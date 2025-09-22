import os, re, logging, pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Tuple, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

from src.etc.utils import (
    DriverManager,
    save_to_csv, clean_title, result_csv_data,
    human_sleep, last_done_page, save_progress
)

today = datetime.now().strftime("%y%m%d")
os.makedirs('log', exist_ok=True)
logging.basicConfig(
    filename=os.path.join('log', f'디시인사이드_log_{today}.txt'),
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.6,
                    status_forcelist=(429,500,502,503,504),
                    allowed_methods=frozenset(["GET"]))
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    s.mount("http://", adapter); s.mount("https://", adapter)
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"})
    return s

SESSION = make_session()

# -------------------------------
# 목록(검색 결과)
# -------------------------------
def fetch_list_urls(search: str, page: int, session: requests.Session = SESSION) -> List[Tuple[str, Optional[datetime.date]]]:
    url = f'https://search.dcinside.com/post/p/{page}/sort/latest/q/{search}'
    try:
        r = session.get(url, timeout=12)
        r.raise_for_status()
    except Exception as e:
        logging.warning(f"[fetch_list_urls] 요청 실패 p{page} {search}: {e}")
        return []
    soup = BeautifulSoup(r.text, 'lxml')
    ul = soup.find('ul', class_='sch_result_list')
    if not ul:
        logging.info(f"[fetch_list_urls] 결과 리스트 없음 p{page} {search}")
        return []
    out: List[Tuple[str, Optional[datetime.date]]] = []
    for li in ul.select('li'):
        date_el = li.select_one('span.date_time')
        a = li.select_one('a.tit_txt')
        if not (date_el and a and a.get('href')): continue
        try:
            date = datetime.strptime(date_el.get_text(strip=True), '%Y.%m.%d %H:%M').date()
        except Exception:
            date = None
        out.append((a['href'], date))
    return out

# -------------------------------
# 상세
# -------------------------------
def dc_crw_detail(dm: DriverManager, url: str, search: str) -> Optional[pd.DataFrame]:
    if not dm.get(url, retries=2, backoff=1.0):
        logging.warning(f"[detail] get 실패: {url}")
        return None
    try:
        WebDriverWait(dm.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".view_content_wrap"))
        )
    except TimeoutException:
        logging.warning(f"[detail] 본문 래퍼 미노출: {url}")
        return None

    soup = BeautifulSoup(dm.driver.page_source, 'lxml')
    ts = soup.select_one('h3.title.ub-word span.title_subject')
    raw_title = ts.get_text(strip=True) if ts else ""
    cleaned = clean_title(raw_title)

    content_div = soup.select_one('div.write_div')
    if not content_div:
        post_text = ""
    else:
        for og in content_div.select('a.og-wrap'): og.decompose()
        for a in content_div.select('a'):
            if (not a.find('img') and not a.find('span', class_='scrap_img')
                and not a.find('video') and not (a.find('iframe') and 'youtube.com' in a.decode_contents())):
                a.decompose()
        post_text = re.sub(r'http[s]?://\S+', '', content_div.get_text(separator='\n', strip=True))

    try:
        date_str = soup.select_one('span.gall_date').get_text(strip=True)
        post_date = datetime.strptime(date_str, '%Y.%m.%d %H:%M:%S').date()
    except Exception:
        post_date = None

    nick_el = soup.select_one('span.nickname')
    ip_el = soup.select_one('span.ip')
    writer = f"{nick_el.get_text(strip=True) if nick_el else ''}{ip_el.get_text(strip=True) if ip_el else ''}"

    return pd.DataFrame({
        "검색어": [search], "플랫폼": ['웹페이지(dcinside)'], "게시물 URL": [url],
        "게시물 제목": [cleaned], "게시물 내용": [post_text],
        "게시물 등록일자": [post_date], "계정명": [writer],
    })

