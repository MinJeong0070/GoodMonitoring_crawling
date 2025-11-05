# cook82_crawler.py
import os
import re
import logging
from datetime import datetime, date

import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from src.etc.utils import setup_driver, save_to_csv, clean_title, result_csv_data


# ===== 실행날짜 & 로깅 =====
today = datetime.now().strftime("%y%m%d")
os.makedirs("log", exist_ok=True)

logging.basicConfig(
    filename=f"log/82쿡_log_{today}.txt",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",
)


# ===== 목록 날짜 파서 =====
def _parse_list_date(td) -> date | None:
    """82쿡 목록 날짜 파싱: title(YYYY-MM-DD hh:mm:ss) 우선 → 텍스트 보조(YYYY/MM/DD 또는 YYYY-MM-DD)."""
    if td is None:
        return None

    title = (td.get("title") or "").strip()
    if title:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", title)
        if m:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()

    txt = td.get_text(strip=True)
    if re.match(r"\d{4}/\d{2}/\d{2}", txt):
        return datetime.strptime(txt[:10], "%Y/%m/%d").date()
    if re.match(r"\d{4}-\d{2}-\d{2}", txt):
        return datetime.strptime(txt[:10], "%Y-%m-%d").date()

    return None


# ===== 상세 페이지 크롤링 =====
def cook82_crw(wd, url, search) -> pd.DataFrame:
    try:
        logging.info(f"[상세] 크롤링 시작: {url}")
        wd.set_page_load_timeout(15)
        wd.get(url)

        # 본문 컨테이너 로드
        try:
            WebDriverWait(wd, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#articleBody"))
            )
        except TimeoutException as e:
            logging.error(f"[상세] 본문 컨테이너 로드 실패: {url} / {e}")
            return pd.DataFrame()

        soup = BeautifulSoup(wd.page_source, "html.parser")

        # 제목
        h4 = soup.select_one("h4.title.bbstitle > span")
        if not h4:
            logging.warning(f"[상세] 제목 엘리먼트 없음: {url}")
            return pd.DataFrame()
        raw_title = h4.get_text()
        cleaned_title = clean_title(raw_title)
        logging.info(f"[상세] 제목 추출: {cleaned_title}")

        # 본문
        content_div = soup.select_one("#articleBody")
        if not content_div:
            logging.warning(f"[상세] 본문 엘리먼트 없음: {url}")
            return pd.DataFrame()

        # 이미지/영상/유튜브가 없는 a 태그 제거
        for a in content_div.find_all("a"):
            has_media = (
                a.find("img")
                or a.find("span", class_="scrap_img")
                or a.find("video")
                or (a.find("iframe") and "youtube.com" in a.decode_contents())
            )
            if not has_media:
                a.decompose()

        post_content = content_div.get_text(separator=" ", strip=True)
        post_content = re.sub(r"https?://\S+", "", post_content).strip()

        # 작성자
        writer_el = soup.select_one("div.readLeft a")
        writer = writer_el.get_text(strip=True) if writer_el else ""

        # 상세 날짜: readRight 텍스트에서 YYYY-MM-DD / YYYY/MM/DD 탐색
        right_txt = soup.select_one("div.readRight")
        if not right_txt:
            logging.warning(f"[상세] 날짜 영역 없음: {url}")
            return pd.DataFrame()
        date_text = right_txt.get_text(" ", strip=True)
        m = re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", date_text)
        if not m:
            logging.warning(f"[상세] 날짜 형식 인식 실패: {date_text}")
            return pd.DataFrame()
        date_str = m.group(0).replace("/", "-")
        reg_dt = datetime.strptime(date_str, "%Y-%m-%d")

        df = pd.DataFrame(
            {
                "검색어": [search],
                "플랫폼": ["웹페이지(82쿡)"],
                "게시물 URL": [url],
                "게시물 제목": [cleaned_title],
                "게시물 내용": [post_content],
                "게시물 등록일자": [reg_dt],
                "계정명": [writer],
                "수집시간": [datetime.now().strftime("%Y-%m-%d")],
            }
        )

        save_to_csv(df, f"csv/12.82쿡/{today}/82쿡_{search}.csv")
        logging.info(f"[상세] 저장 완료: csv/12.82쿡/{today}/82쿡_{search}.csv")
        return df

    except Exception as e:
        logging.error(f"[상세] 오류: {e}")
        return pd.DataFrame()


