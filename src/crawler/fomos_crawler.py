import os
import re
import time
import logging
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from src.etc.utils import setup_driver, save_to_csv, clean_title, result_csv_data

# 실행날짜 및 로그 설정
today = datetime.now().strftime("%y%m%d")

if not os.path.exists("log"):
    os.makedirs("log")

logging.basicConfig(
    filename=f"log/포모스_log_{today}.txt",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",
)


def _extract_date_from_text(text: str):
    """
    목록 li 전체 텍스트에서 YYYY-MM-DD 패턴을 찾아 date 객체로 변환.
    포맷이 다르면 여기만 수정하면 됨.
    """
    if not text:
        return None
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if not m:
        return None
    date_str = m.group(1)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def fomos_crw(wd, url: str, search: str, post_date):
    """
    포모스 상세 페이지 한 건 크롤링
    - wd: 상세 페이지용 WebDriver
    - url: 게시물 URL
    - search: 검색어
    - post_date: 목록에서 파싱한 게시일 (datetime.date)
    """
    try:
        logging.info(f"[상세] 크롤링 시작: {url}")
        wd.set_page_load_timeout(15)
        wd.get(url)

        try:
            WebDriverWait(wd, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.board_area.common_view")
                )
            )
        except TimeoutException:
            logging.error(f"[상세] 본문 컨테이너 로드 실패: {url}")
            return pd.DataFrame()

        soup = BeautifulSoup(wd.page_source, "html.parser")

        # 제목
        title_el = soup.select_one("div.board_area.common_view > h3")
        if not title_el:
            logging.warning(f"[상세] 제목 요소 없음: {url}")
            return pd.DataFrame()
        raw_title = title_el.get_text(strip=True)
        cleaned_title = clean_title(raw_title)

        # 작성자 (첫 번째 span 시도, 없으면 공백)
        writer = ""
        sub_tit = soup.select_one("p.sub_tit")
        if sub_tit:
            spans = sub_tit.find_all("span")
            if spans:
                writer = spans[0].get_text(strip=True)

        # 본문
        content_div = soup.select_one("div.view_text")
        if not content_div:
            logging.warning(f"[상세] 본문(view_text) 없음: {url}")
            return pd.DataFrame()

        # 하이퍼링크 중 미디어가 없는 a 태그 제거 (텍스트 노이즈 줄이기)
        for a_tag in content_div.find_all("a"):
            has_media = (
                a_tag.find("img")
                or a_tag.find("video")
                or (a_tag.find("iframe") and "youtube.com" in a_tag.decode_contents())
            )
            if not has_media:
                a_tag.decompose()

        post_content = content_div.get_text(separator="\n", strip=True)
        post_content = re.sub(r"https?://\S+", "", post_content)
        post_content = re.sub(r"\n{2,}", "\n", post_content).strip()

        df_row = pd.DataFrame(
            {
                "검색어": [search],
                "플랫폼": ["웹페이지(포모스)"],
                "게시물 URL": [url],
                "게시물 제목": [cleaned_title],
                "게시물 내용": [post_content],
                "게시물 등록일자": [post_date],
                "계정명": [writer],
            }
        )

        save_to_csv(df_row, f"csv/18.포모스/{today}/포모스_{search}.csv")
        logging.info(f"[상세] 저장 완료: csv/18.포모스/{today}/포모스_{search}.csv")
        return df_row

    except Exception as e:
        logging.error(f"[상세] 오류 발생: {e}")
        return pd.DataFrame()


