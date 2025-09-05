import re
import os
import time
import logging
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from datetime import datetime

from src.etc.utils import setup_driver, save_to_csv, clean_title, result_csv_data

_today = datetime.now().strftime("%y%m%d")
os.makedirs('log', exist_ok=True)

logging.basicConfig(
    filename=f'log/세리에매니아_log_{_today}.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

BASE = "https://serieamania.com"
G2 = f"{BASE}/g2/bbs"

SFL = "wr_subject%7C%7Cwr_content"
SOP = "and"

# 기본값 (동적 탐색 실패 시 사용)
DEFAULT_BO_TABLES = [
    "calciotalk", "freetalk", "issue", "game", "sports", "multimedia"
]

def discover_all_bo_tables(wd) -> list:
    """사이트 내 모든 bo_table을 동적으로 발견"""
    seen = set()
    seed_urls = [f"{BASE}/", f"{G2}/board.php"]
    for u in seed_urls:
        try:
            wd.get(u)
            time.sleep(0.5)
            soup = BeautifulSoup(wd.page_source, "html.parser")
            for a in soup.find_all("a", href=True):
                h = a["href"]
                if "board.php?bo_table=" in h:
                    m = re.search(r"bo_table=([A-Za-z0-9_]+)", h)
                    if m:
                        seen.add(m.group(1))
        except Exception:
            continue
    return sorted(seen)


def _extract_post(wd, url: str, search: str, board_name: str) -> pd.DataFrame:
    writer_list, title_list, content_list, url_list = [], [], [], []
    search_plt_list, search_word_list, date_list, now_date = [], [], [], []

    try:
        logging.info(f"[세리에매니아] 접속: {url}")
        wd.get(url)
        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        time.sleep(0.5)
        soup = BeautifulSoup(wd.page_source, 'html.parser')

        raw_title = None
        h1 = soup.find('h1')
        if h1:
            raw_title = h1.get_text(strip=True)
        if not raw_title:
            t = soup.find(id='bo_v_title')
            if t:
                raw_title = t.get_text(strip=True)
        title = clean_title(raw_title) if raw_title else ''
        title_list.append(title)

        writer = ''
        for sel in ['.sv_member', '.member', '.profile a', '.wr_name', '.sv_member a']:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                writer = el.get_text(strip=True)
                break
        if not writer:
            texts = soup.get_text('\n', strip=True).split('\n')
            for i, line in enumerate(texts[:10]):
                if 'Updated at' in line and i >= 1:
                    candidate = texts[i-1].strip()
                    candidate = re.sub(r'[^\w\s\.\-가-힣]', '', candidate)
                    if 1 <= len(candidate) <= 30:
                        writer = candidate
                    break
        writer_list.append(writer)

        # ✅ 본문만 추출
        content_div = (
            soup.find('div', id='resContents') or  # 게시물 본문 영역
            soup.find(id='bo_v_con') or
            soup.find('div', class_='view-content') or
            soup.find('article') or
            soup.find('section')
        )
        if content_div:
            for tag in content_div.find_all(['script', 'style']):
                tag.decompose()
            post_content = content_div.get_text(" ", strip=True)
        else:
            post_content = ''

        # ✅ 누락된 append (없으면 DataFrame 생성 시 길이 불일치)
        content_list.append(post_content)

        # 키워드 재검증(제목+본문) — 검색엔진의 느슨한 매칭 방지
        kw = str(search or "").strip()
        if kw:
            tokens = [t.strip().lower() for t in re.split(r'[|,;/]+', kw) if t.strip()]
            hay = f"{title} {post_content}".lower()
            if tokens and not any(tok in hay for tok in tokens):
                # 키워드 미포함 글은 스킵
                return pd.DataFrame()

        text_all = soup.get_text("\n", strip=True)
        dt = None
        m = re.search(r'Updated at\s*(\d{4}-\d{2}-\d{2})', text_all)
        if m:
            dt = m.group(1)
        else:
            m2 = re.search(r'(\d{4}[.-]\d{2}[.-]\d{2})', text_all)
            if m2:
                dt = m2.group(1).replace('.', '-')
        date_list.append(dt if dt else '')

        search_plt_list.append('웹페이지(세리에매니아)')
        search_word_list.append(search)
        url_list.append(url)
        now_date.append(datetime.now().strftime('%Y-%m-%d'))

        df = pd.DataFrame({
            "검색어": search_word_list,
            "플랫폼": search_plt_list,
            "게시물 URL": url_list,
            "게시물 제목": title_list,
            "게시물 내용": content_list,
            "게시물 등록일자": date_list,
            "계정명": writer_list,
            "수집시간": now_date,
        })
        return df

    except Exception as e:
        logging.error(f"[세리에매니아] 상세 추출 실패: {e}")
        return pd.DataFrame()


def serieamania_main_crw(searchs, start_date, end_date, stop_event):
    out_dir = f'csv/세리에매니아/{_today}'
    os.makedirs(out_dir, exist_ok=True)

    logging.info("========================================================")
    logging.info("                    세리에매니아 크롤링 시작")
    logging.info("========================================================")

    wd = setup_driver()
    wd_list = setup_driver()

    # 전체 bo_table 동적 탐색
    bo_tables = discover_all_bo_tables(wd_list)
    if not bo_tables:
        bo_tables = DEFAULT_BO_TABLES

    for search in searchs:
        if stop_event.is_set():
            print("🛑 크롤링 중단됨")
            break

        page = 1
        visited = set()

        while True:
            if stop_event.is_set():
                break
            try:
                hit_any = False
                for bo in bo_tables:
                    list_url = (
                        f"{G2}/board.php?bo_table={bo}"
                        f"&sfl={SFL}&sop={SOP}&stx={search}&page={page}"
                    )
                    logging.info(f"[세리에매니아] 목록: {list_url}")
                    wd_list.get(list_url)
                    WebDriverWait(wd_list, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
                    time.sleep(0.5)
                    soup = BeautifulSoup(wd_list.page_source, 'html.parser')

                    links = []
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if f"board.php?bo_table={bo}&wr_id=" in href:
                            if href.startswith('/'):
                                links.append(BASE + href)
                            elif href.startswith('http'):
                                links.append(href)
                            else:
                                links.append(f"{G2}/" + href)

                    links = [u.split('#')[0] for u in links]
                    links = list(dict.fromkeys(links))

                    for post_url in links:
                        if stop_event.is_set():
                            break
                        if post_url in visited:
                            continue
                        visited.add(post_url)

                        df_one = _extract_post(wd, post_url, search, bo)
                        if df_one.empty:
                            continue

                        try:
                            dstr = str(df_one.iloc[0]["게시물 등록일자"])[:10]
                            if not dstr or dstr == 'nan':
                                continue
                            d = datetime.strptime(dstr.replace('.', '-'), '%Y-%m-%d').date()
                        except Exception:
                            continue

                        if d > end_date:
                            hit_any = True
                        elif d < start_date:
                            continue
                        else:
                            hit_any = True
                            save_to_csv(df_one, f'{out_dir}/세리에매니아_{search}.csv')

                if hit_any:
                    page += 1
                else:
                    break

            except Exception as e:
                logging.error(f"[세리에매니아] 목록 파싱 실패: {e}")
                break

    wd.quit()
    wd_list.quit()

    if not stop_event.is_set():
        result_dir = '결과/세리에매니아'
        os.makedirs(result_dir, exist_ok=True)

        frames = []
        for search in searchs:
            try:
                frames.append(result_csv_data(search, platform='세리에매니아', subdir='세리에매니아'))
            except Exception as e:
                logging.error(f"[세리에매니아] 취합 스킵({search}): {e}")
        if frames:
            all_data = pd.concat(frames, ignore_index=True)
            all_data.to_csv(f'{result_dir}/세리에매니아_raw data_{_today}.csv', encoding='utf-8', index=False)
            print(all_data.count())
        else:
            logging.info("[세리에매니아] 취합할 데이터가 없습니다.")