# ===== 목록 순회 =====
def cook82_main_crw(searchs, start_date, end_date, stop_event):
    os.makedirs(f"csv/12.82쿡/{today}", exist_ok=True)
    logging.info("=" * 55)
    logging.info("82쿡 크롤링 시작")
    logging.info("=" * 55)

    # 단일 드라이버로도 충분하지만, 기존 구조 유지가 필요하면 두 개를 사용
    wd = setup_driver()
    wd_dp1 = setup_driver()

    try:
        for search in searchs:
            if stop_event.is_set():
                logging.info("🛑 중단 플래그 감지")
                break

            page_num = 1
            while True:
                if stop_event.is_set():
                    break

                try:
                    list_url = (
                        f"https://www.82cook.com/entiz/enti.php?"
                        f"bn=15&searchType=search&search1=1&keys={search}&page={page_num}"
                    )
                    logging.info(f"[목록] 접속: {list_url}")
                    wd_dp1.set_page_load_timeout(15)
                    wd_dp1.get(list_url)

                    # 목록 tr까지 로드될 때까지 대기
                    try:
                        WebDriverWait(wd_dp1, 15).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "#bbs table tbody tr")
                            )
                        )
                    except TimeoutException:
                        # 결과 없음 페이지일 수 있으므로 검사하고 종료
                        soup_tmp = BeautifulSoup(wd_dp1.page_source, "html.parser")
                        if not soup_tmp.select("#bbs table tbody tr td.title a"):
                            logging.info("[목록] 검색결과 없음 → 종료")
                            break

                    soup_dp1 = BeautifulSoup(wd_dp1.page_source, "html.parser")

                    # 검색결과 행 수집
                    tr_tags = soup_dp1.select("#bbs table tbody tr")
                    if not tr_tags:
                        logging.info("[목록] tr 없음 → 종료")
                        break

                    logging.info("[목록] 검색목록 찾음.")
                    after_start_date = False

                    for tr in tr_tags:
                        if stop_event.is_set():
                            break

                        # 공지/빈행 제거
                        if "noticeList" in tr.get("class", []):
                            continue
                        title_a = tr.select_one("td.title a")
                        if not title_a:
                            continue

                        # 날짜 셀 추출 + 파싱
                        td_date = tr.select_one("td.regdate.numbers")
                        if td_date is None:
                            logging.warning("[목록] 날짜 셀 없음 → 건너뜀")
                            continue
                        try:
                            reg_date = _parse_list_date(td_date)
                            if not reg_date:
                                logging.warning(
                                    f"[목록] 날짜 형식 인식 실패: "
                                    f"{td_date.get('title','') or td_date.get_text(strip=True)}"
                                )
                                continue
                            logging.info(f"[목록] 날짜 찾음: {reg_date}")
                        except Exception as e:
                            logging.error(f"[목록] 날짜 오류: {e}")
                            continue

                        # 날짜 필터
                        if reg_date > end_date:
                            continue
                        if reg_date < start_date:
                            after_start_date = True
                            break

                        # 상세 URL
                        href = title_a.get("href") or ""
                        if not href.startswith("read.php"):
                            # 페이지네이션/광고 링크 등은 스킵
                            continue
                        post_url = "https://www.82cook.com/entiz/" + href
                        logging.info("[목록] 상세 URL 찾음")

                        cook82_crw(wd, post_url, search)

                    if after_start_date:
                        break
                    page_num += 1

                except Exception as e:
                    logging.error(f"[목록] 오류: {e}")
                    break

    finally:
        try:
            wd.quit()
        except Exception:
            pass
        try:
            wd_dp1.quit()
        except Exception:
            pass

    # ===== 결과 병합 =====
    if not stop_event.is_set():
        result_dir = "결과/82쿡"
        os.makedirs(result_dir, exist_ok=True)
        try:
            all_df = pd.concat(
                [
                    result_csv_data(search, platform="82쿡", subdir="12.82쿡")
                    for search in searchs
                ],
                ignore_index=True,
            )
            out_path = f"{result_dir}/82쿡_raw data_{today}.csv"
            all_df.to_csv(out_path, encoding="utf-8", index=False)
            logging.info(f"[결과] 병합 저장 완료: {out_path}")
        except Exception as e:
            logging.error(f"[결과] 병합 저장 실패: {e}")
