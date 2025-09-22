import os
import re
import logging
import pandas as pd
from datetime import datetime
import undetected_chromedriver as uc

# (추가) 재시도/슬립/체크포인트용 import
import time
import random
import json
from threading import Lock
from selenium.common.exceptions import TimeoutException, WebDriverException

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
os.makedirs('log', exist_ok=True)

def setup_driver():
    logging.info("웹드라이버 시작")
    options = uc.ChromeOptions()
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    )
    options.add_argument(f"user-agent={user_agent}")
    options.page_load_strategy = 'eager'  # DOMContentLoaded 시점 반환
    options.add_argument('--disable-popup-blocking')
    options.add_argument("--disable-javascript")            # 필요 시 주석 처리
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options, enable_cdp_events=True, incognito=True)
    return driver


def result_csv_data(search, platform, subdir, base_path='csv'):
    file_path = os.path.join(base_path, subdir, today, f'{platform}_{search}.csv')
    if not os.path.isfile(file_path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
        return df
    except Exception as e:
        print(f"[오류] CSV 읽기 실패 ({file_path}): {e}")
        return pd.DataFrame()


# csv 저장(추가 시 header=False)
def save_to_csv(df, file_name):
    try:
        if os.path.isfile(file_name):
            df.to_csv(file_name, mode='a', header=False, index=False, encoding='utf-8')
        else:
            df.to_csv(file_name, index=False, encoding='utf-8')
        print(f"저장완료 : {file_name}")
    except Exception as e:
        print(f"파일 저장 오류: {e}")


def clean_title(title):
    # 제목 뒤 넘버링 제거
    title = re.sub(r'\d+$', '', title or '').strip()
    # 파일 확장자 제거 (.jpg, .mp4 등)
    title = re.sub(r'\.(jpg|png|gif|mp4|avi|mkv|webm|jpeg)$', '', title, flags=re.IGNORECASE).strip()
    # 초성 제거 (자음만 있는 경우)
    title = re.sub(r'^[ㄱ-ㅎㅏ-ㅣ]+$', '', title).strip()
    # 따옴표 제거
    title = title.replace('"', '').strip()
    return title


# ===========================
# 안정화용 유틸 (통합 추가)
# ===========================

def human_sleep(short_min=1.5, short_max=3.0, long_prob=0.1, long_min=6, long_max=10):
    """
    사람 같은 딜레이: 가끔 긴 휴식 섞기 (서버 부하/차단/로딩지연 완화)
    """
    if random.random() < long_prob:
        time.sleep(random.uniform(long_min, long_max))
    else:
        time.sleep(random.uniform(short_min, short_max))


def safe_get(driver, url, retries=3, base_sleep=2):
    """
    느린 페이지/일시 오류 대비 안전 접속.
    - set_page_load_timeout(15)
    - 실패 시 window.stop() 시도
    - 지수 백오프 재시도
    """
    for i in range(retries):
        try:
            driver.set_page_load_timeout(15)
            driver.get(url)
            return True
        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            logging.warning(f"[safe_get] Timeout: {url}")
        except WebDriverException as e:
            logging.warning(f"[safe_get] WebDriverException: {e}")
        time.sleep(base_sleep * (2 ** i) + random.uniform(0, 1))
    logging.error(f"[safe_get] FAILED after {retries} tries: {url}")
    return False


# 진행상황 체크포인트 (이어하기)
_PROGRESS_PATH = "progress.json"
_progress_lock = Lock()

def load_progress():
    if os.path.exists(_PROGRESS_PATH):
        try:
            with open(_PROGRESS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_progress(search, page):
    with _progress_lock:
        data = load_progress()
        data[str(search)] = int(page)
        with open(_PROGRESS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def last_done_page(search, default_page=1):
    data = load_progress()
    return int(data.get(str(search), default_page))
