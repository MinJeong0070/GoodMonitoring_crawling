# src/crawler/mlb_crawler.py

import os
import re
import random
import time
import logging
from urllib.parse import urljoin
from datetime import datetime, date as date_cls

import pandas as pd
from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.etc.utils import setup_driver, save_to_csv, clean_title, result_csv_data

# ===== 설정/공통 =====
BASE = "https://mlbpark.donga.com"
PAGELOAD_TIMEOUT = 30          # 페이지로드 타임아웃(초)
DETAIL_RETRY_MAX = 2           # 상세 페이지 진입 재시도 횟수
LIST_RETRY_MAX = 2             # 목록 페이지 진입 재시도 횟수

AD_BLOCK_PATTERNS = [
    "*mediacategory.com*",
    "*contentsfeed.com*",
    "*clickmon.co.kr*",
    "*adpnut.com*",
    "*megadata.co.kr*",
    "*kas/static/ba.min.js*",
    "*tab2.clickmon.co.kr*",
]

today_str_yymmdd = datetime.now().strftime("%y%m%d")
LOG_DIR = "log"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=f'엠엘비파크_log_{today_str_yymmdd}.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

def _rand_sleep(a=0.6, b=1.6):
    time.sleep(random.uniform(a, b))

def _prepare_driver(wd):
    """공통 드라이버 세팅: 페이지 타임아웃 + 광고 차단(CDP)"""
    try:
        wd.set_page_load_timeout(PAGELOAD_TIMEOUT)
    except Exception:
        pass
    try:
        wd.execute_cdp_cmd("Network.enable", {})
        wd.execute_cdp_cmd("Network.setBlockedURLs", {"urls": AD_BLOCK_PATTERNS})
    except Exception:
        # 일부 환경에선 CDP가 막혀 있을 수 있음 -> 무시
        pass

def _safe_text(el) -> str:
    return el.get_text(strip=True) if el else ""

def _format_date(d: date_cls | None) -> str:
    return d.strftime("%Y-%m-%d") if d else ""

def _parse_list_date(raw_text: str) -> date_cls | None:
    """목록 날짜 표기를 안전하게 일자(date)로 환원"""
    if not raw_text:
        return None
    raw = raw_text.strip()
    try:
        if re.fullmatch(r"\d{2}:\d{2}:\d{2}", raw):  # HH:MM:SS (오늘)
            return datetime.now().date()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):  # YYYY-MM-DD
            return datetime.strptime(raw, "%Y-%m-%d").date()
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)   # YYYY-MM-DD HH:MM[:SS]
        if m:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except Exception as e:
        logging.error(f"목록 날짜 파싱 실패: raw='{raw}', err={e}", exc_info=True)
    return None

def _safe_get(wd, url: str, wait_css: str | None = None, retries: int = 1) -> bool:
    """
    크롬이 로딩을 끝내지 못하고 멈출 때를 대비해:
    - 페이지 로드 타임아웃 설정
    - 타임아웃 시 window.stop() 으로 강제 정지 후, 필요하면 대기
    - 지정 횟수만큼 재시도
    """
    for attempt in range(1, retries + 1):
        try:
            wd.get(url)
            if wait_css:
                WebDriverWait(wd, 12).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_css))
                )
            return True
        except TimeoutException:
            logging.warning(f"[GET 타임아웃] {url} (시도 {attempt}/{retries})")
            try:
                wd.execute_script("window.stop();")
            except Exception:
                pass
            if wait_css:
                try:
                    WebDriverWait(wd, 6).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, wait_css))
                    )
                    return True
                except Exception:
                    pass
        except WebDriverException as e:
            logging.error(f"[GET 오류] {url} - {e}")
        _rand_sleep(0.8, 1.6)
    return False

