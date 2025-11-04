# fomos_crawler.py
import os
import re
import logging
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

# ⚠️ setup_driver / save_to_csv / clean_title / result_csv_data 는 기존 유틸을 사용합니다.
#    setup_driver 안에 "이미지/알림 차단 prefs" 적용을 권장합니다.
from src.etc.utils import setup_driver, save_to_csv, clean_title, result_csv_data


# ===== 실행날짜 & 로깅 =====
today = datetime.now().strftime("%y%m%d")
os.makedirs("log", exist_ok=True)

logging.basicConfig(
    filename=f"log/포모스_log_{today}.txt",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",
)


# ===== 상세 페이지 크롤링 =====
def _close_alert_if_any(wd, url: str) -> bool:
    """경고(alert)창이 있으면 닫고 True 반환, 없으면 False"""
    try:
        WebDriverWait(wd, 2).until(EC.alert_is_present())
        alert = wd.switch_to.alert
        txt = alert.text
        alert.accept()
        logging.warning(f"[상세] 경고창 처리 → '{txt}' → 건너뜀: {url}")
        return True
    except Exception:
        return False


def fomos_crw(wd, url, search) -> pd.DataFrame:
    try:
        logging.info(f"[상세] 크롤링 시작: {url}")
        wd.set_page_load_timeout(15)

        # 페이지 진입
        try:
            wd.get(url)
        except Exception as e:
            logging.error(f"[상세] 페이지 요청 실패(로드 타임아웃/연결): {url} / {e}")
            return pd.DataFrame()

        # alert() 대응 (비공개/삭제글 등)
        if _close_alert_if_any(wd, url):
            return pd.DataFrame()

        # 본문 컨테이너 로드
        try:
            WebDriverWait(wd, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.view_area"))
            )
        except TimeoutException as e:
            logging.error(f"[상세] 본문 컨테이너 로드 실패: {url} / {e}")
            return pd.DataFrame()

        soup = BeautifulSoup(wd.page_source, "html.parser")

        # 제목
        title_el = soup.select_one("div.board_area.common_view > h3")
        if not title_el:
            logging.warning(f"[상세] 제목 엘리먼트 없음: {url}")
            return pd.DataFrame()
        raw_title = title_el.get_text()
        cleaned_title = clean_title(raw_title)

        # 작성자/날짜
        sub_spans = soup.select("p.sub_tit > span")
        if len(sub_spans) < 2:
            logging.warning(f"[상세] 작성자/날짜 엘리먼트 부족: {url}")
            return pd.DataFrame()

        writer = sub_spans[0].get_text(strip=True)
        date_str_raw = sub_spans[1].get_text(strip=True)
        date_str = date_str_raw.split(" ")[0]  # 'YYYY-MM-DD ...'
        try:
            date_val = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            date_val = pd.to_datetime(date_str, errors="coerce")
            if pd.isna(date_val):
                logging.warning(f"[상세] 날짜 파싱 실패: {date_str_raw} ({url})")
                return pd.DataFrame()

        # 본문
        content_div = soup.select_one("div.view_text")
        if not content_div:
            logging.warning(f"[상세] 본문(view_text) 없음: {url}")
            return pd.DataFrame()

        # 미디어 없는 a 태그 제거
        for a_tag in content_div.find_all("a"):
            has_media = (
                a_tag.find("img")
                or a_tag.find("span", class_="scrap_img")
                or a_tag.find("video")
                or (a_tag.find("iframe") and "youtube.com" in a_tag.decode_contents())
            )
            if not has_media:
                a_tag.decompose()

        # 본문 텍스트 정리
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
                "게시물 등록일자": [date_val],
                "계정명": [writer],
            }
        )

        save_to_csv(df_row, f"csv/18.포모스/{today}/포모스_{search}.csv")
        logging.info(f"[상세] 저장 완료: csv/18.포모스/{today}/포모스_{search}.csv")
        return df_row

    except Exception as e:
        logging.error(f"[상세] 오류: {e}")
        return pd.DataFrame()


# ===== 목록 페이지 순회 =====
def _restart_driver(wd):
    """드라이버 재시작(자원 정리용)"""
    try:
        wd.quit()
    except Exception:
        pass
    return setup_driver()


def fomos_main_crw(searchs, start_date, end_date, stop_event):
    os.makedirs(f"csv/18.포모스/{today}", exist_ok=True)
    logging.info("=" * 56)
    logging.info("포모스 크롤링 시작")
    logging.info("=" * 56)

    wd = setup_driver()  # 단일 드라이버 사용
    try:
        for search in searchs:
            if stop_event.is_set():
                print("🛑 크롤링 중단됨")
                break

            page_num = 1
            while True:
                if stop_event.is_set():
                    break
                try:
                    list_url = f"https://www.fomos.kr/search/list?menu=talk&fword={search}&page={page_num}"
                    logging.info(f"[목록] 접속: {list_url}")

                    # 목록 진입
                    try:
                        wd.set_page_load_timeout(15)
                        wd.get(list_url)
                    except Exception as e:
                        logging.error(f"[목록] 페이지 요청 실패: {list_url} / {e}")
                        break

                    # 목록 li 등장 대기
                    try:
                        WebDriverWait(wd, 15).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "div.result_section.r_esports ul.webzine li")
                            )
                        )
                    except TimeoutException:
                        soup_tmp = BeautifulSoup(wd.page_source, "html.parser")
                        if not soup_tmp.select("ul.webzine > li"):
                            logging.info(f"[목록] 결과 없음 → 검색어 '{search}' 종료")
                            break

                    soup = BeautifulSoup(wd.page_source, "html.parser")
                    li_tags = soup.select("ul.webzine > li")
                    if not li_tags:
                        logging.info(f"[목록] li 없음 → 검색어 '{search}' 종료")
                        break

                    for li in li_tags:
                        if stop_event.is_set():
                            break
                        a_tag = li.select_one("div.info p.tit a, p.tit a, p.para a")
                        if not a_tag:
                            logging.info("[목록] 제목 링크 없음 → 건너뜀")
                            continue
                        href = a_tag.get("href") or ""
                        if not href.startswith("/"):
                            logging.info(f"[목록] 비정상 href → 건너뜀: {href}")
                            continue

                        post_url = "https://www.fomos.kr" + href
                        fomos_crw(wd, post_url, search)

                except Exception as e:
                    logging.error(f"[목록] 오류: {e}")
                    break

                # ---- 페이징/자원관리 ----
                page_num += 1
                if page_num % 5 == 0:  # 5페이지마다 크롬 재시작 → 커넥션 풀/메모리 누수 방지
                    logging.info("[리소스 정리] 드라이버 세션 재시작")
                    wd = _restart_driver(wd)

                if page_num >= 15:  # 필요시 조정
                    break

    finally:
        try:
            wd.quit()
        except Exception:
            pass

    # ===== 결과 병합 =====
    if not stop_event.is_set():
        result_dir = "결과/포모스"
        os.makedirs(result_dir, exist_ok=True)
        try:
            all_df = pd.concat(
                [result_csv_data(search, platform="포모스", subdir="18.포모스") for search in searchs],
                ignore_index=True,
            )
            out_path = f"{result_dir}/포모스_raw data_{today}.csv"
            all_df.to_csv(out_path, encoding="utf-8", index=False)
            logging.info(f"[결과] 병합 저장 완료: {out_path}")
        except Exception as e:
            logging.error(f"[결과] 병합 저장 실패: {e}")
