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
        # 사이트명/제목 셀 내 <a class="subject" title="원문URL"> 구조일 수 있으므로 보강
        a = cols[3].select_one("a.subject")
        site_link = ""
        if a and a.get("title"):
            site_link = a.get("title").strip()
        else:
            # fallback: td 자체에 title 있는 경우
            site_link = cols[3].get("title", "").strip()

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
# 상세 페이지 진입/추출 유틸
# ──────────────────────────────
def open_detail_from_row(driver, row_webelem):
    """
    리스트의 해당 행에서 상세 페이지 진입.
    1순위: 접수번호(td:nth-child(2))에 링크가 있으면 그것 클릭
    2순위: 행 자체 클릭
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
    - 처리내용: textarea.PROCESS_CN (disabled일 수 있어 value로 읽기)
    """
    # 로딩 여유
    time.sleep(0.7)

    # 심의결과
    review_result = ""
    try:
        td = driver.find_element(By.XPATH, "//th[contains(.,'심의결과')]/following-sibling::td[1]")
        review_result = td.text.strip()
    except:
        review_result = ""

    # 처리내용
    process_text = ""
    try:
        ta = driver.find_element(By.CSS_SELECTOR, "textarea.PROCESS_CN")
        process_text = (ta.get_attribute("value") or ta.text or "").strip()
    except:
        process_text = ""

    return review_result, process_text

# ──────────────────────────────
# 계정 정보 불러오기 (엑셀: 비번 → 비밀번호 정규화)
# ──────────────────────────────
accounts_df = pd.read_excel("../copy112_계정.xlsx")
accounts_df = accounts_df.rename(columns={"비번": "비밀번호"})

all_data = []

# ──────────────────────────────
# 계정별 반복 ('신고처리완료'건 상세조회)
# ──────────────────────────────
for _, row in accounts_df.iterrows():
    USER_ID = str(row["아이디"])
    USER_PW = str(row["비밀번호"])

    print(f"\n계정 로그인 시작: {USER_ID}")

    options = Options()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        # 로그인
        driver.get("https://copy112.kcopa.or.kr/member/loginForm.do")
        time.sleep(2)
        driver.find_element(By.ID, "userid").send_keys(USER_ID)
        driver.find_element(By.ID, "password").send_keys(USER_PW)
        driver.find_element(By.CLASS_NAME, "login-btn").click()
        time.sleep(3)

        # 신고내역 페이지 이동
        driver.get("https://copy112.kcopa.or.kr/mypage/unlaw/mypageUnlawList.do")
        time.sleep(2)

        visited_pages = set()

        while True:
            # 현재 페이지 번호 파악
            try:
                cur_el = driver.find_element(By.CSS_SELECTOR, "a.current")
                current_page_num = int(cur_el.text.strip())
            except:
                print("현재 페이지 파악 실패")
                break

            # 현재 페이지 HTML 파싱
            html = driver.page_source
            parsed_rows = parse_table(html)

            # 상세 진입을 위해 Selenium의 tr 요소 준비
            tr_elems = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")

            # 각 행 처리(기존 누적 + 완료건 상세조회)
            for i, d in enumerate(parsed_rows):
                d["계정"] = USER_ID
                d["심의결과"] = ""
                d["처리내용"] = ""

                if d.get("처리현황") == "신고처리완료":
                    # 상세 페이지 진입
                    ok = open_detail_from_row(driver, tr_elems[i])
                    if ok:
                        rr, pt = scrape_detail(driver)
                        d["심의결과"] = rr
                        d["처리내용"] = pt
                        # 리스트로 복귀
                        driver.back()
                        time.sleep(1.0)
                        # 복귀 후 tr_elems가 무효화되므로 다시 잡아줌
                        tr_elems = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")

                all_data.append(d)

            print(f"{USER_ID} - {current_page_num}페이지 수집 완료, 누적: {len(all_data)}건")
            visited_pages.add(current_page_num)

            # 페이지 순회
            try:
                pgnums = driver.find_elements(By.CSS_SELECTOR, "a.pgnum")
                page_nums = [int(x.text.strip()) for x in pgnums if x.text.strip().isdigit()]
            except:
                page_nums = []

            for pn in page_nums:
                if pn in visited_pages:
                    continue
                try:
                    btn = driver.find_element(By.LINK_TEXT, str(pn))
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1.2)

                    cur_el = driver.find_element(By.CSS_SELECTOR, "a.current")
                    current_page_num = int(cur_el.text.strip())

                    html = driver.page_source
                    parsed_rows = parse_table(html)
                    tr_elems = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")

                    for i, d in enumerate(parsed_rows):
                        d["계정"] = USER_ID
                        d["심의결과"] = ""
                        d["처리내용"] = ""

                        if d.get("처리현황") == "신고처리완료":
                            ok = open_detail_from_row(driver, tr_elems[i])
                            if ok:
                                rr, pt = scrape_detail(driver)
                                d["심의결과"] = rr
                                d["처리내용"] = pt
                                driver.back()
                                time.sleep(1.0)
                                tr_elems = driver.find_elements(By.CSS_SELECTOR, "table.result-list tbody tr")

                        all_data.append(d)

                    print(f"{USER_ID} - {current_page_num}페이지 수집 완료, 누적: {len(all_data)}건")
                    visited_pages.add(current_page_num)

                except Exception as e:
                    print(f"{pn}페이지 이동 실패: {e}")
                    continue

            # Next 버튼 처리
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, "a.page.next")
                prev_num = current_page_num
                driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(1.2)
                new_num_el = driver.find_element(By.CSS_SELECTOR, "a.current")
                new_num = int(new_num_el.text.strip())
                if new_num == prev_num:
                    print(f"{USER_ID} - 마지막 페이지 도달. 종료.")
                    break
            except:
                print(f"{USER_ID} - 다음 버튼 없음. 종료.")
                break

    finally:
        driver.quit()

# ──────────────────────────────
# 저장('신고처리완료'건 상세 내용 포함)
# ──────────────────────────────
df = pd.DataFrame(all_data, columns=[
    "계정","순번","접수번호","신고유형","사이트링크","저작물명","서버위치","처리현황","신고일자",
    "심의결과","처리내용"
])
outfile = f"신고내역_전체_{datetime.now().strftime('%Y%m%d')}.xlsx"
df.to_excel(outfile, index=False)
print(f"\n모든 계정 수집 완료. 저장 파일: {outfile}  (총 {len(df)}건)")
