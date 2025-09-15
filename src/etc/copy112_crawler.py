# -*- coding: utf-8 -*-
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime
from pathlib import Path

LIST_URL = "https://copy112.kcopa.or.kr/mypage/unlaw/mypageUnlawList.do"
LOGIN_URL = "https://copy112.kcopa.or.kr/member/loginForm.do"

# ──────────────────────────────
# 리스트 테이블 파싱
# ──────────────────────────────
def parse_table(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.result-list")
    data = []

    if not table:
        return data

    for row in table.select("tbody tr"):
        cols = row.select("td")
        if len(cols) < 8:
            continue
        # 제목/사이트링크 보강: <a class="subject" title="원문URL"> 가능성
        a = cols[3].select_one("a.subject")
        site_link = a.get("title", "").strip() if (a and a.get("title")) else cols[3].get("title", "").strip()

        data.append({
            "순번": cols[0].get_text(strip=True),
            "접수번호": cols[1].get_text(strip=True),
            "신고유형": cols[2].get_text(strip=True),
            "사이트링크": site_link,
            "저작물명": cols[4].get_text(strip=True),
            "서버위치": cols[5].get_text(strip=True),
            "처리현황": cols[6].get_text(strip=True),
            "신고일자": cols[7].get_text(strip=True),
        })
    return data

# ──────────────────────────────
# 상세 페이지 진입/추출
# ──────────────────────────────
def open_detail_from_row(driver, row_webelem):
    """
    1순위: 접수번호(td:nth-child(2)) 링크 클릭
    2순위: tr 자체 클릭
    """
    try:
        a = row_webelem.find_element(By.CSS_SELECTOR, "td:nth-child(2) a")
        driver.execute_script("arguments[0].click();", a)
        return True
    except:
        pass
    try:
        driver.execute_script("arguments[0].click();", row_webelem)
        return True
    except:
        return False

def scrape_detail(driver):
    """
    상세에서 심의결과/처리내용 읽기
    - 심의결과: //th[contains(.,'심의결과')]/following-sibling::td[1]
    - 처리내용: textarea.PROCESS_CN (disabled일 때 value로 읽기)
    """
    time.sleep(0.7)

    review_result, process_text = "", ""
    try:
        td = driver.find_element(By.XPATH, "//th[contains(.,'심의결과')]/following-sibling::td[1]")
        review_result = td.text.strip()
    except:
        pass
    try:
        ta = driver.find_element(By.CSS_SELECTOR, "textarea.PROCESS_CN")
        process_text = (ta.get_attribute("value") or ta.text or "").strip()
    except:
        pass

    return review_result, process_text

# ──────────────────────────────
# 상태 그룹 매핑 (GUI 연동)
# ──────────────────────────────
STATUS_GROUPS = {
    "전체 현황": None,  # 모든 상태 허용
    "신고 접수 전": {"신고접수전"},
    "신고 접수 중": {"채증 및 검증", "위원심의", "시정권고", "이행여부 확인"},
    "신고 접수 완료": {"신고처리완료"},
}

# ──────────────────────────────
# 날짜/상태 로컬 필터
# ──────────────────────────────
def _within_period(date_text, start_date, end_date):
    if not (start_date or end_date):
        return True
    try:
        dt = pd.to_datetime(date_text, errors="coerce")
        if pd.isna(dt):
            return False
        if start_date and dt.date() < start_date:
            return False
        if end_date and dt.date() > end_date:
            return False
        return True
    except:
        return False

def _status_in_group(status_text, group_name):
    group = STATUS_GROUPS.get(group_name, None)
    if group is None:
        return True
    return status_text in group

# ──────────────────────────────
# 핵심: run_crawl (GUI가 호출)
# ──────────────────────────────
def run_crawl(
    selected_accounts,                      # [{'성명':..., '아이디':..., '비밀번호':...}, ...]
    start_date=None, end_date=None,         # datetime.date 또는 None
    status_group="전체 현황",               # STATUS_GROUPS의 키
    excel_path="../copy112_계정.xlsx",      # 계정 엑셀 경로(참고 저장용)
    output_dir=".",                         # 저장 폴더
    detailed_for_done=True,                 # 신고처리완료 상세 진입
    log_callback=None,                      # 로그 함수(str)->None
    stop_event=None, pause_event=None       # threading.Event (옵션)
):
    """
    반환: (pd.DataFrame, 최종저장파일경로 또는 None)
    """
    def log(msg):
        if log_callback:
            try:
                log_callback(msg)
            except:
                pass
        else:
            print(msg)

    all_rows = []
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 계정 반복
    for acc in selected_accounts:
        if stop_event and stop_event.is_set():
            break
        # 중지(일시정지) 처리
        if pause_event:
            while pause_event.is_set():
                time.sleep(0.2)
                if stop_event and stop_event.is_set():
                    break

        name = str(acc.get("성명", "") or "")
        user_id = str(acc.get("아이디", "") or "")
        user_pw = str(acc.get("비밀번호", "") or acc.get("비번", "") or "")

        log(f"{name or user_id} 계정 크롤링 시작")

        options = Options()
        options.add_argument("--start-maximized")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        try:
            # 로그인
            driver.get(LOGIN_URL)
            time.sleep(2)
            driver.find_element(By.ID, "userid").send_keys(user_id)
            driver.find_element(By.ID, "password").send_keys(user_pw)
            driver.find_element(By.CLASS_NAME, "login-btn").click()
            time.sleep(2.5)

            # 신고내역 이동
            driver.get(LIST_URL)
            time.sleep(1.8)

            visited_pages = set()

            while True:
                if stop_event and stop_event.is_set():
                    break
                if pause_event:
                    while pause_event.is_set():
                        time.sleep(0.2)
                        if stop_event and stop_event.is_set():
                            break

                # 현재 페이지 번호
                try:
                    cur_el = driver.find_element(By.CSS_SELECTOR, "a.current")
                    current_page_num = int(cur_el.text.strip())
                except:
                    log("현재 페이지 파악 실패")
                    break

                html = driver.page_source
                parsed = parse_table(html)
                tr_elems = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")

                # 행 처리
                for i, d in enumerate(parsed):
                    if stop_event and stop_event.is_set():
                        break
                    if pause_event:
                        while pause_event.is_set():
                            time.sleep(0.2)
                            if stop_event and stop_event.is_set():
                                break

                    d["계정"] = user_id
                    d["성명"] = name
                    d["심의결과"] = ""
                    d["처리내용"] = ""

                    # 로컬 필터(기간/상태)
                    if not _within_period(d.get("신고일자", ""), start_date, end_date):
                        continue
                    if not _status_in_group(d.get("처리현황", ""), status_group):
                        continue

                    # 완료건 상세 진입
                    if detailed_for_done and d.get("처리현황") == "신고처리완료":
                        ok = open_detail_from_row(driver, tr_elems[i])
                        if ok:
                            rr, pt = scrape_detail(driver)
                            d["심의결과"] = rr
                            d["처리내용"] = pt
                            driver.back()
                            time.sleep(0.8)
                            tr_elems = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")

                    all_rows.append(d)

                visited_pages.add(current_page_num)
                log(f"{name or user_id} - {current_page_num}페이지 수집 완료, 누적 {len(all_rows)}건")

                # 페이지 번호들 이동
                try:
                    pgnums = driver.find_elements(By.CSS_SELECTOR, "a.pgnum")
                    page_nums = [int(x.text.strip()) for x in pgnums if x.text.strip().isdigit()]
                except:
                    page_nums = []

                progressed = False
                for pn in page_nums:
                    if pn in visited_pages:
                        continue
                    try:
                        btn = driver.find_element(By.LINK_TEXT, str(pn))
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1.0)
                        progressed = True
                        break
                    except Exception as e:
                        log(f"{pn}페이지 이동 실패: {e}")
                        continue

                if progressed:
                    continue

                # Next
                try:
                    next_btn = driver.find_element(By.CSS_SELECTOR, "a.page.next")
                    prev_num = current_page_num
                    driver.execute_script("arguments[0].click();", next_btn)
                    time.sleep(1.0)
                    new_num_el = driver.find_element(By.CSS_SELECTOR, "a.current")
                    new_num = int(new_num_el.text.strip())
                    if new_num == prev_num:
                        log(f"{name or user_id} - 마지막 페이지.")
                        break
                except:
                    log(f"{name or user_id} - 다음 버튼 없음.")
                    break

            # 계정 단위 부분 저장(안전)
            df_acc = pd.DataFrame(all_rows)
            acc_safe = (name or user_id or "account").replace("/", "_")
            part_path = output_dir / f"신고내역_부분저장_{acc_safe}_{ts}.xlsx"
            df_acc.to_excel(part_path, index=False)
            log(f"{name or user_id} 계정 저장 완료: {part_path.name}")

        except Exception as e:
            log(f"{name or user_id} 계정 오류: {e}")
        finally:
            driver.quit()
            log(f"{name or user_id} 계정 크롤링 종료")

        if stop_event and stop_event.is_set():
            break

    # 최종 저장
    df = pd.DataFrame(all_rows, columns=[
        "계정","성명","순번","접수번호","신고유형","사이트링크","저작물명","서버위치","처리현황","신고일자",
        "심의결과","처리내용"
    ])
    final_path = None
    try:
        final_path = output_dir / f"신고내역_전체_{ts}.xlsx"
        df.to_excel(final_path, index=False)
        log(f"전체 저장 완료: {final_path.name} (총 {len(df)}건)")
    except Exception as e:
        log(f"최종 저장 실패: {e}")

    return df, (str(final_path) if final_path else None)
