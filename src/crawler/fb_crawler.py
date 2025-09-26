"""
Facebook 크롤러 (Google 검색 기반)
- 쿼리: site:facebook.com "키워드" after:YYYY-MM-DD before:YYYY-MM-DD
- 기본 쿼리 + RAW_KEYWORDS OR 블록 확장 쿼리(2패스)
- 페이스북 '게시물' URL만 수집 (정규식/파라미터 기반)
- 제목+스니펫에 RAW_KEYWORDS가 걸린 경우에만 저장
- 어떤 키워드로 매칭됐는지 '키워드' 컬럼으로 기록(여러 개면 행 분리)
"""

import os
import re
import csv
import time
import random
import urllib.parse
from datetime import datetime, date
from typing import List, Dict
from urllib.parse import urlparse, parse_qs

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# ======================== 출력 스키마 =========================
HEADERS = ["검색어", "키워드", "게시물 URL", "게시물 제목"]
SITE_DIR = os.path.join("결과", "페이스북")

# ======================== 패턴/키워드 =========================
POST_PATTERNS = [
    r"/posts/\d+",
    r"/posts/pfbid\w+",
    r"/permalink/\d+",
    r"/groups/\d+/posts/\d+",
    r"/photo\.php",
    r"/videos/\d+",
    r"story_fbid",
    r"fbid",
]

RAW_KEYWORDS = [
    "기사공유","기사읽기","기사정리","뉴스스크랩","만평",
    "신문사설","신문필사","간추린뉴스","신문공부","지면기사",
    "경제","뉴스","스크랩","시사","정치","정부",
]

# ======================== 유틸 =========================
def sleep_rand(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))

def _nospace(s: str) -> str:
    return (s or "").replace(" ", "").strip()

def extract_matches(text: str, keywords) -> List[str]:
    s = _nospace(text)
    # 중복 방지 위해 set 사용 후 원래 순서 보존
    seen = set()
    out = []
    for k in keywords:
        kk = _nospace(k)
        if kk and kk in s and kk not in seen:
            seen.add(kk)
            out.append(k)
    return out

def clean_url(href: str) -> str:
    try:
        u = urllib.parse.urlsplit(href)
        q = parse_qs(u.query)
        for k in list(q):
            if k.startswith("utm") or k in ("refsrc", "mibextid", "_fb_noscript"):
                q.pop(k, None)
        new_q = urllib.parse.urlencode({k: v[0] for k, v in q.items()})
        return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, new_q, ""))
    except Exception:
        return href

def is_post_url(href: str) -> bool:
    parsed = urlparse(href)
    if "facebook.com" not in parsed.netloc:
        return False
    path = parsed.path
    if any(re.search(p, path) for p in POST_PATTERNS):
        return True
    q = parse_qs(parsed.query)
    return any(k in q for k in ("story_fbid", "fbid"))

def build_query(keyword: str, start_d: date, end_d: date) -> str:
    q = [f'site:facebook.com "{keyword}"',
         f"after:{start_d.isoformat()}",
         f"before:{end_d.isoformat()}"]
    return " ".join(q)

def build_augmented_queries(keyword: str, start_d: date, end_d: date) -> List[str]:
    base = build_query(keyword, start_d, end_d)
    or_block = " OR ".join(RAW_KEYWORDS)           # (기사공유 OR 기사읽기 OR …)
    augmented = f"{base} ({or_block})"
    return [base, augmented]

def build_url(query: str, start: int, start_d: date, end_d: date) -> str:
    params = {
        "q": query,
        "start": str(start),
        "num": "10",
        "hl": "ko",
        "lr": "lang_ko",
        "tbs": f"cdr:1,cd_min:{start_d.strftime('%m/%d/%Y')},cd_max:{end_d.strftime('%m/%d/%Y')}"
    }
    return "https://www.google.com/search?" + urllib.parse.urlencode(params)

def wait_if_captcha(driver):
    if "sorry/index" in driver.current_url or "captcha" in driver.page_source.lower():
        print("[CAPTCHA] 감지됨 - 브라우저에서 해제 후 대기합니다.")
        while "sorry/index" in driver.current_url or "captcha" in driver.page_source.lower():
            time.sleep(3)
        print("[CAPTCHA] 해제됨 - 재개")