# ===== 상세 페이지 크롤링 =====
def mlb_crw(wd, url: str, search: str, list_date_hint: date_cls | None = None) -> bool:
    """
    단일 게시물 상세 페이지 크롤링.
    성공 시 True, 실패 시 False.
    list_date_hint: 목록에서 읽어온 날짜(YYYY-MM-DD) 폴백용
    """
    try:
        logging.info(f"[상세] 이동: {url} (검색어: {search})")
        ok = _safe_get(wd, url, wait_css="#contentDetail", retries=DETAIL_RETRY_MAX)
        if not ok:
            logging.error(f"[상세] 페이지 진입 실패(타임아웃/오류 지속): {url}")
            return False
        _rand_sleep(0.6, 1.2)

        soup = BeautifulSoup(wd.page_source, "html.parser")

        # 제목
        title_el = soup.select_one("div.titles, h1.tit, div.view_tit, .tit_cont .tit, .view_top .tit")
        if title_el:
            word_span = title_el.select_one("span.word")
            if word_span:
                word_span.decompose()
        raw_title = _safe_text(title_el)
        cleaned_title = clean_title(raw_title)

        # 본문
        content_tag = soup.select_one("#contentDetail")
        post_content = ""
        if content_tag:
            tool_div = content_tag.select_one("div.tool_cont")
            if tool_div:
                tool_div.decompose()
            # 본문 내 불필요 링크 제거(이미지/영상/스크랩 제외)
            for a_tag in content_tag.find_all('a'):
                try:
                    if (
                        not a_tag.find('img')
                        and not a_tag.find('span', class_='scrap_img')
                        and not a_tag.find('video')
                        and not (a_tag.find('iframe') and 'youtube.com' in str(a_tag))
                    ):
                        a_tag.decompose()
                except Exception:
                    pass
            post_content = content_tag.get_text(separator='\n', strip=True)
            post_content = re.sub(r'http[s]?://\S+', '', post_content)

        # 작성자
        author_el = soup.select_one("span.nick, span.writer, div.nick, .post_info .nick, .view_top .nick")
        author = _safe_text(author_el)

        # 작성일 (여러 후보 + 폴백)
        DATE_SELECTORS = [
            "span.date", "div.date", "time", "div.text3 span.val",
            ".tit_cont .date", ".view_tit .date", ".view_top .date",
            ".post_info .date", ".title_area .date", ".view_info .date"
        ]
        post_dt_raw = ""
        for sel in DATE_SELECTORS:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                post_dt_raw = el.get_text(strip=True)
                break

        post_date = ""
        try:
            if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", post_dt_raw):
                dt = datetime.strptime(post_dt_raw[:16], "%Y-%m-%d %H:%M")
                post_date = dt.strftime("%Y-%m-%d")
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", post_dt_raw):
                dt = datetime.strptime(post_dt_raw, "%Y-%m-%d")
                post_date = dt.strftime("%Y-%m-%d")
            else:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", post_dt_raw)
                if m:
                    post_date = m.group(1)

            # 여전히 비어 있으면 페이지 전체 텍스트에서 폴백 검색
            if not post_date:
                m2 = re.search(r"(\d{4}-\d{2}-\d{2})", soup.get_text(" ", strip=True))
                if m2:
                    post_date = m2.group(1)
        except Exception as e:
            logging.error(f"상세 날짜 파싱 실패: raw='{post_dt_raw}', err={e}", exc_info=True)

        # 최종 폴백: 목록에서 읽은 날짜
        if not post_date and list_date_hint:
            post_date = _format_date(list_date_hint)

        df = pd.DataFrame({
            "검색어": [search],
            "플랫폼": ["웹페이지(MLBPARK)"],
            "게시물 URL": [url],
            "게시물 제목": [cleaned_title],
            "게시물 내용": [post_content],
            "게시물 등록일자": [post_date],
            "계정명": [author],
        })
        save_to_csv(df, f'csv/21.엠엘비파크/{today_str_yymmdd}/엠엘비파크_{search}.csv')
        logging.info(f"[상세] 저장 완료: {url}")

        # 무거운 페이지 잔상 제거
        try:
            wd.get("about:blank")
        except Exception:
            pass
        return True

    except Exception as e:
        logging.error(f"[상세] 크롤링 실패: url={url}, err={e}", exc_info=True)
        return False

