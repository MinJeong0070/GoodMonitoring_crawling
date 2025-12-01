import time
from typing import List, Dict, Tuple

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

OUTPUT_PATH = r"D:\jupyter\community_site_crawling-main\site crawling\src\etc\Daum_cafe_test.xlsx"

QUERIES = ["파킨슨병"]

MAX_PAGES_PER_QUERY = 1        # 검색 결과 페이지 최대 몇 페이지까지 볼지
HEADLESS = False               # True 로 두면 브라우저 창 안 뜸

CHROMEDRIVER_PATH = r"C:\chromedriver-win64\chromedriver.exe"

# ========================================================

DAUM_CAFE_HOME_URL = "https://top.cafe.daum.net/"


# ---------------- 공통 유틸 ----------------

def init_driver(headless: bool = False):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,900")

    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(5)
    return driver


def safe_click(driver, locator, timeout: int = 10) -> bool:
    try:
        elem = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable(locator)
        )
        elem.click()
        time.sleep(1)
        return True
    except (TimeoutException, WebDriverException):
        return False


# ------------- 검색 페이지 조작 -------------

def open_search_page(driver):
    driver.get(DAUM_CAFE_HOME_URL)
    time.sleep(2)


def set_search_query_and_go(driver, query: str):
    """
    검색창: input#q.tf_keyword.inp_search
    """
    wait = WebDriverWait(driver, 10)
    search_input = wait.until(
        EC.presence_of_element_located((By.ID, "q"))
    )
    search_input.clear()
    search_input.send_keys(query)
    search_input.send_keys(Keys.ENTER)
    time.sleep(2)


def select_cafe_article_and_sort_recent(driver):
    """
    '카페글' 탭 선택 후 정렬 '최신' 선택
    (이미 선택되어 있으면 실패해도 무시)
    """
    safe_click(driver, (By.LINK_TEXT, "카페글"), timeout=5)
    safe_click(driver, (By.LINK_TEXT, "최신"), timeout=5)


def get_article_items(driver) -> List:
    """
    검색 결과 페이지에서 게시글 li 요소 리스트 가져오기.

    ul.list_scafe li 를 우선 사용.
    """
    selectors = ["ul.list_scafe li", "ul#articleContentWrap li"]

    for sel in selectors:
        items = driver.find_elements(By.CSS_SELECTOR, sel)
        if items:
            print(f"[INFO]  selector '{sel}' 에서 {len(items)}개 발견")
            return items

    print("[WARN]  게시글 리스트를 찾지 못했습니다.")
    return []


def parse_list_item(li_elem) -> Dict:
    """
    검색 결과 한 줄에서 제목/URL만 읽는다.
    날짜는 상세 페이지에서 다시 가져올 것.
    """
    try:
        a_title = li_elem.find_element(By.CSS_SELECTOR, "a.link_tit")
        title = a_title.text.strip()
        url = a_title.get_attribute("href")
    except NoSuchElementException:
        title = ""
        url = ""

    return {
        "title": title,
        "url": url,
    }


# ------------- 상세 페이지 크롤링 -------------

