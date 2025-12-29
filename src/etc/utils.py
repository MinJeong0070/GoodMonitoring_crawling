import os
import re
import logging
import pandas as pd
from datetime import datetime
import undetected_chromedriver as uc

import time
import random
import json
from threading import Lock
from selenium.common.exceptions import TimeoutException, WebDriverException, UnexpectedAlertPresentException
from selenium.webdriver.common.by import By

today = datetime.now().strftime("%y%m%d")
os.makedirs('log', exist_ok=True)

def _maybe_accept_alert(driver) -> bool:
    try:
        a = driver.switch_to.alert
        txt = a.text
        a.accept()
        logging.info(f"[alert] accepted: {txt[:40]}")
        return True
    except Exception:
        return False

def setup_driver(headless: bool = False,
                 user_agent: str | None = None,
                 user_data_dir: str | None = None,
                 window_size: str = "1550,1000") -> uc.Chrome:
    """
    HTTPConnectionPool 타임아웃 방지를 위한 최적 안정 세팅
    """

    logging.info("🔧 Chrome 드라이버 초기화 시작")

    # Chrome 옵션
    options = uc.ChromeOptions()

    # 사용자 에이전트
    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )
    options.add_argument(f"--user-agent={ua}")

    options.add_argument(f"--window-size={window_size}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-infobars")
    options.add_argument("--log-level=3")
    options.add_argument("--silent")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--incognito")

    if headless:
        options.add_argument("--headless=new")

    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.cookies": 2,
        "profile.managed_default_content_settings.javascript": 1,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    })

    # 페이지 로딩 전략: DOMContentLoaded까지만
    options.page_load_strategy = "eager"

    # ✅ 핵심: 내부 localhost 통신 지연 방지를 위해 subprocess 완전 비활성
    #    (이 설정이 있어야 HTTPConnectionPool 오류 대부분 사라집니다)
    try:
        driver = uc.Chrome(
            options=options,
            enable_cdp_events=False,
            use_subprocess=True,  # ⚠️ False에서 True로 변경 테스트 (v143 버그 회피 시도)
            headless=headless,
            version_main=143  # ⚠️ 강제로 메이저 버전 지정 (설치된 크롬이 143이므로)
        )
    except Exception as e:
        logging.error(f"드라이버 초기화 실패: {e}")
        driver = uc.Chrome(
            options=options,
            enable_cdp_events=False,
            use_subprocess=False,
            headless=headless,
            version_main=143
        )

    # 기본 타임아웃
    driver.set_page_load_timeout(10)
    driver.set_script_timeout(10)
    driver.implicitly_wait(0)

    logging.info("✅ Chrome 드라이버 초기화 완료")
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
    - 알럿/성인안내 모달 처리
    - 느린 페이지 window.stop() + 지수 백오프 재시도
    """
    for i in range(retries):
        try:
            driver.set_page_load_timeout(15)
            driver.get(url)

            # 즉시 알럿 처리
            _maybe_accept_alert(driver)

            try:
                for btn in driver.find_elements(By.CSS_SELECTOR, "button, a"):
                    t = (btn.text or "").strip()
                    if any(k in t for k in ("동의", "확인", "continue")):
                        try:
                            btn.click()
                            break
                        except Exception:
                            pass
            except Exception:
                pass

            return True

        except UnexpectedAlertPresentException:
            logging.warning("[safe_get] unexpected alert → accept & retry")
            _maybe_accept_alert(driver)

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