# fomos_crawler.py
import os
import re
import logging
from datetime import datetime
import time

import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

# ⚠️ setup_driver / save_to_csv / clean_title / result_csv_data 는 기존 유틸 사용
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


# 새로 열린 탭이 있을 경우 모두 닫고 메인 탭으로 복귀
def _close_extra_tabs(wd):
    """메인 탭(첫 번째)을 제외한 모든 탭을 닫습니다."""
    try:
        if len(wd.window_handles) > 1:
            main_handle = wd.window_handles[0]
            for handle in wd.window_handles:
                if handle != main_handle:
                    wd.switch_to.window(handle)
                    wd.close()
            wd.switch_to.window(main_handle)
    except Exception:
        pass


# 페이지 내 alert 창이 뜨면 자동으로 닫고 실패로 처리
def _close_alert_if_any(wd, url: str) -> bool:
    """경고(alert)창이 있으면 닫고 True 반환"""
    try:
        WebDriverWait(wd, 1).until(EC.alert_is_present())
        alert = wd.switch_to.alert
        alert.accept()
        return True
    except Exception:
        return False


# 포모스 상세 페이지에서 게시글 정보 추출 및 개별 CSV 저장
def fomos_crw(wd, url, search) -> str:
    """
    반환값: "ok" (성공), "fail" (실패), "fatal" (브라우저 먹통/재시작 필요)
    """
    try:
        wd.set_page_load_timeout(15)  # 타임아웃 조금 여유 있게 (10->15)

        try:
            wd.get(url)
            _close_extra_tabs(wd)
        except Exception as e:
            logging.error(f"[상세] 페이지 로드 치명적 오류: {url} / {e}")
            return "fatal"  # 브라우저 연결 끊김 의심

        if _close_alert_if_any(wd, url):
            return "fail"

        try:
            WebDriverWait(wd, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.view_area"))
            )
        except TimeoutException:
            return "fail"

        soup = BeautifulSoup(wd.page_source, "html.parser")

        # 제목
        title_el = soup.select_one("div.board_area.common_view > h3")
        if not title_el: return "fail"

        raw_title = title_el.get_text()
        cleaned_title = clean_title(raw_title)

        # 작성자/날짜
        sub_spans = soup.select("p.sub_tit > span")
        if len(sub_spans) < 2: return "fail"

        writer = sub_spans[0].get_text(strip=True)
        date_str_raw = sub_spans[1].get_text(strip=True)
        date_str = date_str_raw.split(" ")[0]

        try:
            date_val = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            date_val = pd.to_datetime(date_str, errors="coerce")
            if pd.isna(date_val): return "fail"

        # 본문
        content_div = soup.select_one("div.view_text")
        if not content_div: return "fail"

        # 미디어 태그 정리
        for tag in content_div.find_all(["script", "style", "iframe", "video", "img"]):
            # 이미지는 제거 (속도 향상 및 텍스트 위주)
            tag.decompose()

        post_content = content_div.get_text(separator="\n", strip=True)
        post_content = re.sub(r"https?://\S+", "", post_content)
        post_content = re.sub(r"\n{2,}", "\n", post_content).strip()

        df_row = pd.DataFrame({
            "검색어": [search],
            "플랫폼": ["웹페이지(포모스)"],
            "게시물 URL": [url],
            "게시물 제목": [cleaned_title],
            "게시물 내용": [post_content],
            "게시물 등록일자": [date_val],
            "계정명": [writer],
        })

        save_to_csv(df_row, f"csv/18.포모스/{today}/포모스_{search}.csv")
        logging.info(f"[저장] {cleaned_title}")
        return "ok"

    except WebDriverException:
        return "fatal"  # 셀레니움 연결 끊김
    except Exception as e:
        logging.error(f"[상세] 일반 오류: {e}")
        return "fail"


# ===== 드라이버 재시작 함수 =====
# 브라우저 재시작 로직 (에러 발생 시 메모리 누수 방지)
def _restart_driver(wd):
    logging.warning("⚠️ [시스템] 드라이버 재시작 시도...")
    try:
        wd.quit()
    except:
        pass
    time.sleep(2)
    new_wd = setup_driver()
    logging.warning("✅ [시스템] 드라이버 재시작 완료")
    return new_wd


# 검색어 목록에 대해 포모스 게시글 크롤링 전체 수행 및 결과 병합 저장
def fomos_main_crw(searchs, start_date, end_date, stop_event):
    os.makedirs(f"csv/18.포모스/{today}", exist_ok=True)
    logging.info("=" * 56)
    logging.info("포모스 크롤링 시작")
    logging.info("=" * 56)

    wd = setup_driver()

    try:
        for search in searchs:
            if stop_event.is_set(): break

            page_num = 1
            err_count = 0  # 연속 에러 카운트

            while True:
                if stop_event.is_set(): break

                list_url = f"https://www.fomos.kr/search/list?menu=talk&fword={search}&page={page_num}"

                try:
                    wd.set_page_load_timeout(15)
                    wd.get(list_url)
                    _close_extra_tabs(wd)

                    try:
                        WebDriverWait(wd, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "ul.webzine li"))
                        )
                        err_count = 0  # 성공하면 에러 카운트 초기화
                    except TimeoutException:
                        soup_check = BeautifulSoup(wd.page_source, "html.parser")
                        if not soup_check.select("ul.webzine li"):
                            logging.info(f"[목록] 결과 없음 → '{search}' 완료")
                            break
                        else:
                            # 요소는 있는데 타임아웃이면 재시작 한번 해봄
                            logging.warning("[목록] 로딩 지연. 재시작 후 재시도.")
                            wd = _restart_driver(wd)
                            continue

                    soup = BeautifulSoup(wd.page_source, "html.parser")
                    li_tags = soup.select("ul.webzine > li")
                    if not li_tags: break

                    for li in li_tags:
                        if stop_event.is_set(): break

                        a_tag = li.select_one("div.info p.tit a, p.tit a, p.para a")
                        if not a_tag: continue

                        href = a_tag.get("href") or ""
                        if not href.startswith("/"): continue

                        post_url = "https://www.fomos.kr" + href

                        status = fomos_crw(wd, post_url, search)

                        if status == "fatal":
                            wd = _restart_driver(wd)
                            continue

                except (WebDriverException, Exception) as e:
                    logging.error(f"[목록] 치명적 오류 발생: {e}")
                    wd = _restart_driver(wd)  # 에러나면 무조건 재시작
                    err_count += 1
                    if err_count > 3:  # 같은 페이지에서 3번 연속 터지면 다음 검색어로
                        logging.error("[시스템] 연속 오류로 해당 검색어 스킵")
                        break
                    continue

                page_num += 1

                if page_num % 10 == 0:
                    wd = _restart_driver(wd)

                if page_num >= 50:
                    break

    finally:
        try:
            wd.quit()
        except:
            pass

    if not stop_event.is_set():
        result_dir = "결과/포모스"
        os.makedirs(result_dir, exist_ok=True)
        try:
            dfs = []
            for search in searchs:
                df = result_csv_data(search, platform="포모스", subdir="18.포모스")
                if not df.empty:
                    dfs.append(df)

            if dfs:
                all_df = pd.concat(dfs, ignore_index=True)
                out_path = f"{result_dir}/포모스_raw data_{today}.csv"
                all_df.to_csv(out_path, encoding="utf-8-sig", index=False)
                logging.info(f"[결과] 병합 저장 완료: {out_path}")
        except Exception as e:
            logging.error(f"[결과] 병합 저장 실패: {e}")