def fomos_main_crw(searchs, start_date, end_date, stop_event):
    """
    포모스 메인 크롤러
    - searchs: 검색어 리스트
    - start_date, end_date: 'YYYY-MM-DD' 또는 date 객체 (GUI에서 넘어옴)
    - stop_event: 쓰레드 중단 이벤트
    """
    # CSV 폴더 생성
    csv_dir = f"csv/18.포모스/{today}"
    if not os.path.exists(csv_dir):
        os.makedirs(csv_dir)
        print(f"폴더 생성 완료: {csv_dir}")

    logging.info("========================================================")
    logging.info("                    포모스 크롤링 시작")
    logging.info("========================================================")

    # 날짜 형식 통일
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    elif isinstance(start_date, datetime):
        start_date = start_date.date()

    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    elif isinstance(end_date, datetime):
        end_date = end_date.date()

    wd = setup_driver()        # 상세 페이지용
    wd_list = setup_driver()   # 목록용

    try:
        for search in searchs:
            if stop_event.is_set():
                print("🛑 크롤링 중단됨")
                break

            page_num = 1
            logging.info(f"[검색어] '{search}' 크롤링 시작")

            while True:
                if stop_event.is_set():
                    break

                try:
                    list_url = (
                        f"https://www.fomos.kr/search/list?menu=talk&fword={search}"
                        f"&page={page_num}"
                    )
                    logging.info(f"[목록] 접속: {list_url}")
                    wd_list.set_page_load_timeout(15)
                    wd_list.get(list_url)

                    # 목록 li 로딩 대기
                    try:
                        WebDriverWait(wd_list, 15).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "ul.webzine li")
                            )
                        )
                    except TimeoutException:
                        soup_tmp = BeautifulSoup(wd_list.page_source, "html.parser")
                        li_check = soup_tmp.select("ul.webzine li")
                        if not li_check:
                            logging.info(f"[목록] 결과 없음 → '{search}' 종료")
                            break

                    soup = BeautifulSoup(wd_list.page_source, "html.parser")
                    li_tags = soup.select("ul.webzine > li")
                    if not li_tags:
                        logging.info(f"[목록] li 없음 → '{search}' 종료")
                        break

                    after_start_date = False  # 시작일 이전 게시글에 도달했는지 여부

                    for li in li_tags:
                        if stop_event.is_set():
                            break

                        # 1) li 전체 텍스트에서 날짜 추출
                        li_text = li.get_text(" ", strip=True)
                        post_date = _extract_date_from_text(li_text)
                        if not post_date:
                            logging.warning("[목록] 날짜 추출 실패 → 건너뜀")
                            continue

                        # 2) 날짜 기준 필터링 (뽐뿌와 동일 로직)
                        if post_date > end_date:
                            # 끝 날짜 이후(너무 최신) 글 → 건너뛰고 계속
                            continue
                        if post_date < start_date:
                            # 시작 날짜보다 이전 글이 나오면 이 검색어는 종료
                            after_start_date = True
                            logging.info(
                                f"[목록] 시작일 이전({post_date}) 글 도달 → '{search}' 종료"
                            )
                            break

                        # 3) 날짜 범위 안 → 상세 페이지 URL 추출 후 크롤링
                        a_tag = li.select_one("p.tit a, div.info p.tit a, p.para a")
                        if not a_tag:
                            logging.info("[목록] 제목 링크 없음 → 건너뜀")
                            continue

                        href = a_tag.get("href") or ""
                        if not href.startswith("/"):
                            logging.info(f"[목록] 비정상 href → 건너뜀: {href}")
                            continue

                        post_url = "https://www.fomos.kr" + href
                        fomos_crw(wd, post_url, search, post_date)

                    # 시작 날짜 이전 게시글을 만났으면 현재 검색어 종료
                    if after_start_date:
                        break

                    # 다음 페이지로
                    page_num += 1

                except Exception as e:
                    logging.error(f"[목록] 오류 발생: {e}")
                    break

    finally:
        wd.quit()
        wd_list.quit()

    # ===== 결과 병합 =====
    if not stop_event.is_set():
        result_dir = "결과/포모스"
        if not os.path.exists(result_dir):
            os.makedirs(result_dir)
        try:
            all_data = pd.concat(
                [
                    result_csv_data(search, platform="포모스", subdir="18.포모스")
                    for search in searchs
                ],
                ignore_index=True,
            )
            print(all_data.count())
            out_path = f"{result_dir}/포모스_raw data_{today}.csv"
            all_data.to_csv(out_path, encoding="utf-8", index=False)
            logging.info(f"[결과] 병합 저장 완료: {out_path}")
        except Exception as e:
            logging.error(f"[결과] 병합 저장 실패: {e}")
