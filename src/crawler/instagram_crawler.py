"""
Instagram 크롤러 (Google 검색 기반)
- 쿼리: site:instagram.com "키워드" after:YYYY-MM-DD before:YYYY-MM-DD
- 기본 쿼리 + RAW_KEYWORDS OR 블록 확장 쿼리(2패스)
- 인스타 '게시물' URL만 수집 (정규식/리다이렉트 파라미터 기반)
- 제목+스니펫에 RAW_KEYWORDS가 걸린 경우에만 저장
- 어떤 키워드로 매칭됐는지 '키워드' 컬럼으로 기록(여러 개면 행 분리)

※ 업데이트: instagram_main_crw() 인자를 생략해도 동작하도록 기본값(최근 30일, RAW_KEYWORDS를 검색어로 사용, stop_event 무시)을 제공합니다.
"""

import os
import re
import csv
import time
import random
import urllib.parse
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple
from urllib.parse import urlparse, parse_qs, unquote

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# ======================== 출력 스키마/경로 =========================
HEADERS = ["검색어", "키워드", "게시물 URL", "게시물 제목"]
SITE_DIR = os.path.join("결과", "인스타그램")

# ======================== 패턴/키워드 =========================
# Instagram '게시물' URL 패턴:
#   - /p/SHORTCODE
#   - /reel/SHORTCODE
#   - /tv/SHORTCODE
#   - (옵션) /stories/USERNAME/ID
POST_PATTERNS = [
    r"^/p/[^/]+/?$",
    r"^/reel/[^/]+/?$",
    r"^/tv/[^/]+/?$",
    r"^/stories/[^/]+/\d+/?$",
]

# 제외해야 할 루트/프로필/탐색/계정 관리 등
EXCLUDE_PATH_PREFIX = (
    "/",
    "/explore",
    "/accounts",
    "/about",
    "/developer",
    "/legal",
    "/directory",
)

RAW_KEYWORDS = [
    "기사공유","기사읽기","기사정리","뉴스스크랩","만평",
    "신문사설","신문필사","간추린뉴스","신문공부","지면기사",
    "경제","뉴스","스크랩","시사","정치","정부",
]

# ======================== 유틸 =========================
def sleep_rand(a: float = 1.5, b: float = 3.5):
    time.sleep(random.uniform(a, b))

def _nospace(s: str) -> str:
    return (s or "").replace(" ", "").strip()

def extract_matches(text: str, keywords) -> List[str]:
    s = _nospace(text)
    seen = set()
    out = []
    for k in keywords:
        kk = _nospace(k)
        if kk and kk in s and kk not in seen:
            seen.add(kk)
            out.append(k)
    return out

def _strip_tracking_params(q: Dict[str, List[str]]) -> Dict[str, str]:
    # utm 계열, 리다이렉트 파라미터 등 제거
    drop_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                 "igshid", "refsrc", "mibextid", "_fb_noscript"}
    return {k: v[0] for k, v in q.items() if k not in drop_keys}

def clean_url(href: str) -> str:
    """utm류 파라미터 제거 + 말미 슬래시 정리."""
    try:
        u = urllib.parse.urlsplit(href)
        q = parse_qs(u.query)
        new_q = urllib.parse.urlencode(_strip_tracking_params(q))
        path = u.path.rstrip("/") if u.path != "/" else u.path
        return urllib.parse.urlunsplit((u.scheme, u.netloc, path, new_q, ""))
    except Exception:
        return href

def _unwrap_instagram_redirect(href: str) -> str:
    """
    l.instagram.com/?u=<encoded> 형태를 실제 대상 URL로 복호화.
    """
    try:
        pu = urlparse(href)
        if pu.netloc.endswith("l.instagram.com"):
            q = parse_qs(pu.query)
            if "u" in q and q["u"]:
                # 첫 번째 u 파라미터만 사용
                target = q["u"][0]
                return unquote(target)
    except Exception:
        pass
    return href

def _is_excluded_profile_or_root(path: str) -> bool:
    # 한 단 계 프로필 (/username) 은 제외, 루트(/) 도 제외
    # 제외 prefix 들도 필터
    if path == "/" or path.count("/") == 1:
        return True
    for p in EXCLUDE_PATH_PREFIX:
        if path.startswith(p) and path == p:
            return True
        if p != "/" and path.startswith(p + "/"):
            return True
    return False

def is_post_url(href: str) -> bool:
    """
    Instagram 게시물 URL 여부 판단.
    - l.instagram.com 리다이렉트(u=)는 원본으로 풀어서 검사
    - /p/, /reel/, /tv/, (옵션) /stories/... 만 허용
    - 프로필/루트/탐색/계정 등은 제외
    """
    href = _unwrap_instagram_redirect(href)
    parsed = urlparse(href)

    # only instagram.com
    netloc = parsed.netloc.lower()
    if not (netloc.endswith("instagram.com") or netloc.endswith("instagram.com:443")):
        return False

    path = parsed.path.rstrip("/") if parsed.path != "/" else parsed.path

    # 명백한 제외
    if _is_excluded_profile_or_root(path):
        return False

    # 게시물 패턴 매칭
    for pat in POST_PATTERNS:
        if re.search(pat, path):
            return True
    return False

