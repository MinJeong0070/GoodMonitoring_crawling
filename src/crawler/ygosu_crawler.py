import os
import re
import time
import random
import logging
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime

from src.etc.utils import setup_driver, save_to_csv, clean_title, result_csv_data

# 오늘 날짜
today = datetime.now().strftime("%y%m%d")

# 로그 디렉토리 생성
if not os.path.exists('log'):
    os.makedirs('log')

# 로그 설정
logging.basicConfig(
    filename=f'log/와이고수_log_{today}.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 게시글 상세 페이지 크롤링
def ygosu_crw(wd, url, search):
    try:
        wd.get(url)
        time.sleep(random.uniform(2, 4))
        soup = BeautifulSoup(wd.page_source, 'html.parser')

        title = soup.find('h1', class_='view-title').get_text(strip=True)
        content_div = soup.find('div', class_='view-content')
        content = content_div.get_text(separator='\n', strip=True)
        content = re.sub(r'http[s]?://\S+', '', content)  # 링크 제거

        info_box = soup.find('div', class_='view-info')
        date_text = info_box.find_all('span')[1].get_text(strip=True)
        writer = info_box.find('a').get_text(strip=True)

        post_date = datetime.strptime(date_text, '%Y-%m-%d %H:%M:%S').date()

        df = pd.DataFrame({
            "검색어": [search],
            "플랫폼": ["웹페이지(와이고수)"],
            "게시물 URL": [url],
            "게시물 제목": [clean_title(title)],
            "게시물 내용": [content],
            "게시물 등록일자": [post_date],
            "계정명": [writer]
        })

        save_to_csv(df, f'csv/25.와이고수/{today}/와이고수_{search}.csv')
        logging.info(f"[저장 완료] {url}")

    except Exception as e:
        logging.error(f"[상세 페이지 오류] {url} - {e}")


# 메인 크롤링 함수
def ygosu_main_crw(searchs, start_date, end_date, stop_event):
    if not os.path.exists(f'csv/25.와이고수/{today}'):
        os.makedirs(f'csv/25.와이고수/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")

    save_dir = f'csv/25.와이고수/{today}'
    os.makedirs(save_dir, exist_ok=True)

    logging.info("====== 와이고수 크롤링 시작 ======")
    wd = setup_driver()
    wd_dp1 = setup_driver()

    for search in searchs:
        if stop_event.is_set():
            print("🛑 크롤링 중단됨")
            break

        page_num = 1
        while True:
            if stop_event.is_set():
                break

            search_url = f"https://ygosu.com/all_search/?add_search_log=Y&keyword={search}&page={page_num}"
            wd_dp1.get(search_url)
            time.sleep(random.uniform(2, 4))
            soup = BeautifulSoup(wd_dp1.page_source, 'html.parser')

            if soup.find('div', class_='no_result'):
                logging.info(f"[검색결과 없음] '{search}' → 다음 키워드로")
                break

            #  게시글 목록 추출
            results = soup.find_all('li', class_=lambda x: x in ['default_body', 'thumbnail_body'])

            #  결과가 완전히 없으면 다음 키워드로
            if not results:
                logging.info(f"[검색결과 없음] {search} (page {page_num}) → 다음 키워드로")
                empty_result_flag = True
                break

            stop_flag = False
            for li in results:
                try:
                    a_tag = li.find('a', class_='subject')
                    href = a_tag.get('href')
                    post_url = f"https://ygosu.com{href}"

                    raw_date = li.find('span', class_='date').text.strip()
                    post_date = datetime.strptime(raw_date, '%y.%m.%d').date()

                    if post_date > end_date:
                        continue
                    if post_date < start_date:
                        stop_flag = True
                        break

                    ygosu_crw(wd, post_url, search)

                except Exception as e:
                    logging.error(f"[목록 파싱 오류] {e}")
                    continue

            if stop_flag:
                break

            page_num += 1

    wd.quit()
    wd_dp1.quit()
    # 통합 결과 저장
    if not stop_event.is_set():
        result_dir = '결과/와이고수'
        os.makedirs(result_dir, exist_ok=True)

        all_data = pd.concat([
            result_csv_data(search, platform='와이고수', subdir='25.와이고수')
            for search in searchs
        ])

        result_path = f'{result_dir}/와이고수_raw data_{today}.csv'
        all_data.to_csv(result_path, encoding='utf-8', index=False)
        logging.info(f"[최종 저장 완료] {result_path}")