def click_consent(driver):
    if "consent.google.com" not in driver.current_url:
        return
    try:
        driver.find_element(By.XPATH, "//button[contains(text(),'동의')]").click()
        sleep_rand()
        print("[GOOGLE] 동의창 자동 클릭 완료")
    except Exception:
        print("[GOOGLE] 동의창 자동 클릭 실패 - 수동 클릭 요망")

def save_csv(path: str, rows: List[Dict[str, str]]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[SAVE] {len(rows)}건 저장 → {path}")

# ======================== 수집 =========================
def _extract_current_page(driver, keyword: str) -> List[Dict[str, str]]:
    rows = []
    blocks = driver.find_elements(By.CSS_SELECTOR, "div.g, div.MjjYud")
    for block in blocks:
        try:
            a = block.find_element(By.CSS_SELECTOR, "a")
            href = a.get_attribute("href")
            title = a.text.strip()
            snippet = block.text.strip()
            if not href or not is_post_url(href):
                continue

            # 제목+스니펫에서 RAW_KEYWORDS 매칭 → 키워드별로 행 분리
            matches = extract_matches(f"{title} {snippet}", RAW_KEYWORDS)
            if not matches:
                continue

            for m in matches:
                rows.append({
                    "검색어": keyword,
                    "키워드": m,
                    "게시물 URL": clean_url(href),
                    "게시물 제목": title,
                })
        except Exception:
            continue
    return rows

# ======================== 메인 =========================
def fb_main_crw(searchs, start_d: date, end_d: date, stop_event):
    max_pages = 8
    profile_dir = os.getenv("GOOGLE_CHROME_PROFILE_DIR")

    options = uc.ChromeOptions()
    if profile_dir:
        options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--lang=ko-KR")

    driver = uc.Chrome(options=options)

    now = datetime.now().strftime("%y%m%d")
    all_rows: List[Dict[str, str]] = []
    print(f"[GOOGLE] 기간: {start_d} ~ {end_d} / 키워드 수: {len(searchs)}")

    try:
        for idx, keyword in enumerate(searchs, 1):
            if stop_event.is_set():
                break
            print(f"\n[GOOGLE] 검색어[{idx}/{len(searchs)}] = {keyword}")

            seen = set()  # (URL, 키워드) 단위 중복 방지
            collected: List[Dict[str, str]] = []

            queries = build_augmented_queries(keyword, start_d, end_d)
            for pass_no, query in enumerate(queries, 1):
                print(f"  - Pass {pass_no}: {query}")
                no_new_pages = 0

                for page in range(max_pages):
                    if stop_event.is_set():
                        break
                    url = build_url(query, page * 10, start_d, end_d)
                    print(f"    · p{page+1} 요청: {url}")
                    try:
                        driver.get(url)
                    except Exception as e:
                        print(f"      ! 페이지 로드 실패: {e}")
                        no_new_pages += 1
                        if no_new_pages >= 2:
                            break
                        continue

                    wait_if_captcha(driver)
                    time.sleep(1.5)
                    click_consent(driver)

                    rows = _extract_current_page(driver, keyword)

                    new_cnt = 0
                    for r in rows:
                        key = (r["게시물 URL"], r["키워드"])
                        if key not in seen:
                            seen.add(key)
                            collected.append(r)
                            all_rows.append(r)
                            new_cnt += 1

                    print(f"      - p{page+1} 신규: {new_cnt}건 (누적 {len(collected)})")
                    if new_cnt == 0:
                        no_new_pages += 1
                    else:
                        no_new_pages = 0
                    if no_new_pages >= 2:
                        print("      - 신규 없음 2회 연속 → 다음 패스")
                        break
                    sleep_rand()

            out_path = os.path.join(SITE_DIR, f"페이스북_raw data_{keyword}_{now}.csv")
            save_csv(out_path, collected)

        final_path = os.path.join(SITE_DIR, f"페이스북_raw data_{now}.csv")
        save_csv(final_path, all_rows)
        print(f"[GOOGLE] 합본 저장 완료: {len(all_rows)}건 → {final_path}")
        return final_path
    finally:
        driver.quit()