# ======================== 쿼리 빌드 =========================
def build_query(keyword: str, start_d: date, end_d: date) -> str:
    # site:instagram.com "키워드" after:YYYY-MM-DD before:YYYY-MM-DD
    q = [f'site:instagram.com "{keyword}"',
         f"after:{start_d.isoformat()}",
         f"before:{end_d.isoformat()}"]
    return " ".join(q)

def build_augmented_queries(keyword: str, start_d: date, end_d: date) -> List[str]:
    base = build_query(keyword, start_d, end_d)
    # 공백 없이 OR 연결 → fb_crawler 스타일에 맞춰 문자열 구성
    or_block = " OR ".join(RAW_KEYWORDS)
    augmented = f"{base} ({or_block})"
    return [base, augmented]

def build_url(query: str, start: int, start_d: date, end_d: date) -> str:
    # 참고: filter=0 을 켜면 유사결과 확장 (옵션) → 필요 시 아래 주석 해제
    params = {
        "q": query,
        "start": str(start),
        "num": "10",
        "hl": "ko",
        "lr": "lang_ko",
        "tbs": f"cdr:1,cd_min:{start_d.strftime('%m/%d/%Y')},cd_max:{end_d.strftime('%m/%d/%Y')}",
        # "filter": "0",
    }
    return "https://www.google.com/search?" + urllib.parse.urlencode(params)

# ======================== 동의/캡챠 =========================
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

# ======================== 저장 =========================
def save_csv(path: str, rows: List[Dict[str, str]]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[SAVE] {len(rows)}건 저장 → {path}")

# ======================== 수집 =========================
def _extract_current_page(driver, keyword: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
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

            cleaned = clean_url(_unwrap_instagram_redirect(href))
            for m in matches:
                rows.append({
                    "검색어": keyword,
                    "키워드": m,
                    "게시물 URL": cleaned,
                    "게시물 제목": title,
                })
        except Exception:
            continue
    return rows

# ======================== 기본값 헬퍼 =========================
class _NoopEvent:
    """stop_event 이 None일 때 사용할 더미 이벤트."""
    def is_set(self) -> bool:
        return False

def _default_dates() -> Tuple[date, date]:
    end_d = date.today()
    start_d = end_d - timedelta(days=30)
    return start_d, end_d

def _default_searchs() -> List[str]:
    # 인자가 없으면 RAW_KEYWORDS 자체를 검색어로 사용 (최소 동작 보장)
    return list(RAW_KEYWORDS)

# ======================== 메인 (fb_main_crw와 동일한 흐름/톤) =========================
def instagram_main_crw(searchs: List[str] = None,
                       start_d: date = None,
                       end_d: date = None,
                       stop_event=None):
    """
    Google SERP 기반 Instagram 게시물 수집
    - 2패스(기본 쿼리 → OR 확장 쿼리)
    - 페이지 루프: max_pages (연속 0건 2회 시 조기 종료)
    - 중복 제거 키: (URL, 키워드)

    인자를 모두 생략해도 동작:
      * searchs  : RAW_KEYWORDS 사용
      * 기간     : 최근 30일 (start_d = today-30, end_d = today)
      * stop_event: 무시(_NoopEvent)
    """
    if searchs is None:
        searchs = _default_searchs()
        print(f"[DEFAULT] searchs 미지정 → RAW_KEYWORDS {len(searchs)}개 사용")
    if end_d is None or start_d is None:
        ds, de = _default_dates()
        start_d = start_d or ds
        end_d = end_d or de
        print(f"[DEFAULT] 기간 미지정 → 최근 30일 사용: {start_d} ~ {end_d}")
    if stop_event is None:
        stop_event = _NoopEvent()
        print("[DEFAULT] stop_event 미지정 → 무시(중지 신호 없음)")

    max_pages = 8
    profile_dir = os.getenv("GOOGLE_CHROME_PROFILE_DIR")
    USE_INCOGNITO = False  # True면 시크릿 모드, False면 일반 프로필 모드

    options = uc.ChromeOptions()
    options.add_argument("--lang=ko-KR")

    if USE_INCOGNITO:
        options.add_argument("--incognito")
        print("[MODE] 시크릿 모드로 실행됩니다.")
    else:
        if profile_dir:
            options.add_argument(f"--user-data-dir={profile_dir}")
            print(f"[MODE] 일반 모드 (프로필 경로 사용): {profile_dir}")

    driver = uc.Chrome(options=options)

    now = datetime.now().strftime("%y%m%d")
    all_rows: List[Dict[str, str]] = []
    print(f"[GOOGLE] 기간: {start_d} ~ {end_d} / 키워드 수: {len(searchs)}")

    try:
        for idx, keyword in enumerate(searchs, 1):
            if stop_event.is_set():
                break
            print(f"\n[GOOGLE] 검색어[{idx}/{len(searchs)}] = {keyword}")

            seen: set[Tuple[str, str]] = set()  # (URL, 키워드) 단위 중복 방지
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

            out_path = os.path.join(SITE_DIR, f"인스타그램_raw data_{keyword}_{now}.csv")
            save_csv(out_path, collected)

        final_path = os.path.join(SITE_DIR, f"인스타그램_raw data_{now}.csv")
        save_csv(final_path, all_rows)
        print(f"[GOOGLE] 합본 저장 완료: {len(all_rows)}건 → {final_path}")
        return final_path
    finally:
        driver.quit()
