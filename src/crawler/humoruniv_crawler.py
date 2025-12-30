import os
import re
import time
import random
import logging
import pandas as pd
import pyperclip
import undetected_chromedriver as uc  # [핵심] 봇 탐지 우회 드라이버
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import UnexpectedAlertPresentException
from datetime import datetime

from src.etc.utils import save_to_csv, clean_title, result_csv_data

# setup_driver는 제거하고 아래 get_undetected_driver를 사용합니다.

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f"log"):
    os.makedirs(f"log")

# 로그 설정
logging.basicConfig(
    filename=f"웃긴대학_log_{today}.txt",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",
)


# Selenium 탐지 우회용 undetected_chromedriver 설정 및 생성
def get_undetected_driver():
    """
    일반 Selenium 대신 undetected-chromedriver를 사용하여
    봇 탐지를 우회하는 드라이버를 생성합니다.
    """
    options = uc.ChromeOptions()
    # options.add_argument('--headless') # 차단 회피를 위해 가급적 헤드리스는 끕니다.
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-popup-blocking')

    # 드라이버 생성 (버전 자동 매칭)
    driver = uc.Chrome(options=options, use_subprocess=True)
    return driver


# 알림창(Unexpected Alert) 발생 시 자동 처리 및 로그 기록
def handle_unexpected_alert(driver, context: str = "") -> str | None:
    try:
        alert = driver.switch_to.alert
        text = alert.text
        logging.warning(f"[ALERT]({context}) {text}")
        alert.accept()
        time.sleep(random.uniform(2.0, 3.0))  # Alert 처리 후 충분히 대기
        return text
    except Exception:
        return None


# 키보드 입력 대신 클립보드 복사/붙여넣기를 활용한 검색어 입력
def clipboard_input(driver, element, user_input):
    """클립보드 복사 -> 붙여넣기 (봇 탐지 최소화)"""
    try:
        pyperclip.copy(user_input)
        element.click()
        # 전체 선택 후 삭제
        element.send_keys(Keys.CONTROL, 'a')
        time.sleep(random.uniform(0.1, 0.3))
        element.send_keys(Keys.BACKSPACE)
        time.sleep(random.uniform(0.5, 1.0))
        # 붙여넣기
        element.send_keys(Keys.CONTROL, 'v')
        time.sleep(random.uniform(0.5, 1.0))
    except Exception as e:
        logging.error(f"클립보드 입력 실패: {e}")
        element.clear()
        element.send_keys(user_input)


# 웃긴대학 단일 게시글 상세 크롤링 및 CSV 저장
def humoruniv_crw(wd, url, search):
    try:
        logging.info(f"크롤링 시작: {url}")
        wd.set_page_load_timeout(30)  # 타임아웃 넉넉하게

        try:
            wd.get(f"{url}")
        except UnexpectedAlertPresentException:
            msg = handle_unexpected_alert(wd, context="상세 페이지 이동")
            logging.error(f"[상세] 스킵: {msg}")
            return pd.DataFrame()

        time.sleep(random.uniform(1.5, 2.5))  # 페이지 이동 후 딜레이

        try:
            WebDriverWait(wd, 15).until(EC.presence_of_element_located((By.ID, "cnts")))
        except UnexpectedAlertPresentException:
            handle_unexpected_alert(wd, context="상세 로딩")
            return pd.DataFrame()
        except Exception:
            return pd.DataFrame()

        soup = BeautifulSoup(wd.page_source, "html.parser")

        # 데이터 담을 리스트
        search_word_list = []
        search_plt_list = []
        writer_list = []
        url_list = []
        title_list = []
        content_list = []
        date_list = []

        try:
            content_div = soup.find("div", id="cnts")
            tb = soup.find("table", id="profile_table").find("table")

            raw_title = tb.find("span", id="ai_cm_title").get_text()
            cleaned_title = clean_title(raw_title)
            title_list.append(cleaned_title)

            for a_tag in content_div.find_all("a"):
                a_tag.decompose()
            post_content = content_div.get_text(separator=" ", strip=True)
            post_content_cleaned = re.sub(r"https?://[^\s]+", "", post_content)
            content_list.append(post_content_cleaned)

            search_plt_list.append("웹페이지(웃긴대학)")
            url_list.append(url)
            search_word_list.append(search)

            date_str = tb.find("div", id="content_info").find_all("span")[4].get_text().strip().split(" ")[0]
            date = datetime.strptime(date_str, "%Y-%m-%d")
            date_list.append(date)

            writer_list.append(tb.find("span", class_="hu_nick_txt").get_text())

            main_temp = pd.DataFrame({
                "검색어": search_word_list,
                "플랫폼": search_plt_list,
                "게시물 URL": url_list,
                "게시물 제목": title_list,
                "게시물 내용": content_list,
                "게시물 등록일자": date_list,
                "계정명": writer_list,
            })

            save_to_csv(main_temp, f"csv/11.웃긴대학/{today}/웃긴대학_{search}.csv")
            logging.info(f"저장완료: {cleaned_title}")

        except Exception as e:
            logging.error(f"파싱 중 에러: {e}")
            return pd.DataFrame()

    except Exception as e:
        logging.error(f"오류 발생: {e}")
        return pd.DataFrame()