# -------------------------------
# 메인
# -------------------------------
def dc_main_crw(searchs, start_date, end_date, stop_event):
    out_dir = f'csv/22.디시인사이드/{today}'
    os.makedirs(out_dir, exist_ok=True)
    logging.info("="*56); logging.info("      디시인사이드 크롤링 시작"); logging.info("="*56)

    dm = DriverManager()
    processed_keywords, err_streak = 0, 0

    pages_since_restart = 0
    empty_pages_streak = 0

    try:
        for search in searchs:
            if stop_event.is_set(): print("🛑 크롤링 중단됨"); break

            # (선택) 키워드 주기 재시작은 유지
            if processed_keywords > 0 and (processed_keywords % 20) == 0:
                dm.restart(); pages_since_restart = 0; empty_pages_streak = 0

            page_num = last_done_page(search, default_page=1)
            logging.info(f"[{search}] 시작 페이지: {page_num}")

            while True:
                if stop_event.is_set(): break
                if page_num >= 121: break

                pairs = fetch_list_urls(search, page_num, SESSION)

                # ✅ 결과 없음 → 연속 없음 카운터 증가
                if not pairs:
                    empty_pages_streak += 1
                    # 3페이지 연속 비어있으면 세션 재시작(파서/세션 꼬임 대비)
                    if empty_pages_streak >= 3:
                        logging.warning("[main] 3페이지 연속 결과 없음 → 드라이버 재시작")
                        dm.restart()
                        empty_pages_streak = 0
                    page_num += 1
                    save_progress(search, page_num)
                    human_sleep(0.2, 0.6)
                    pages_since_restart += 1
                    # ✅ 10페이지마다 강제 재시작
                    if pages_since_restart >= 10:
                        dm.restart(); pages_since_restart = 0
                    continue

                # 정상 결과면 streak 초기화
                empty_pages_streak = 0

                after_start_flag = False
                batch_saved = 0

                for post_url, post_date in pairs:
                    if stop_event.is_set(): break
                    if post_date and post_date > end_date: continue
                    if post_date and post_date < start_date:
                        after_start_flag = True; break

                    try:
                        one = dc_crw_detail(dm, post_url, search)
                        if one is not None:
                            save_to_csv(one, f'{out_dir}/디시인사이드_{search}.csv')
                            batch_saved += 1; err_streak = 0
                    except WebDriverException as e:
                        err_streak += 1
                        logging.error(f"[{search}] 상세 실패({err_streak}): {e}")
                        # ✅ 세션/DevTools 관련이면 즉시 교체
                        if any(sig in str(e).lower() for sig in (
                            "invalid session id","chrome not reachable","target closed",
                            "not connected to devtools","httpconnectionpool","read timed out",
                            "winerror 10061","devtoolsactiveport","net::err_connection_reset"
                        )):
                            dm.restart()
                        continue
                    except Exception as e:
                        # 기타 예외도 로그만 남기고 계속
                        logging.error(f"[{search}] 상세 기타 예외: {e}")
                        continue

                if after_start_flag: break

                page_num += 1
                save_progress(search, page_num)
                human_sleep(0.2, 0.6)

                pages_since_restart += 1
                if pages_since_restart >= 10:   # ✅ 10페이지마다 강제 재시작
                    dm.restart(); pages_since_restart = 0

            processed_keywords += 1

    finally:
        dm.quit()

    # 병합(선택)
    if not stop_event.is_set():
        result_dir = '결과/디시인사이드'
        os.makedirs(result_dir, exist_ok=True)
        frames = []
        for search in searchs:
            try:
                part = result_csv_data(search, platform='디시인사이드', subdir='22.디시인사이드')
                if part is not None and len(part) > 0: frames.append(part)
            except Exception as e:
                logging.error(f"[merge] {search} 병합 실패: {e}")
        if frames:
            all_data = pd.concat(frames, ignore_index=True)
            all_data.to_csv(f'{result_dir}/디시인사이드_raw data_{today}.csv', encoding='utf-8', index=False)
            logging.info(f"[merge] 저장 완료: {result_dir}/디시인사이드_raw data_{today}.csv")
        else:
            logging.info("[merge] 병합할 데이터가 없습니다.")
