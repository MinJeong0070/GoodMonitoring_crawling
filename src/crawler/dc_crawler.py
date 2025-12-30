import os
import re
import time
import random
import logging
import requests
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from datetime import datetime
from pathlib import Path
import json
PROGRESS_PATH = Path("progress.json")

# 진행상황 JSON(progress.json)을 비우는 초기화 함수
def reset_progress():
    """크롤링 시작 시 진행상황 파일을 빈 JSON으로 초기화"""
    try:
        PROGRESS_PATH.write_text("{}", encoding="utf-8")
        logging.info("[INFO] progress.json reset at crawl start.")
    except Exception as e:
        logging.warning(f"[WARNING] Failed to reset progress.json at start: {e}")

# utils.py 하나에서 모두 가져오도록 통합
from src.etc.utils import (
    setup_driver,
    save_to_csv,
    clean_title,
    result_csv_data,
    safe_get,
    human_sleep,
    last_done_page,
    save_progress,
)

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
os.makedirs('log', exist_ok=True)

logging.basicConfig(
    filename=f'디시인사이드_log_{today}.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# -------------------------------
# DCInside 검색 결과 페이지에서 게시물 목록 URL과 날짜 추출
# -------------------------------
def fetch_list_urls(search: str, page: int):
    """
    검색결과 목록 수집 (requests + BeautifulSoup)
    반환: [(post_url, post_date), ...]
    """
    url = f'https://search.dcinside.com/post/p/{page}/sort/latest/q/{search}'
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": UA})
        r.raise_for_status()
    except Exception as e:
        logging.warning(f"[fetch_list_urls] 요청 실패 p{page} {search}: {e}")
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    ul = soup.find('ul', class_='sch_result_list')
    if not ul:
        logging.info(f"[fetch_list_urls] 결과 리스트 없음 p{page} {search}")
        return []

    out = []
    for li in ul.find_all('li'):
        try:
            date_str = li.find('span', class_='date_time').get_text(strip=True)
            date = datetime.strptime(date_str, '%Y.%m.%d %H:%M').date()
            a = li.find('a', class_='tit_txt')
            href = a.get('href') if a else None

            # 🔹 국제뉴스 갤러리(id=gukjenews)는 크롤링 제외
            if href and "gall.dcinside.com" in href and "id=gukjenews" in href:
                logging.info(f"[fetch_list_urls] 국제뉴스 갤러리 제외: {href}")
                continue

            if href:
                out.append((href, date))
        except Exception:
            continue
    return out


# -------------------------------
# 단일 게시물 상세 정보를 requests로 수집하여 DataFrame으로 반환
# -------------------------------
def dc_crw_detail(wd, url: str, search: str):
    """
    단일 게시물 상세 크롤링 (브라우저 대신 requests 사용)
    - Selenium wd 인자는 호환성 유지만 위해 받고, 내부에서는 사용하지 않음.
    - 외부 링크/iframe은 로딩되지 않아서 더 빠르고 가벼움.
    성공 시 DataFrame(1행), 실패/스킵 시 None
    """
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": UA})
        r.raise_for_status()
    except Exception as e:
        logging.warning(f"[detail] 요청 실패: {url} - {e}")
        return None

    soup = BeautifulSoup(r.text, 'html.parser')

    # 제목
    title_tag = soup.find('h3', class_='title ub-word')
    if title_tag:
        ts = title_tag.find('span', class_='title_subject')
        raw_title = ts.get_text(strip=True) if ts else ""
    else:
        raw_title = ""
    cleaned_title = clean_title(raw_title)

    # 본문
    content_div = soup.find('div', class_='write_div')
    if not content_div:
        post_text = ""
    else:
        # 미디어/OG 제거 + 이미지/영상 포함된 링크만 유지
        for og_tag in content_div.find_all('a', class_='og-wrap'):
            og_tag.decompose()
        for a_tag in content_div.find_all('a'):
            if (
                not a_tag.find('img') and
                not a_tag.find('span', class_='scrap_img') and
                not a_tag.find('video') and
                not (a_tag.find('iframe') and 'youtube.com' in a_tag.decode_contents())
            ):
                a_tag.decompose()
        post_text = content_div.get_text(separator='\n', strip=True)
        post_text = re.sub(r'http[s]?://\S+', '', post_text)

    # 날짜
    try:
        date_str = soup.find('span', class_='gall_date').get_text(strip=True)
        post_date = datetime.strptime(date_str, '%Y.%m.%d %H:%M:%S').date()
    except Exception:
        post_date = None

    # 작성자 (닉네임 + IP)
    try:
        nickname = soup.find('span', class_='nickname').get_text(strip=True)
    except Exception:
        nickname = ""
    ip_tag = soup.find('span', class_='ip')
    ip_address = ip_tag.get_text(strip=True) if ip_tag else ""
    writer = f"{nickname}{ip_address}"

    df = pd.DataFrame({
        "검색어": [search],
        "플랫폼": ['웹페이지(dcinside)'],
        "게시물 URL": [url],
        "게시물 제목": [cleaned_title],
        "게시물 내용": [post_text],
        "게시물 등록일자": [post_date],
        "계정명": [writer],
    })
    return df


# -------------------------------
# 검색어 리스트에 대해 디시인사이드 크롤링 전체 실행 (목록+상세+저장+병합)
# -------------------------------
def dc_main_crw(searchs, start_date, end_date, stop_event):
    """
    - 목록: requests / 상세: (기존 Selenium 대신) requests
    - 진행상황(progress.json) 저장 → 죽어도 이어서
    - 페이지/게시물 실패는 스킵하고 계속
    - 키워드 배치마다 드라이버 재생성 (호환성 유지용, 현재는 상세에 사용 X)
    """
    out_dir = f'csv/22.디시인사이드/{today}'
    os.makedirs(out_dir, exist_ok=True)

    logging.info("=" * 56)
    logging.info("                 디시인사이드 크롤링 시작")
    logging.info("=" * 56)

    # 🔹 추가: 크롤링 시작 시 진행상황 리셋
    reset_progress()

    wd_detail = setup_driver()
    processed_keywords = 0

    try:
        for search in searchs:
            if stop_event.is_set():
                print("🛑 크롤링 중단됨")
                break

            if processed_keywords > 0 and (processed_keywords % 15) == 0:
                try:
                    wd_detail.quit()
                except Exception:
                    pass
                wd_detail = setup_driver()

            page_num = last_done_page(search, default_page=1)
            logging.info(f"[{search}] 시작 페이지: {page_num}")

            while True:
                if stop_event.is_set():
                    break
                if page_num >= 121:  # 최대 120페이지
                    break

                # 목록 수집
                pairs = fetch_list_urls(search, page_num)
                if not pairs:
                    page_num += 1
                    save_progress(search, page_num)
                    continue

                after_start_flag = False  # 시작일 이전 글 만나면 종료
                for post_url, post_date in pairs:
                    if stop_event.is_set():
                        break

                    # 날짜 필터
                    if post_date and post_date > end_date:
                        continue
                    if post_date and post_date < start_date:
                        after_start_flag = True
                        break

                    fail_streak = 0

                    # 상세 수집
                    try:
                        one = dc_crw_detail(wd_detail, post_url, search)
                        if one is not None:
                            save_to_csv(one, f'{out_dir}/디시인사이드_{search}.csv')
                            fail_streak = 0
                        else:
                            fail_streak += 1
                    except Exception as e:
                        logging.error(f"[{search}] 상세 실패: {e}")
                        fail_streak += 1

                    if fail_streak >= 3:
                        logging.info("[driver] 실패 누적 → 드라이버 재기동")
                        try:
                            wd_detail.quit()
                        except Exception:
                            pass
                        wd_detail = setup_driver()
                        fail_streak = 0

                    human_sleep()  # 속도 제어

                if after_start_flag:
                    break

                page_num += 1
                save_progress(search, page_num)

            processed_keywords += 1

    finally:
        try:
            wd_detail.quit()
        except Exception:
            pass

    # 최종 머지 (중단 시 생략)
    if not stop_event.is_set():
        result_dir = '결과/디시인사이드'
        os.makedirs(result_dir, exist_ok=True)

        frames = []
        for search in searchs:
            try:
                part = result_csv_data(search, platform='디시인사이드', subdir='22.디시인사이드')
                if part is not None and len(part) > 0:
                    frames.append(part)
            except Exception as e:
                logging.error(f"[merge] {search} 병합 실패: {e}")

        if frames:
            all_data = pd.concat(frames, ignore_index=True)
            all_data.to_csv(
                f'{result_dir}/디시인사이드_raw data_{today}.csv',
                encoding='utf-8',
                index=False
            )
            logging.info(f"[merge] 저장 완료: {result_dir}/디시인사이드_raw data_{today}.csv")
        else:
            logging.info("[merge] 병합할 데이터가 없습니다.")
