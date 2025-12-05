import time
import os
import re
from typing import List, Dict, Tuple
from datetime import datetime, date

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

# ====================== 사용자 설정 ======================

# 파일이 저장될 폴더 경로
SAVE_DIR = r"D:\jupyter\community_site_crawling-main\site crawling\src\etc"

# [업데이트] 이미지에서 추출한 15개 검색어 리스트
QUERIES = [
    "잠꼬대가 시그널이었다, 알리도 KO패 당한 그 병",
    "제발 뜨거운 물 참아라, 머리카락 사수하는 소소한 습관",
    "심장에 좋은 음식 뭐냐고요? 살부터 빼세요",
    "꿀잠 그립다→\"이젠 꿀잠\"...침대 사용법 알게 된 덕분",
    "순간 죽을 것 같은 공황 공포, 이럴 땐 펜 들어라",
    "코스피 폭락? 매달 돈 찍힌다...계좌 지켜줄 ‘방패ETF 12개’",
    "관세폭탄? 이때다 몰려갔다...고딩 개미도 해외주식 ‘줍줍’",
    "문 열 기미 보이는 러시아 시장...국내 기업들, 재진출 고심",
    "투잡러, 어서오세요...'월 400만원' 무인매장의 유혹",
    "나스닥 빠질 때 22% 올랐다...10년 담아둘 중국 'IT공룡' 등장",
    "도수치료 받고 실손 못 받는다...윤곽 드러낸 '5세대 실손보험'",
    "반려견 풀밭 두지 말라...치명률 47% 이 감염병, 주인도 노린다",
    "봄꽃 극장 이런 적 없었다...매화·목련·벚꽃 동시 상영",
    "‘벚꽃 성곽’ 품은 동네...동래로 봄마실",
    "‘단짠’ 조합으로 치팅한 다음날, 부종과 독소 빼려면 '이것'"
]

# 수집할 기간 설정 (YYYY-MM-DD)
TARGET_START_DATE = date(2025, 4, 1)
TARGET_END_DATE = date(2025, 11, 30)

MAX_PAGES_PER_QUERY = 100
HEADLESS = False  # 작업 과정을 보려면 False, 안 보고 속도 높이려면 True

CHROMEDRIVER_PATH = r"C:\chromedriver-win64\chromedriver.exe"
DAUM_CAFE_HOME_URL = "https://top.cafe.daum.net/"


# ========================================================

def parse_date_str(date_text: str) -> date:
    """날짜 문자열 파싱 (예: 25.10.28 -> 2025-10-28)"""
    if not date_text: return None
    try:
        date_text = date_text.strip().rstrip(".")
        if "." in date_text:
            parts = date_text.split(".")
            if len(parts) >= 3:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2].split(" ")[0])
                if year < 100: year += 2000
                return date(year, month, day)
    except:
        pass
    return None


def init_driver(headless: bool = False):
    """드라이버 초기화 및 속도 최적화 옵션 적용"""
    options = Options()
    if headless:
        options.add_argument("--headless=new")

    # [속도 최적화] 이미지, 알림, 팝업 차단
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.popups": 2,
    }
    options.add_experimental_option("prefs", prefs)

    # [속도 최적화] 페이지 로드 전략: Eager
    options.page_load_strategy = 'eager'

    # [로그 최적화]
    options.add_argument("--log-level=3")
    options.add_argument("--disable-logging")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    # 차단 방지
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,900")

    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(2)
    return driver


def safe_click(driver, locator, timeout: int = 5) -> bool:
    try:
        elem = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))
        elem.click()
        time.sleep(0.3)
        return True
    except:
        return False


# ------------- 페이지 조작 로직 -------------

def open_search_page(driver):
    driver.get(DAUM_CAFE_HOME_URL)
    try:
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "q")))
    except:
        time.sleep(1)


def set_search_query_and_go(driver, query: str):
    try:
        wait = WebDriverWait(driver, 5)
        search_input = wait.until(EC.presence_of_element_located((By.ID, "q")))
        search_input.clear()
        search_input.send_keys(query)
        search_input.send_keys(Keys.ENTER)
        time.sleep(1)
    except:
        print("[ERR] 검색창 못찾음")


def get_article_items(driver) -> List:
    selectors = ["ul.list_scafe li", "ul#articleContentWrap li"]
    for sel in selectors:
        items = driver.find_elements(By.CSS_SELECTOR, sel)
        if items: return items
    return []


