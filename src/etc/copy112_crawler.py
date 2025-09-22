# -*- coding: utf-8 -*-
"""
copy112_crawler.py

- 로그인 → 신고내역 리스트 크롤링 → (옵션) 신고처리완료 상세 진입(심의결과/처리내용) → 엑셀 저장
- GUI(copy112_gui.py)에서 run_crawl()를 호출해 사용
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

import pandas as pd
import time
from datetime import datetime
from pathlib import Path

# 대상 URL
LIST_URL = "https://copy112.kcopa.or.kr/mypage/unlaw/mypageUnlawList.do"
LOGIN_URL = "https://copy112.kcopa.or.kr/member/loginForm.do"

# 처리현황 분류 그룹
STATUS_GROUPS = {
    "전체 현황": None,
    "신고 접수 전": {"신고접수전"},
    "신고 접수 중": {"채증 및 검증", "위원심의", "시정권고", "이행여부 확인"},
    "신고 접수 완료": {"신고처리완료"},
}


# ──────────────────────────────────────────────
# 공용 유틸
# ──────────────────────────────────────────────
def _wait_table_ready(driver, timeout=10):
    """리스트 테이블 로드/안정화 대기 (stale 예방)"""
    WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table.result-list tbody tr"))
    )
    time.sleep(0.3)


def _parse_row_date(row):
    """tr에서 신고일자를 date로 파싱 (실패시 None)"""
    try:
        tds = row.find_elements(By.TAG_NAME, "td")
        dt = pd.to_datetime(tds[7].text.strip(), errors="coerce")
        return None if pd.isna(dt) else dt.date()
    except Exception:
        return None


def _within_period(date_text, start_date, end_date):
    """신고일자가 [start_date, end_date] 안에 있는지"""
    if not (start_date or end_date):
        return True
    try:
        dt = pd.to_datetime(date_text, errors="coerce")
        if pd.isna(dt):
            return False
        d = dt.date()
        if start_date and d < start_date:
            return False
        if end_date and d > end_date:
            return False
        return True
    except Exception:
        return False


def _status_in_group(status_text, group_name):
    """처리현황이 선택 그룹 조건에 부합하는지"""
    group = STATUS_GROUPS.get(group_name, None)
    if group is None:
        return True
    return status_text in group


def _classify_page_dates(driver, start_date, end_date):
    """
    페이지 내 날짜 분포를 스캔해 3가지 플래그 반환:
    (종료일 이후 있음?, 기간 내 있음?, 시작일 이전 있음?)
    """
    has_newer = False
    has_in_range = False
    has_older = False
    if not (start_date or end_date):
        return (False, True, False)  # 기간 제한이 없으면 '기간 내'로 취급

    rows = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")
    for r in rows:
        d = _parse_row_date(r)
        if not d:
            continue
        if end_date and d > end_date:
            has_newer = True
        if (not start_date or d >= start_date) and (not end_date or d <= end_date):
            has_in_range = True
        if start_date and d < start_date:
            has_older = True
    return has_newer, has_in_range, has_older


# ──────────────────────────────────────────────
# 페이징
# ──────────────────────────────────────────────
def _goto_next_page_by_one(driver, current_page_num, timeout=8):
    """
    페이지네이션을 '무조건 1페이지씩'만 전진.
    1) a.current의 다음 형제 숫자 클릭
    2) 없으면 블록 '다음(>)' → 새 블록에서 숫자 클릭
    3) 이동 후 a.current/테이블 안정화 대기
    """
    next_num = current_page_num + 1

    # 1) 현재 블록 내에서 다음 숫자
    try:
        cur = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.current"))
        )
        sibling_next = cur.find_element(
            By.XPATH,
            "following-sibling::a[normalize-space(text())!='' and not(contains(@class,'page'))][1]"
        )
        if sibling_next and sibling_next.text.strip().isdigit():
            driver.execute_script("arguments[0].click();", sibling_next)
            WebDriverWait(driver, timeout).until(
                lambda d: d.find_element(By.CSS_SELECTOR, "a.current").text.strip() == str(next_num)
            )
            _wait_table_ready(driver)
            return True
    except Exception:
        pass

    # 2) 블록 경계: '다음(>)' → 새 블록에서 숫자
    try:
        nxt = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a.page.next, a.next"))
        )
        driver.execute_script("arguments[0].click();", nxt)
        nums = WebDriverWait(driver, timeout).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//a[normalize-space(text())!='' and not(contains(@class,'page')) and number(normalize-space(text()))=number(normalize-space(text()))]")
            )
        )
        target = None
        for a in nums:
            if a.text.strip() == str(next_num):
                target = a
                break
        if target is None and nums:
            target = sorted(nums, key=lambda e: int(e.text.strip()))[0]

        if target:
            driver.execute_script("arguments[0].click();", target)
            WebDriverWait(driver, timeout).until(
                lambda d: d.find_element(By.CSS_SELECTOR, "a.current").text.strip().isdigit()
            )
            _wait_table_ready(driver)
            return True
    except Exception:
        pass

    # 3) 이동 실패 → 마지막 페이지로 간주
    try:
        cur_after = int(driver.find_element(By.CSS_SELECTOR, "a.current").text.strip())
    except Exception:
        cur_after = current_page_num
    return cur_after != current_page_num


# ──────────────────────────────────────────────
# 리스트/상세 파싱
# ──────────────────────────────────────────────
def _open_detail_from_row(driver, row_webelem):
    """행(row)에서 상세 페이지 진입(접수번호 링크 → tr 클릭 순)"""
    try:
        a = row_webelem.find_element(By.CSS_SELECTOR, "td:nth-child(2) a")
        driver.execute_script("arguments[0].click();", a)
        return True
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();", row_webelem)
        return True
    except Exception:
        return False


def _scrape_detail(driver):
    """상세 페이지에서 심의결과 / 처리내용 추출(실패 무시)"""
    time.sleep(0.5)
    review_result, process_text = "", ""
    try:
        td = driver.find_element(By.XPATH, "//th[contains(.,'심의결과')]/following-sibling::td[1]")
        review_result = td.text.strip()
    except Exception:
        pass
    try:
        ta = driver.find_element(By.CSS_SELECTOR, "textarea.PROCESS_CN")
        process_text = (ta.get_attribute("value") or ta.text or "").strip()
    except Exception:
        pass
    return review_result, process_text


def _extract_row_dict(row):
    """리스트 페이지의 tr → dict 변환"""
    tds = row.find_elements(By.TAG_NAME, "td")
    d = {
        "순번": tds[0].text.strip(),
        "접수번호": tds[1].text.strip(),
        "신고유형": tds[2].text.strip(),
        "사이트링크": "",
        "저작물명": tds[4].text.strip(),
        "서버위치": tds[5].text.strip(),
        "처리현황": tds[6].text.strip(),
        "신고일자": tds[7].text.strip(),
        "심의결과": "",
        "처리내용": "",
    }
    # 사이트링크(툴팁 title 또는 a.subject의 title)
    try:
        a = tds[3].find_element(By.CSS_SELECTOR, "a.subject")
        d["사이트링크"] = (a.get_attribute("title") or "").strip()
    except Exception:
        try:
            d["사이트링크"] = (tds[3].get_attribute("title") or "").strip()
        except Exception:
            d["사이트링크"] = ""
    return d


# ──────────────────────────────────────────────
# 메인 엔트리
# ──────────────────────────────────────────────
def run_crawl(
    selected_accounts,
    start_date=None, end_date=None,
    status_group="전체 현황",
    output_dir=".",
    detailed_for_done=True,
    log_callback=None,
    stop_event=None, pause_event=None
):
    """
    선택된 계정들에 대해:
      1) 로그인
      2) 신고내역 리스트 페이지를 기간/상태 필터로 수집
      3) (옵션) '신고처리완료'면 상세 진입하여 심의결과/처리내용 추가
      4) 모든 계정 종료 후 엑셀 저장
    """
    def log(msg):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass
        else:
            print(msg)

    # 상세 진입 허용: '신고 접수 완료' 선택시에만
    detail_allowed = (status_group == "신고 접수 완료") and bool(detailed_for_done)

    all_rows = []
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    seen_receipts = set()  # 접수번호 중복 방지

    # ───── 계정 단위 반복 ─────
    for acc in selected_accounts:
        if stop_event and stop_event.is_set():
            break

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

        collected_this_account = 0
        found_any_in_period = False  # 이 계정에서 '기간 내 데이터'를 한번이라도 찾았는지

        try:
            # 로그인
            driver.get(LOGIN_URL)
            time.sleep(2)
            driver.find_element(By.ID, "userid").send_keys(user_id)
            driver.find_element(By.ID, "password").send_keys(user_pw)
            driver.find_element(By.CLASS_NAME, "login-btn").click()
            time.sleep(2)

            # 리스트 진입
            driver.get(LIST_URL)
            _wait_table_ready(driver)

            # 페이지 루프
            zero_page_streak = 0
            max_zero_streak = 5  # 연속 5페이지가 필터 일치 0건이면 안전 종료

            while True:
                # 종료/일시정지 체크
                if stop_event and stop_event.is_set():
                    break
                if pause_event and pause_event.is_set():
                    while pause_event.is_set():
                        time.sleep(0.2)
                        if stop_event and stop_event.is_set():
                            break

                # 현재 페이지 번호
                try:
                    cur_el = WebDriverWait(driver, 6).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "a.current"))
                    )
                    current_page_num = int(cur_el.text.strip())
                except Exception:
                    log("현재 계정 접속 실패")
                    break

                # 페이지 날짜 분포
                newer_flag, inrange_flag, older_flag = _classify_page_dates(driver, start_date, end_date)

                # 날짜 판정 불명(회색지대) → 방어적으로 1페이지 전진(마지막이면 종료)
                if (start_date or end_date) and not (newer_flag or inrange_flag or older_flag):
                    moved = _goto_next_page_by_one(driver, current_page_num)
                    if not moved:
                        if not found_any_in_period:
                            log(f"{name or user_id} : 선택한 기간에 해당하는 데이터가 없어 종료 → 다음 계정으로 이동")
                        break
                    # 다음 루프로
                    continue

                # 종료일 이후만 있고(너무 최신), 기간 내가 없으면 1페이지 전진
                if (start_date or end_date) and newer_flag and not inrange_flag:
                    moved = _goto_next_page_by_one(driver, current_page_num)
                    if not moved:
                        if not found_any_in_period:
                            log(f"{name or user_id} : 선택한 기간에 해당하는 데이터가 없어 종료 → 다음 계정으로 이동")
                        break
                    continue

                # 행 처리
                prev_cnt = collected_this_account
                idx = 0
                while True:
                    _wait_table_ready(driver)
                    rows = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")
                    if idx >= len(rows):
                        break

                    row, d = None, None
                    for _ in range(3):  # stale 방지 재시도
                        try:
                            rows = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")
                            row = rows[idx]
                            d = _extract_row_dict(row)
                            break
                        except StaleElementReferenceException:
                            time.sleep(0.3)

                    if d is None:
                        idx += 1
                        continue

                    # 로컬 필터(기간/상태)
                    d_date_ok = _within_period(d.get("신고일자", ""), start_date, end_date)
                    d_status_ok = _status_in_group(d.get("처리현황", ""), status_group)

                    if d_date_ok and d_status_ok:
                        found_any_in_period = True

                        # 접수번호 중복 제거
                        receipt = d.get("접수번호", "").strip()
                        if receipt and receipt in seen_receipts:
                            idx += 1
                            continue
                        if receipt:
                            seen_receipts.add(receipt)

                        # 상세 진입(신고처리완료 & 해당 모드)
                        if detail_allowed and d.get("처리현황") == "신고처리완료":
                            try:
                                if _open_detail_from_row(driver, row):
                                    rr, pt = _scrape_detail(driver)
                                    d["심의결과"], d["처리내용"] = rr, pt
                                    driver.back()
                                    _wait_table_ready(driver)
                            except Exception:
                                pass

                        d["계정"], d["성명"] = user_id, name
                        all_rows.append(d)
                        collected_this_account += 1

                    idx += 1

                # 페이지 처리 결과 로그 + 연속 0건 종료장치
                page_added = collected_this_account - prev_cnt
                msg = f"{name or user_id} : {current_page_num}페이지 수집 완료, 누적 {collected_this_account}건"
                if page_added == 0:
                    msg += " (이 페이지 필터 일치 0건)"
                    zero_page_streak += 1
                else:
                    zero_page_streak = 0
                log(msg)

                if zero_page_streak >= max_zero_streak:
                    log(f"{name or user_id} : 연속 {max_zero_streak}페이지 필터 일치 0건 → 계정 수집 종료")
                    break

                # 시작일 이전 데이터가 하나라도 보이면 종료(요구 조건 유지)
                if (start_date or end_date) and older_flag:
                    log(f"{name or user_id} : 시작일 이전 데이터 발견 → 계정 수집 종료")
                    break

                # 다음 페이지로 1장 전진 + 페이지 번호 미변경 안전장치
                prev_num = current_page_num
                moved = _goto_next_page_by_one(driver, current_page_num)
                if not moved:
                    if not found_any_in_period:
                        log(f"{name or user_id} : 선택한 기간에 해당하는 데이터가 없어 종료 → 다음 계정으로 이동")
                    break
                try:
                    now_num = int(driver.find_element(By.CSS_SELECTOR, "a.current").text.strip())
                except Exception:
                    now_num = prev_num
                if now_num == prev_num:
                    log(f"{name or user_id} : 페이지 번호가 변하지 않음 → 계정 수집 종료")
                    break

        except Exception as e:
            log(f"{name or user_id} 계정 오류: {e}")
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            log(f"{name or user_id} 계정 크롤링 종료")

        # 계정별 0건 안내
        if collected_this_account == 0:
            log("해당 계정은 수집된 데이터가 0건입니다")

        if stop_event and stop_event.is_set():
            break

    # 전체 저장(부분 저장 없음)
    df = pd.DataFrame(all_rows, columns=[
        "계정", "성명", "순번", "접수번호", "신고유형", "사이트링크",
        "저작물명", "서버위치", "처리현황", "신고일자", "심의결과", "처리내용"
    ])

    final_path = None
    try:
        final_path = Path(output_dir) / f"신고내역_전체_{ts}.xlsx"
        df.to_excel(final_path, index=False)
        log(f"전체 저장 완료: {final_path.name} (총 {len(df)}건)")
    except Exception as e:
        log(f"최종 저장 실패: {e}")

    return df, (str(final_path) if final_path else None)