# ===== 메인(리스트 페이지 순회) =====
def mlb_main_crw(searchs, start_date, end_date, stop_event):
    """
    searchs: 검색어 리스트
    start_date/end_date: datetime.date 객체
    stop_event: threading.Event
    """
    out_dir = f'csv/21.엠엘비파크/{today_str_yymmdd}'
    os.makedirs(out_dir, exist_ok=True)

    logging.info("=" * 60)
    logging.info("엠엘비파크 크롤링 시작")
    logging.info("=" * 60)

    wd = setup_driver()
    _prepare_driver(wd)
    wd_list = setup_driver()
    _prepare_driver(wd_list)

    try:
        for search in searchs:
            if stop_event.is_set():
                logging.info("🛑 stop_event 감지 - 중단")
                break

            page_num = 1
            visited_urls = set()
            logging.info(f"[검색어 시작] '{search}'")

            while True:
                if stop_event.is_set():
                    logging.info("🛑 stop_event 감지 - 페이지 루프 종료")
                    break

                list_url = (
                    f"{BASE}/mp/b.php?p={page_num}&m=search&b=bullpen"
                    f"&query={search}&select=sct&subquery=&subselect=&user="
                )
                logging.info(f"[목록] 이동: {list_url}")

                # 목록 페이지 진입(재시도 포함)
                ok = _safe_get(wd_list, list_url, wait_css="table.tbl_type01", retries=LIST_RETRY_MAX)
                if not ok:
                    logging.error(f"[목록] 페이지 진입 실패: {list_url}")
                    # 드물게 드라이버가 죽었을 수 있으니 재기동
                    try:
                        wd_list.quit()
                    except Exception:
                        pass
                    wd_list = setup_driver()
                    _prepare_driver(wd_list)
                    # 다음 페이지로 넘어가며 계속
                    page_num += 30
                    continue

                _rand_sleep(0.4, 1.0)

                soup_list = BeautifulSoup(wd_list.page_source, "html.parser")
                tbody = soup_list.select_one("table.tbl_type01 > tbody")
                if not tbody:
                    logging.warning("[목록] tbody 없음 - 종료")
                    break

                rows = tbody.select("tr")
                if not rows:
                    logging.info("[목록] 행 없음 - 종료")
                    break

                reached_before_start = False
                consecutive_detail_fail = 0

                for tr in rows:
                    if stop_event.is_set():
                        break

                    # 날짜 필터
                    list_date = _parse_list_date(_safe_text(tr.select_one("span.date")))
                    if not list_date:
                        continue
                    if list_date > end_date:
                        continue
                    if list_date < start_date:
                        reached_before_start = True
                        break

                    # 링크
                    link_el = tr.select_one("div.tit > a.txt, td.t_left a.txt")
                    if not link_el:
                        continue
                    href = (link_el.get("href") or "").strip()
                    if not href:
                        continue
                    abs_url = urljoin(BASE, href)
                    if abs_url in visited_urls:
                        continue
                    visited_urls.add(abs_url)

                    # 상세
                    ok = mlb_crw(wd, abs_url, search, list_date_hint=list_date)
                    if not ok:
                        consecutive_detail_fail += 1
                        if consecutive_detail_fail >= 2:
                            # 연속 실패 시 상세 드라이버 재기동 후 계속
                            logging.warning("[상세] 연속 실패 → 드라이버 재기동 시도")
                            try:
                                wd.quit()
                            except Exception:
                                pass
                            wd = setup_driver()
                            _prepare_driver(wd)
                            consecutive_detail_fail = 0
                    else:
                        consecutive_detail_fail = 0

                if reached_before_start:
                    logging.info(f"[검색어 종료] '{search}' - 시작일 이전 도달")
                    break

                page_num += 30  # 엠팍 검색 페이징은 30 단위

    finally:
        for drv in (wd, wd_list):
            try:
                drv.quit()
            except Exception:
                pass

    # 최종 병합
    if not stop_event.is_set():
        try:
            result_dir = '결과/엠엘비파크'
            os.makedirs(result_dir, exist_ok=True)

            dfs = []
            for search in searchs:
                try:
                    df = result_csv_data(search, platform='엠엘비파크', subdir='21.엠엘비파크')
                    if df is not None and not df.empty:
                        dfs.append(df)
                except Exception as e:
                    logging.error(f"[병합] '{search}' result_csv_data 실패: {e}", exc_info=True)

            if dfs:
                all_data = pd.concat(dfs, ignore_index=True)
                out_path = f'{result_dir}/엠엘비파크_raw data_{today_str_yymmdd}.csv'
                all_data.to_csv(out_path, encoding='utf-8', index=False)
                logging.info(f"[병합] 최종 저장 완료: {out_path}")
            else:
                logging.warning("[병합] 결합할 데이터가 없습니다.")
        except Exception as e:
            logging.error(f"[병합] 최종 병합 실패: {e}", exc_info=True)
