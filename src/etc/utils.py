import os
import re
import logging
import pandas as pd
from datetime import datetime
import undetected_chromedriver as uc

# 재시도/슬립/체크포인트용 import
import time
import random
import json
from threading import Lock
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
    # options.add_argument("--disable-javascript")            # 필요 시 주석 처리 (성능 유지하되 기능보장)
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options, enable_cdp_events=True, incognito=True)
    driver.set_page_load_timeout(20)
    driver.set_script_timeout(20)

    # CDP로 리소스 차단 (이미지/폰트/미디어/애널리틱스)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
            "*.png","*.jpg","*.jpeg","*.gif","*.webp","*.svg",
            "*.woff","*.woff2","*.ttf","*.otf",
            "*.mp4","*.webm","*.avi","*.mov",
            "*googletagmanager.com/*","*google-analytics.com/*","*doubleclick.net/*"
        ]})
        driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": False})
    except Exception:
        pass

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
        os.makedirs(os.path.dirname(file_name), exist_ok=True)
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

def human_sleep(short_min=0.2, short_max=0.6, long_prob=0.0, long_min=6, long_max=10):
    """
    페이지 단위로만 소량 지터(기본). 필요 시 long_prob 조정.
    """
    if random.random() < long_prob:
        time.sleep(random.uniform(long_min, long_max))
    else:
        time.sleep(random.uniform(short_min, short_max))

def _accept_alert_if_present(driver, timeout=1.5):
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        driver.switch_to.alert.accept()
        return True
    except Exception:
        return False


def safe_get(driver, url, retries=3, base_sleep=1.2):
    """
    느린 페이지/일시 오류 대비 안전 접속.
    - set_page_load_timeout(20)
    - 실패 시 window.stop() 시도
    - 알럿 자동 수습
    - 지수 백오프 재시도
    """
    for i in range(retries):
        try:
            driver.get(url)
            # 빠른 알럿 처리
            _accept_alert_if_present(driver, timeout=0.8)
            return True
        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            logging.warning(f"[safe_get] Timeout: {url}")
        except WebDriverException as e:
            # 알럿 수습 후 재시도
            if _accept_alert_if_present(driver, timeout=1.2):
                try:
                    driver.get(url)
                    return True
                except Exception:
                    pass
            logging.warning(f"[safe_get] WebDriverException: {e}")
        time.sleep(base_sleep * (2 ** i) + random.uniform(0, 0.8))

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
