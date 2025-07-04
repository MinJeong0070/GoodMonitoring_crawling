import os
import re
import time
import random
import logging
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import WebDriverException
from datetime import datetime,date

from src.crawler.setup import setup_driver, save_to_csv, clean_title,result_csv_data

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

logging.basicConfig(
    filename=f'더쿠_log_{today}.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
today = datetime.now().strftime("%y%m%d")
def parse_theqoo_date(raw_text):
    today = date.today()
    try:
        # 1. "HH:MM" → 오늘 날짜
        if re.match(r"^\d{2}:\d{2}$", raw_text):
            return today

        # 2. "MM.DD" → 올해 날짜
        elif re.match(r"^\d{2}\.\d{2}$", raw_text):
            month, day = map(int, raw_text.split('.'))
            return date(today.year, month, day)

        # 3. "YY.MM.DD" → 연도 포함
        elif re.match(r"^\d{2}\.\d{2}\.\d{2}$", raw_text):
            return datetime.strptime(raw_text, "%y.%m.%d").date()

        else:
            logging.warning(f"날짜 형식 인식 불가: {raw_text}")
            return None
    except Exception as e:
        logging.error(f"날짜 파싱 오류: {raw_text}, 오류: {e}")
        return None

def dq_crw(wd, url, searchs):
    try:
        logging.info(f"더쿠 크롤링 시작: {url}")
        wd.get(url)
        time.sleep(1)
        WebDriverWait(wd, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.theqoo_document_header > span.title"))
        )

        soup = BeautifulSoup(wd.page_source, 'html.parser')

        raw_title = wd.find_element(By.CSS_SELECTOR, "div.theqoo_document_header > span.title").text.strip()
        cleaned_title = clean_title(raw_title)

        article_tag = soup.find('article', attrs={"itemprop": "articleBody"})
        if not article_tag:
            print("본문 <article> 태그가 없음")
            return

        content_div = article_tag.find('div', class_=lambda x: x and 'rhymix_content' in x and 'xe_content' in x)
        if not content_div:
            print("본문 내용 div를 찾을 수 없음")
            return

        post_content = wd.find_element(By.CSS_SELECTOR, "article[itemprop='articleBody']").text
        post_content = re.sub(r'http[s]?://\S+', '', post_content).strip()

        # 날짜 파싱
        date_tag = soup.select_one('div.side.fr > span')
        if not date_tag:
            logging.warning(f"날짜 정보가 없습니다: {url}")
            return
        date_str = date_tag.get_text(strip=True)
        try:
            date = datetime.strptime(date_str.split()[0], '%Y.%m.%d').date()
        except Exception as e:
            logging.error(f"날짜 파싱 오류: {date_str}, 오류: {e}")
            return

        writer_tag = soup.select_one('div.side')
        if writer_tag:
            # 링크 제외하고 텍스트만 추출
            writer = ''.join([t for t in writer_tag.contents if isinstance(t, str)]).strip()
            if writer == "무명의 더쿠":
                writer = "익명"
        else:
            writer = "익명"
        # images = content_div.find_all('img')
        # videos = content_div.find_all('video')
        # youtube_iframes = [i for i in content_div.find_all('iframe') if 'youtube.com' in str(i.get('src'))]
        # has_media = 'O' if images or videos or youtube_iframes else ' '

        now_time = datetime.now().strftime('%Y-%m-%d ')

        # ✅ 매칭되는 검색어가 있을 때마다 저장
        for search in searchs:
            if search.lower() in cleaned_title.lower() or search.lower() in post_content.lower():
                df = pd.DataFrame({
                    "검색어": [search],
                    "플랫폼": ["웹페이지(더쿠)"],
                    "게시물 URL": [url],
                    "게시물 제목": [cleaned_title],
                    "게시물 내용": [post_content],
                    "게시물 등록일자": [date],
                    "계정명": [writer],
                    "수집시간": [now_time],
                    # "이미지 유무": [has_media]
                })
                save_to_csv(df, f'../csv/24.더쿠/{today}/더쿠_{search}.csv')
                logging.info(f'csv/24.더쿠/{today}/인스티즈_{search}.csv')

    except Exception as e:
        logging.error(f"상세 페이지 오류: {e}")
        print(f"상세 페이지 오류: {e}")


def dq_main_crw(searchs, start_date, end_date, max_pages=1400):
    if not os.path.exists(f'../csv/24.더쿠/{today}'):
        os.makedirs(f'../csv/24.더쿠/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")
    logging.info(f"========================================================")
    logging.info(f"                    더쿠 크롤링 시작")
    logging.info(f"========================================================")
    wd = setup_driver()
    wd_detail = setup_driver()

    page_num = 1
    visited_urls = set()

    while page_num <= max_pages:
        url_list_page = f'https://theqoo.net/square/category/512000849?page={page_num}'
        logging.info(f"[{page_num}페이지] 접속: {url_list_page}")
        print(f"[{page_num}페이지] 접근 중...")

        try:
            wd.get(url_list_page)
            time.sleep(random.uniform(2, 3))

            WebDriverWait(wd, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'tbody.hide_notice tr'))
            )

            soup = BeautifulSoup(wd.page_source, 'html.parser')
            post_list = soup.select('tbody.hide_notice tr:not(.notice)')

            all_old = True
            stop_flag = False

            for post in post_list:
                try:
                    date_str = post.select_one('.time').get_text(strip=True)
                    post_date = parse_theqoo_date(date_str)
                    if not post_date:
                        continue

                    if post_date >= start_date:
                        all_old = False
                    if post_date > end_date:
                        continue
                    if post_date < start_date:
                        stop_flag = True
                        continue

                    title_tag = post.select_one('td.title > a:not(.replyNum)')
                    if not title_tag:
                        continue

                    post_url = 'https://theqoo.net' + title_tag.get('href')
                    if post_url in visited_urls:
                        continue
                    visited_urls.add(post_url)

                    # ✅ 검색어 리스트 통째로 전달
                    dq_crw(wd_detail, post_url, searchs)

                except Exception as e:
                    logging.error(f"리스트 처리 중 오류: {e}")
                    continue

            if all_old:
                page_num += 1
                continue

            if stop_flag:
                break

            page_num += 1

        except WebDriverException as e:
            logging.error(f"{page_num}페이지 WebDriver 예외 발생: {e}")
            print(f"❌ WebDriver 예외 발생! 드라이버 재시작 중...")
            wd.quit()
            wd = setup_driver()
            page_num += 1
            continue

    wd.quit()
    wd_detail.quit()


    result_dir = '../결과/더쿠'
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)

    all_data = pd.concat([
        result_csv_data(search, platform='더쿠', subdir='24.더쿠')
        for search in searchs
    ])

    all_data.to_csv(f'{result_dir}/더쿠_raw data_{today}.csv', encoding='utf-8', index=False)