# 웃긴대학 전체 게시글 반복 수집 (검색어별, 날짜 필터 포함)
def humoruniv_main_crw(searchs, start_date, end_date, stop_event):
    if not os.path.exists(f"csv/11.웃긴대학/{today}"):
        os.makedirs(f"csv/11.웃긴대학/{today}")

    logging.info(f"=== 웃긴대학 크롤링 시작 (Undetected Mode) ===")

    # 날짜 변환
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    elif isinstance(start_date, datetime):
        start_date = start_date.date()

    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    elif isinstance(end_date, datetime):
        end_date = end_date.date()

    # [중요] 일반 드라이버 대신 우회 드라이버 사용
    # 주의: 실행 시 기존에 켜져 있는 크롬창을 모두 닫는 것이 좋습니다.
    wd = get_undetected_driver()
    wd_dp1 = get_undetected_driver()

    site_blocked = False

    for search in searchs:
        if stop_event.is_set() or site_blocked:
            break

        while True:
            if stop_event.is_set() or site_blocked:
                break

            try:
                logging.info(f"검색 시작: {search}")
                url = "https://web.humoruniv.com/main.html"

                try:
                    wd_dp1.get(url)
                except UnexpectedAlertPresentException:
                    msg = handle_unexpected_alert(wd_dp1, "메인 진입")
                    if msg and "사이트에서 직접" in msg:
                        site_blocked = True;
                        break

                try:
                    WebDriverWait(wd_dp1, 15).until(EC.presence_of_element_located((By.ID, "wrap_sch")))
                except:
                    handle_unexpected_alert(wd_dp1, "메인 로딩")

                time.sleep(random.uniform(1.0, 2.0))

                # 검색어 입력
                try:
                    keyword_input = wd_dp1.find_element(By.ID, "search_text")
                    clipboard_input(wd_dp1, keyword_input, search)  # 클립보드 입력

                    time.sleep(random.uniform(0.5, 1.5))

                    submit_btn = wd_dp1.find_element(By.XPATH, '//input[@alt="검색"]')
                    submit_btn.click()

                except UnexpectedAlertPresentException:
                    msg = handle_unexpected_alert(wd_dp1, "검색 실행")
                    if msg and "사이트에서 직접" in msg:
                        logging.error("차단 감지됨 -> 종료")
                        site_blocked = True
                        break
                    break
                except Exception as e:
                    logging.error(f"검색 입력 실패: {e}")
                    break

                time.sleep(random.uniform(3.0, 5.0))  # 검색 결과 대기

                try:
                    soup_dp1 = BeautifulSoup(wd_dp1.page_source, "html.parser")
                except UnexpectedAlertPresentException:
                    handle_unexpected_alert(wd_dp1, "소스 파싱")
                    break

                date_flag = False
                after_start_date = False

                tables = soup_dp1.find_all("table", {"width": "100%", "style": "border-collapse:collapse;"})

                if not tables:  # 테이블 못 찾았으면 차단되었거나 결과 없음
                    logging.info("검색 결과 테이블 없음")

                # 게시글 루프
                for tb in tables:
                    if stop_event.is_set(): break

                    try:
                        date_str = tb.find("font", class_="gray").text.split(" ")[0]
                        date = datetime.strptime(date_str, "%Y-%m-%d").date()

                        if start_date <= date <= end_date:
                            date_flag = True

                            raw_href = tb.find("a").get("href").strip()

                            if raw_href.startswith("http"):
                                link_url = raw_href
                            elif raw_href.startswith("//"):
                                link_url = "https:" + raw_href
                            else:
                                # 경로가 '/'로 시작하지 않으면 붙여줌
                                if not raw_href.startswith("/"):
                                    raw_href = "/" + raw_href
                                # 도메인 강제 결합
                                link_url = "https://web.humoruniv.com" + raw_href

                            logging.info(f"URL 생성 확인: {link_url}")  # 로그로 확인

                            # 상세 크롤링 실행
                            humoruniv_crw(wd, link_url, search)

                            # 크롤링 후 잠시 대기
                            time.sleep(random.uniform(2.0, 3.5))

                    except Exception:
                        continue

                if not after_start_date and not date_flag:
                    logging.info("기간 내 게시글 없음 -> 다음 검색어")
                    break

                try:
                    # '다음' 버튼 찾기 (CSS 선택자 수정 가능성 있음)
                    # 웃긴대학의 다음 버튼은 보통 javascript:paging(...) 형태이거나 이미지 버튼임
                    # 여기서는 기존 코드의 흐름 유지하되 예외처리 강화
                    next_btns = wd_dp1.find_elements(By.XPATH, "//a[contains(text(), '[다음]')]")
                    if next_btns:
                        next_btns[0].click()
                        logging.info("다음 페이지 클릭")
                        time.sleep(random.uniform(3.0, 5.0))
                    else:
                        logging.info("다음 페이지 버튼 없음 -> 종료")
                        break

                except Exception as e:
                    logging.error(f"페이징 실패: {e}")
                    break

            except Exception as e:
                logging.error(f"메인 루프 에러: {e}")
                break


    wd.quit()
    wd_dp1.quit()

    if not site_blocked and not stop_event.is_set():
        result_dir = "결과/웃긴대학"
        if not os.path.exists(result_dir):
            os.makedirs(result_dir)

        try:
            all_data = pd.concat([result_csv_data(search, platform="웃긴대학", subdir="11.웃긴대학") for search in searchs])
            all_data.to_csv(f"{result_dir}/웃긴대학_raw data_{today}.csv", encoding="utf-8", index=False)
            logging.info("전체 병합 완료")
        except Exception:
            pass
    elif site_blocked:
        print("🛑 웃긴대학 보안 로직에 의해 차단되었습니다. 나중에 다시 시도하세요.")