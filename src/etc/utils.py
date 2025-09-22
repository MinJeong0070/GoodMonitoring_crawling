import os, re, json, time, random, logging
import pandas as pd
from datetime import datetime
import undetected_chromedriver as uc

from threading import Lock
from selenium.common.exceptions import (
    TimeoutException, WebDriverException, NoSuchWindowException,
    InvalidSessionIdException
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

today = datetime.now().strftime("%y%m%d")
os.makedirs('log', exist_ok=True)

# ---------------------------
# Chrome 드라이버 생성
# ---------------------------
def setup_driver():
    logging.info("웹드라이버 시작")
    options = uc.ChromeOptions()
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/128.0.0.0 Safari/537.36")
    options.add_argument(f"user-agent={ua}")
    options.page_load_strategy = 'eager'   # DOMContentLoaded 기준
    options.add_argument('--disable-popup-blocking')
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # options.add_argument("--headless=new")  # 필요시 활성

    driver = uc.Chrome(options=options, enable_cdp_events=True, incognito=True)
    driver.set_page_load_timeout(20)
    driver.set_script_timeout(20)

    # CDP: 불필요 리소스 차단
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


# ---------------------------
# 드라이버 매니저(자동 복구 핵심)
# ---------------------------
class DriverManager:
    """
    - 세션 유실/창 닫힘/invalid session 발생 시 자동 재생성
    - get() 호출만으로 복구 + 재시도
    - 주기적 헬스체크로 사전 감지
    """
    def __init__(self):
        self.lock = Lock()
        self.driver = setup_driver()
        self.nav_count = 0  # 네비게이션 횟수(헬스체크 트리거)

    def _healthcheck(self) -> bool:
        try:
            # 간단한 JS 실행 여부로 세션 생존 확인
            self.driver.execute_script("return 1+1")
            return True
        except (InvalidSessionIdException, NoSuchWindowException, WebDriverException):
            return False

    def restart(self):
        with self.lock:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = setup_driver()
            self.nav_count = 0
            logging.info("[DriverManager] 드라이버 재생성 완료")

    def ensure_alive(self):
        # 15회마다 가벼운 헬스체크(오버헤드 낮음)
        self.nav_count += 1
        if self.nav_count % 15 == 0 and not self._healthcheck():
            logging.warning("[DriverManager] 헬스체크 실패 → 드라이버 재생성")
            self.restart()

    def get(self, url: str, retries: int = 2, backoff: float = 1.0) -> bool:
        """
        안전 네비게이션: 세션 오류 시 즉시 재생성 후 재시도
        """
        for attempt in range(retries + 1):
            self.ensure_alive()
            try:
                self.driver.get(url)
                # 알럿 즉시 수습
                _accept_alert_if_present(self.driver, timeout=0.8)
                return True
            except (InvalidSessionIdException, NoSuchWindowException):
                logging.warning(f"[DriverManager] 세션 소실 감지 → 재생성 (attempt {attempt+1})")
                self.restart()
            except TimeoutException:
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
                logging.warning("[DriverManager] Timeout → 백오프 재시도")
            except WebDriverException as e:
                # 알럿 가능성 우선 처리
                if _accept_alert_if_present(self.driver, timeout=1.2):
                    try:
                        self.driver.get(url)
                        return True
                    except Exception:
                        pass
                logging.warning(f"[DriverManager] WebDriverException: {e} → 재시도")
            time.sleep(backoff * (2 ** attempt) + random.uniform(0, 0.5))
        logging.error(f"[DriverManager] GET 실패: {url}")
        return False

    def quit(self):
        try:
            self.driver.quit()
        except Exception:
            pass


# ---------------------------
# CSV/전처리 유틸
# ---------------------------
def result_csv_data(search, platform, subdir, base_path='csv'):
    file_path = os.path.join(base_path, subdir, today, f'{platform}_{search}.csv')
    if not os.path.isfile(file_path):
        return pd.DataFrame()
    try:
        return pd.read_csv(file_path, encoding='utf-8')
    except Exception as e:
        print(f"[오류] CSV 읽기 실패 ({file_path}): {e}")
        return pd.DataFrame()

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
    title = re.sub(r'\d+$', '', title or '').strip()
    title = re.sub(r'\.(jpg|png|gif|mp4|avi|mkv|webm|jpeg)$', '', title, flags=re.IGNORECASE).strip()
    title = re.sub(r'^[ㄱ-ㅎㅏ-ㅣ]+$', '', title).strip()
    title = title.replace('"', '').strip()
    return title


# ---------------------------
# 보조 유틸
# ---------------------------
def human_sleep(short_min=0.2, short_max=0.6, long_prob=0.0, long_min=6, long_max=10):
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

# 기존 호환용: safe_get → DriverManager.get 위임
def safe_get(driver, url, retries=3, base_sleep=1.2):
    """
    (하위호환) 외부 코드가 직접 driver를 넘길 때도 동작하도록 래핑.
    세션 유실 복구가 필요하면 DriverManager 사용을 권장.
    """
    try:
        driver.get(url)
        _accept_alert_if_present(driver, timeout=0.8)
        return True
    except (InvalidSessionIdException, NoSuchWindowException, TimeoutException, WebDriverException):
        # 최소한의 폴백: 간단 재시도
        for i in range(retries):
            try:
                driver.get(url)
                _accept_alert_if_present(driver, timeout=0.8)
                return True
            except Exception:
                time.sleep(base_sleep * (2 ** i) + random.uniform(0, 0.5))
        return False


# 진행상황 체크포인트
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