def fetch_post_detail(driver, url: str) -> Tuple[str, str, str]:
    """
    상세 페이지에서 작성자, 날짜, 전체 내용을 가져온다.

    - 작성자:  #primaryContent .cover_info a.link_item
    - 날짜:    #primaryContent .info_desc span.txt_item 들 중
              '.'와 ':'가 동시에 들어간 텍스트 (예: 25.11.28 02:42)
    - 본문:    div#user_contents
              (없으면 iframe들 내부에서 다시 탐색)
    """
    current_window = driver.current_window_handle

    author = ""
    post_date = ""
    content = ""

    try:
        # 새 탭으로 열기
        driver.execute_script("window.open(arguments[0]);", url)
        driver.switch_to.window(driver.window_handles[-1])

        wait = WebDriverWait(driver, 10)

        # primaryContent 등장까지 대기 (상단 영역)
        try:
            wait.until(
                EC.presence_of_element_located((By.ID, "primaryContent"))
            )
        except TimeoutException:
            # 느린 경우를 대비해서 약간 더 대기
            time.sleep(2)

        # ----- 작성자 -----
        try:
            author_el = driver.find_element(
                By.CSS_SELECTOR, "#primaryContent .cover_info a.link_item"
            )
            author = author_el.text.strip()
        except NoSuchElementException:
            author = ""

        # ----- 날짜 -----
        # span.txt_item 들 중에서 '.'와 ':'가 같이 들어간 텍스트를 우선적으로 선택
        try:
            info_desc = driver.find_element(
                By.CSS_SELECTOR, "#primaryContent .info_desc"
            )
            txt_items = info_desc.find_elements(By.CSS_SELECTOR, "span.txt_item")
            for span in txt_items:
                t = span.text.strip()
                if "." in t and ":" in t:  # 예: 25.11.28 02:42
                    post_date = t
                    break
            if not post_date and txt_items:
                # 혹시 위 조건에 안 걸려도 일단 첫 번째 값이라도 저장
                post_date = txt_items[0].text.strip()
        except NoSuchElementException:
            post_date = ""

        # ----- 본문 (1차: 현재 문서에서 바로 시도) -----
        try:
            content_el = driver.find_element(By.ID, "user_contents")
            content = content_el.text.strip()
        except NoSuchElementException:
            content = ""

        # ----- 본문 (2차: iframe 내부 탐색) -----
        if not content:
            try:
                frames = driver.find_elements(By.TAG_NAME, "iframe")
            except NoSuchElementException:
                frames = []

            for frame in frames:
                try:
                    driver.switch_to.frame(frame)
                    try:
                        content_el = driver.find_element(By.ID, "user_contents")
                        content = content_el.text.strip()
                        driver.switch_to.default_content()
                        break
                    except NoSuchElementException:
                        driver.switch_to.default_content()
                        continue
                except WebDriverException:
                    driver.switch_to.default_content()
                    continue

        return author, post_date, content

    finally:
        # 탭 닫고 원래 검색결과 탭으로 복귀
        try:
            driver.close()
        except WebDriverException:
            pass
        try:
            driver.switch_to.window(current_window)
        except WebDriverException:
            pass





def go_next_page_by_number(driver, current_page: int) -> bool:
    """
    하단 페이지네이션에서 다음 페이지 번호 클릭 (1→2, 2→3 ...)
    """
    next_page = current_page + 1
    xpath = f"//div[@class='paging_scafe']//a[normalize-space(text())='{next_page}']"
    return safe_click(driver, (By.XPATH, xpath), timeout=5)


# ------------- 메인 크롤러 (단일 검색어) -------------

def crawl_daum_cafe_for_query(
    driver,
    query_text: str,
    max_pages: int = 3,
) -> List[Dict]:
    """
    단일 검색어에 대해:
    - 카페글 + 최신 정렬
    - 각 게시글 상세 페이지까지 들어가서
      → 제목, 날짜, 작성자, 내용, URL 수집
    """
    print(f"[INFO] 검색어 크롤링 시작: {query_text}")

    open_search_page(driver)
    set_search_query_and_go(driver, query_text)
    select_cafe_article_and_sort_recent(driver)

    all_rows: List[Dict] = []
    current_page = 1

    while current_page <= max_pages:
        print(f"[INFO]  - 페이지 {current_page} 처리 중...")

        items = get_article_items(driver)
        if not items:
            print("[INFO]    게시글이 없습니다. 종료.")
            break

        for li in items:
            try:
                row = parse_list_item(li)
            except StaleElementReferenceException:
                continue

            url = row.get("url", "")
            if not url:
                continue

            author, post_date, content = fetch_post_detail(driver, url)

            all_rows.append(
                {
                    "검색어_쿼리": query_text,
                    "게시글_제목": row.get("title", ""),
                    "게시글_날짜": post_date,
                    "게시글_작성자": author,
                    "게시글_내용": content,
                    "게시글_URL": url,
                }
            )

        print(f"[INFO]    현재 검색어 누적 수집: {len(all_rows)}건")

        if not go_next_page_by_number(driver, current_page):
            print("[INFO]    다음 페이지가 없습니다. 종료.")
            break

        current_page += 1
        time.sleep(1)

    print(f"[INFO] 검색어 크롤링 완료: {query_text} (총 {len(all_rows)}건)")
    return all_rows


# ------------- 전체 실행 -------------

def main():
    driver = init_driver(headless=HEADLESS)

    try:
        all_results: List[Dict] = []

        for q in QUERIES:
            rows = crawl_daum_cafe_for_query(
                driver,
                query_text=q,
                max_pages=MAX_PAGES_PER_QUERY,
            )
            all_results.extend(rows)

        if all_results:
            df = pd.DataFrame(all_results)
            df.to_excel(OUTPUT_PATH, index=False)
            print(f"\n[INFO] 최종 {len(df)}건을 엑셀로 저장했습니다: {OUTPUT_PATH}")
        else:
            print("\n[INFO] 수집된 데이터가 없습니다.")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
