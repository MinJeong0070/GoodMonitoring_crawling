# -*- coding: utf-8 -*-
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

LIST_URL = "https://copy112.kcopa.or.kr/mypage/unlaw/mypageUnlawList.do"
LOGIN_URL = "https://copy112.kcopa.or.kr/member/loginForm.do"

STATUS_GROUPS = {
    "전체 현황": None,
    "신고 접수 전": {"신고접수전"},
    "신고 접수 중": {"채증 및 검증", "위원심의", "시정권고", "이행여부 확인"},
    "신고 접수 완료": {"신고처리완료"},
}


def _wait_table_ready(driver, timeout=10):
    WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table.result-list tbody tr"))
    )
    time.sleep(0.3)


def _parse_row_date(row):
    try:
        tds = row.find_elements(By.TAG_NAME, "td")
        dt = pd.to_datetime(tds[7].text.strip(), errors="coerce")
        return None if pd.isna(dt) else dt.date()
    except Exception:
        return None


def _within_period(date_text, start_date, end_date):
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
    group = STATUS_GROUPS.get(group_name, None)
    if group is None:
        return True
    return status_text in group


def _classify_page_dates(driver, start_date, end_date):
    """페이지 내 날짜를 스캔해 세 가지 플래그를 반환한다.
    returns: (has_newer_than_end, has_in_range, has_older_than_start)
    """
    has_newer = False
    has_in_range = False
    has_older = False
    if not (start_date or end_date):
        return (False, True, False)  # 기간 제한 없으면 '기간 내'로 취급

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


def _goto_next_page_by_one(driver, current_page_num, timeout=8):
    next_num = current_page_num + 1
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

    try:
        cur_after = int(driver.find_element(By.CSS_SELECTOR, "a.current").text.strip())
    except Exception:
        cur_after = current_page_num
    return cur_after != current_page_num


def _open_detail_from_row(driver, row_webelem):
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
    try:
        a = tds[3].find_element(By.CSS_SELECTOR, "a.subject")
        d["사이트링크"] = (a.get_attribute("title") or "").strip()
    except Exception:
        try:
            d["사이트링크"] = (tds[3].get_attribute("title") or "").strip()
        except Exception:
            d["사이트링크"] = ""
    return d


def run_crawl(
    selected_accounts,
    start_date=None, end_date=None,
    status_group="전체 현황",
    output_dir=".",
    detailed_for_done=True,
    log_callback=None,
    stop_event=None, pause_event=None
):
    def log(msg):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass
        else:
            print(msg)

    detail_allowed = (status_group == "신고 접수 완료") and bool(detailed_for_done)

    all_rows = []
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    seen_receipts = set()

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
        found_any_in_period = False

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

            while True:
                if stop_event and stop_event.is_set():
                    break
                if pause_event and pause_event.is_set():
                    while pause_event.is_set():
                        time.sleep(0.2)
                        if stop_event and stop_event.is_set():
                            break

                try:
                    cur_el = WebDriverWait(driver, 6).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "a.current"))
                    )
                    current_page_num = int(cur_el.text.strip())
                except Exception:
                    log("현재 계정 접속 실패")
                    break

                # 페이지 날짜 분포 분류
                newer_flag, inrange_flag, older_flag = _classify_page_dates(driver, start_date, end_date)

                # 종료일보다 최신만 있고 기간 내가 없으면 1페이지 전진
                if (start_date or end_date) and newer_flag and not inrange_flag:
                    if not _goto_next_page_by_one(driver, current_page_num):
                        if not found_any_in_period:
                            log(f"{name or user_id} : 선택한 기간에 해당하는 데이터가 없어 종료 → 다음 계정으로 이동")
                        break
                    continue

                # 이 페이지에서 기간 내 데이터가 있다면 그 행들만 파싱
                prev_cnt = collected_this_account
                idx = 0
                while True:
                    _wait_table_ready(driver)
                    rows = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")
                    if idx >= len(rows):
                        break

                    row, d = None, None
                    for _ in range(3):
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

                    d_date_ok = _within_period(d.get("신고일자", ""), start_date, end_date)
                    d_status_ok = _status_in_group(d.get("처리현황", ""), status_group)

                    if d_date_ok and d_status_ok:
                        found_any_in_period = True

                        receipt = d.get("접수번호", "").strip()
                        if receipt and receipt in seen_receipts:
                            idx += 1
                            continue
                        if receipt:
                            seen_receipts.add(receipt)

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

                page_added = collected_this_account - prev_cnt
                log_msg = f"{name or user_id} : {current_page_num}페이지 수집 완료, 누적 {collected_this_account}건"
                if page_added == 0:
                    log_msg += " (이 페이지 필터 일치 0건)"
                log(log_msg)

                # 시작일보다 이전이 하나라도 보이면 즉시 계정 종료(요구사항)
                if (start_date or end_date) and older_flag:
                    log(f"{name or user_id} : 시작일 이전 데이터 발견 → 계정 수집 종료")
                    break

                # 다음 페이지로 1장 전진
                if not _goto_next_page_by_one(driver, current_page_num):
                    if not found_any_in_period:
                        log(f"{name or user_id} : 선택한 기간에 해당하는 데이터가 없어 종료 → 다음 계정으로 이동")
                    break

        except Exception as e:
            log(f"{name or user_id} 계정 오류: {e}")
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            log(f"{name or user_id} 계정 크롤링 종료")

        if (collected_this_account == 0):
            log("해당 계정은 수집된 데이터가 0건입니다")

        if stop_event and stop_event.is_set():
            break

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


if __name__ == "__main__":
    root = tk.Tk()
    app = CrawlerGUI(root)
    root.mainloop()
