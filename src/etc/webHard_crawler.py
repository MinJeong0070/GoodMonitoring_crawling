# webHard_crawler.py
# pip install selenium webdriver-manager pandas openpyxl

import re
import time
import random
from datetime import datetime
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

BASE = "https://www.applefile.com"
LOGIN_URL = f"{BASE}/"
BOARD_URL = f"{BASE}/contents/#tab=DOC&tab2=001"
DETAIL_URL_FMT = f"{BASE}/contents/view.html?idx={{post_id}}"

USER_ID = "gms1123"
USER_PW = "gms11234!!"

FILENAME = f"애플파일_도서 일반_{datetime.now().strftime('%Y%m%d')}.xlsx"
OUTPUT_PATH = Path.cwd() / FILENAME


def human_sleep(a=0.4, b=0.9):
    time.sleep(random.uniform(a, b))


def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,900")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options
    )
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
    )
    return driver


def wait_one_of(driver, selectors, timeout=12, clickable=False):
    end = time.time() + timeout
    last_err = None
    while time.time() < end:
        for sel in selectors:
            try:
                cond = EC.element_to_be_clickable if clickable else EC.presence_of_element_located
                el = WebDriverWait(driver, 2).until(cond((By.CSS_SELECTOR, sel)))
                return el, sel
            except Exception as e:
                last_err = e
        time.sleep(0.2)
    raise TimeoutException(str(last_err) if last_err else "not found")


def safe_dump(driver, tag="debug"):
    t = int(time.time())
    html_p = Path.cwd() / f"{tag}_{t}.html"
    png_p = Path.cwd() / f"{tag}_{t}.png"
    try:
        html_p.write_text(driver.page_source, encoding="utf-8", errors="ignore")
        driver.save_screenshot(str(png_p))
        print(f"[디버그] HTML 저장: {html_p}")
        print(f"[디버그] 스크린샷 저장: {png_p}")
    except Exception:
        pass


def login(driver: webdriver.Chrome):
    driver.get(LOGIN_URL)
    human_sleep(0.8, 1.4)

    try:
        uid_el, _ = wait_one_of(driver, ["#login_userid", "input[name='userid']"], timeout=15)
        pw_el, _  = wait_one_of(driver, ["#login_userpw", "input[name='userpw']"], timeout=10)
        btn_el, _ = wait_one_of(driver, ["#login_btn", "input#login_btn", "input[value='로그인']"], timeout=10, clickable=True)
    except TimeoutException:
        print("[오류] 로그인 폼 요소를 찾지 못했습니다.")
        safe_dump(driver, "login_not_found")
        raise

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", uid_el)
    human_sleep()
    uid_el.clear(); uid_el.send_keys(USER_ID); human_sleep()
    pw_el.clear();  pw_el.send_keys(USER_PW);  human_sleep()
    btn_el.click()
    human_sleep(1.0, 1.6)


def open_board(driver: webdriver.Chrome):
    driver.get(BOARD_URL)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.table_hoz tbody tr"))
        )
    except TimeoutException:
        print("[오류] 목록 테이블이 보이지 않습니다.")
        safe_dump(driver, "list_not_found")
        raise
    human_sleep()


# ---- URL/ID 파싱 강화 ----
ID_PATTERNS = [
    re.compile(r"view\.html\?idx=(\d+)"),        # 올바른 쿼리
    re.compile(r"view\.html\?id=(\d+)"),         # 혹시 섞여 있으면 대비
    re.compile(r"azim\(['\"]?(\d+)['\"]?\)"),    # onclick 케이스
    re.compile(r"[^\d](\d{6,})[^\d]"),           # 최후 보루
]


def extract_post_id_from_html(html: str) -> str | None:
    if not html:
        return None
    for pat in ID_PATTERNS:
        m = pat.search(html)
        if m:
            return m.group(1)
    return None


def build_url_from_row(row) -> str:
    """가능한 모든 경로로 글 ID/URL을 찾는다. 우선순위: a.onclick → a.href → row.innerHTML 스캔"""
    try:
        a_tag = row.find_element(By.CSS_SELECTOR, "td.title a")
    except Exception:
        return ""

    # 1) onclick에서 추출
    onclick_val = a_tag.get_attribute("onclick") or ""
    post_id = extract_post_id_from_html(onclick_val)
    if post_id:
        return DETAIL_URL_FMT.format(post_id=post_id)

    # 2) href 직접 사용 (있다면)
    href = a_tag.get_attribute("href") or ""
    if href and "view.html" in href:
        # href에 id/idx가 있으면 표준화
        m = re.search(r"(?:idx|id)=(\d+)", href)
        if m:
            return DETAIL_URL_FMT.format(post_id=m.group(1))
        return href

    # 3) 행 내부 HTML 전체에서 스캔
    inner_html = row.get_attribute("innerHTML") or ""
    post_id = extract_post_id_from_html(inner_html)
    if post_id:
        return DETAIL_URL_FMT.format(post_id=post_id)

    # 4) 실패 시 디버그 드롭
    try:
        rid = row.get_attribute("outerHTML")
        t = int(time.time())
        Path(f"row_debug_{t}.html").write_text(rid, encoding="utf-8", errors="ignore")
        print(f"[경고] URL 추출 실패 → row_debug_{t}.html 저장")
    except Exception:
        pass
    return ""


# ---- 용량 추출: 숫자 + 단위(K/M/G 또는 KB/MB/GB) 패턴만 선택 ----
SIZE_PAT = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:[KMG]|KB|MB|GB)\s*$", re.IGNORECASE)

def extract_size_from_row(row) -> str:
    """td.ta_r 중 '용량'만 골라내기 (예: 651.6K, 23.0M, 1.2G, 512MB 등)"""
    try:
        candidates = row.find_elements(By.CSS_SELECTOR, "td.ta_r")
    except Exception:
        return ""
    for td in candidates:
        txt = (td.text or "").strip()
        if SIZE_PAT.match(txt):
            # 통일을 원하면 대문자/소문자 정규화 가능
            return txt.upper().replace("KB","K").replace("MB","M").replace("GB","G")
    return ""


def scrape_first_page(driver: webdriver.Chrome):
    rows = driver.find_elements(By.CSS_SELECTOR, "table.table_hoz tbody tr")
    results = []
    for row in rows:
        try:
            # 광고/추천 배너 행 스킵
            if "auth_link(" in row.get_attribute("outerHTML"):
                continue

            # 제목
            title_td = row.find_element(By.CSS_SELECTOR, "td.title")
            title_text = title_td.text.strip()
            if not title_text:
                continue

            # URL
            url = build_url_from_row(row)

            # 등록자
            writer_td = row.find_element(By.CSS_SELECTOR, "td.ta_c.user")
            writer = writer_td.text.strip()

            # 용량
            size = extract_size_from_row(row)

            results.append({
                "게시글 제목": title_text,
                "게시글 url": url,
                "게시글 용량": size,
                "등록자": writer
            })
        except Exception:
            continue
    return results


def main():
    driver = create_driver()
    try:
        login(driver)
        open_board(driver)
        data = scrape_first_page(driver)
        if not data:
            print("[알림] 수집된 데이터가 없습니다.")
            return
        df = pd.DataFrame(data, columns=["게시글 제목", "게시글 url", "등록자", "게시글 용량"])
        df.to_excel(OUTPUT_PATH, index=False)
        print(f"[완료] 1페이지 수집 → {OUTPUT_PATH} 저장 ({len(df)}건)")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