def parse_list_item(li_elem) -> Dict:
    data = {"title": "", "url": "", "date_str": "", "author_list": ""}
    try:
        tit = li_elem.find_element(By.CSS_SELECTOR, "a.link_tit")
        data["title"] = tit.text.strip()
        data["url"] = tit.get_attribute("href")
    except:
        pass

    try:
        data["date_str"] = li_elem.find_element(By.CSS_SELECTOR, "span.info_scafe").text.strip()
    except:
        pass

    try:
        data["author_list"] = li_elem.find_element(By.CSS_SELECTOR, "a.link_cafe").text.strip()
    except:
        pass

    return data


def fetch_post_content_detail(driver, url: str) -> Tuple[str, str]:
    current_handle = driver.current_window_handle
    content, detail_author = "", ""

    try:
        driver.execute_script("window.open(arguments[0]);", url)
        driver.switch_to.window(driver.window_handles[-1])
        wait = WebDriverWait(driver, 3)

        try:
            wait.until(EC.presence_of_element_located((By.ID, "primaryContent")))
        except:
            pass

        try:
            detail_author = driver.find_element(By.CSS_SELECTOR, "#primaryContent .cover_info a.link_item").text.strip()
        except:
            pass

        try:
            content = driver.find_element(By.ID, "user_contents").text.strip()
        except:
            pass

        if not content:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in frames[:2]:
                try:
                    driver.switch_to.frame(frame)
                    content = driver.find_element(By.ID, "user_contents").text.strip()
                    driver.switch_to.default_content()
                    if content: break
                except:
                    driver.switch_to.default_content()

        return content, detail_author

    except:
        return "", ""
    finally:
        try:
            if len(driver.window_handles) > 1:
                driver.close()
            driver.switch_to.window(current_handle)
        except:
            pass


def crawl_query(driver, query: str, max_pages: int) -> List[Dict]:
    print(f"\n{'=' * 60}\n[INFO] '{query}' 크롤링 시작\n{'=' * 60}")

    open_search_page(driver)
    set_search_query_and_go(driver, query)

    safe_click(driver, (By.LINK_TEXT, "카페글"))
    safe_click(driver, (By.LINK_TEXT, "최신"))

    results = []
    page = 1
    finished = False

    while page <= max_pages and not finished:
        print(f" >> [Page {page}] 스캔 중...", end="\r")
        items = get_article_items(driver)
        if not items:
            print("\n    게시글이 없습니다. 종료.")
            break

        for item in items:
            try:
                info = parse_list_item(item)
                if not info['url']: continue

                d_obj = parse_date_str(info['date_str'])
                if d_obj:
                    if d_obj > TARGET_END_DATE: continue
                    if d_obj < TARGET_START_DATE:
                        print(f"\n    [STOP] 날짜 범위 경과 ({info['date_str']}). 수집 종료.")
                        finished = True
                        break

                content, d_author = fetch_post_content_detail(driver, info['url'])
                final_author = d_author if d_author else info['author_list']

                row = {
                    "검색어": query,
                    "제목": info['title'],
                    "날짜": info['date_str'],
                    "작성자": final_author,
                    "내용": content,
                    "URL": info['url']
                }
                results.append(row)

                print(f"\n  [#{len(results)}] {info['date_str']} | {info['title'][:30]}...")
                print(f"   • 작성자: {final_author}")
                print(f"   • URL: {info['url']}")
                print("  " + "-" * 50)

            except StaleElementReferenceException:
                continue
            except Exception:
                continue

        if not finished:
            next_btn = f"//div[@class='paging_scafe']//a[normalize-space(text())='{page + 1}']"
            if not safe_click(driver, (By.XPATH, next_btn), timeout=3):
                print("\n    마지막 페이지입니다.")
                break
            page += 1
            time.sleep(0.5)

    return results


# ------------- 실행부 -------------

def main():
    if not os.path.exists(SAVE_DIR): os.makedirs(SAVE_DIR)

    for query in QUERIES:
        driver = None
        try:
            driver = init_driver(headless=HEADLESS)
            data = crawl_query(driver, query, MAX_PAGES_PER_QUERY)

            if data:
                # 파일명 특수문자 및 길이 안전 처리
                safe_q = re.sub(r'[\\/*?:"<>|]', "_", query)
                if len(safe_q) > 30:  # 파일명이 너무 길면 잘라서 저장
                    safe_q = safe_q[:30]

                fname = f"Daum_{safe_q}_{datetime.now().strftime('%y%m%d')}.xlsx"
                fpath = os.path.join(SAVE_DIR, fname)

                df = pd.DataFrame(data)
                df.to_excel(fpath, index=False, engine='openpyxl')
                print(f"   >>> [저장 완료] {fname}")
            else:
                print(f"   >>> [알림] 데이터 없음: {query}")

        except Exception as e:
            print(f"\n[CRITICAL] '{query}' 처리 중 에러: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            print("   >>> 브라우저 리셋...\n")


if __name__ == "__main__":
    main()