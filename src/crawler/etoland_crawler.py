import os
import re
import time
import random
import logging
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote

from src.etc.utils import setup_driver, save_to_csv, clean_title, result_csv_data

# 날짜/로그 설정
today = datetime.now().strftime("%y%m%d")
if not os.path.exists('log'):
    os.makedirs('log')

logging.basicConfig(
    filename=f'이토랜드_log_{today}.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)


def etoland_crw(wd, url, search):
    try:
        logging.info(f"[본문 크롤링 시작] {url}")
        wd.set_page_load_timeout(10)
        wd.get(url)
        time.sleep(random.uniform(1, 2))

        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.ID, 'view_content')))
        soup = BeautifulSoup(wd.page_source, 'html.parser')

        # 제목
        title = soup.find('h1').get_text(strip=True)

        # 작성자
        writer = soup.find('span', class_='member').get_text(strip=True)

        # 날짜
        raw_date = soup.find('span', class_='mw_basic_view_datetime').get_text(strip=True)
        date = raw_date.split('(')[0].strip()

        # 본문 내용
        content_div = soup.find('div', id='view_content')
        addr_box = content_div.find('div', class_='view_document_address')
        if addr_box:
            addr_box.decompose()

        content_text = content_div.get_text(separator=' ', strip=True)
        content_cleaned = re.sub(r'https?://[^\s]+', '', content_text)

        # 결과 저장
        df = pd.DataFrame({
            "검색어": [search],
            "플랫폼": ["웹페이지(이토랜드)"],
            "게시물 URL": [url],
            "게시물 제목": [clean_title(title)],
            "게시물 내용": [content_cleaned],
            "게시물 등록일자": [date],
            "계정명": [writer],
        })

        save_to_csv(df, f'csv/26.이토랜드/{today}/이토랜드_{search}.csv')
        logging.info(f"[저장 완료] {url}")

    except Exception as e:
        logging.error(f"[본문 크롤링 실패] {url} / {e}")


# 메인 크롤링
def etoland_main_crw(searchs, start_date, end_date, stop_event):
    if not os.path.exists(f'csv/26.이토랜드/{today}'):
        os.makedirs(f'csv/26.이토랜드/{today}')
        print(f"[폴더 생성 완료] csv/26.이토랜드/{today}")

    logging.info("========== 이토랜드 크롤링 시작 ==========")
    wd = setup_driver()
    wd_dp1 = setup_driver()
    for search in searchs:
        if stop_event.is_set():
            print("🛑 크롤링 중단됨")
            break
        search_encoded = quote(search, encoding='euc-kr')
        current_url = f"https://www.etoland.co.kr/bbs/new2.php?sfl=subject&sword={search_encoded}"
        no_result_count = 0
        while True:
            if stop_event.is_set():
                break

            try:
                wd.get(current_url)
                WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'board_new2_list')))
                time.sleep(random.uniform(1, 2))

                soup = BeautifulSoup(wd.page_source, 'html.parser')
                if soup.find('div', class_='no_list_div'):
                    no_result_count += 1
                    logging.info(f"[빈 검색 결과] {no_result_count}회 연속 → {current_url}")

                    if no_result_count >= 5:
                        logging.warning(f"[중단] 빈 결과가 5회 연속 발생하여 검색어 '{search}' 종료")
                        break
                time.sleep(random.uniform(2, 5))
                ul_tag = soup.find('ul', class_='board_new2_list')
                li_tags = ul_tag.find_all('li')
                after_start_date = False
                for li in li_tags:
                    if stop_event.is_set():
                        break

                    if li.get('class') and ('board_new2_title' in li['class'] or 'middle_line' in li['class']):
                        continue

                    try:
                        subject_div = li.find('div', class_='subject')
                        a_tag = subject_div.find('a', href=True)
                        title = a_tag.get_text(separator=' ', strip=True)
                        href = a_tag['href']
                        full_url = f"https://www.etoland.co.kr/bbs{href.lstrip('.')}"

                        writer = li.find('div', class_='writer').find('span', class_='member').get_text(strip=True)

                        date_str = li.find('div', class_='datetime').get_text(strip=True)
                        if re.match(r'^\d{2}-\d{2}$', date_str):
                            date_str = f"{datetime.now().year}-{date_str}"
                        post_date = datetime.strptime(date_str, '%Y-%m-%d').date()

                        if post_date > end_date:
                            continue
                        if post_date < start_date:
                            after_start_date = True
                            break  # stop crawling

                        logging.info(f"[게시글 추출] {title} ({post_date})")
                        etoland_crw(wd_dp1, full_url, search)

                    except Exception as e:
                        logging.warning(f"[리스트 항목 파싱 실패] {e}")
                        continue
                if after_start_date:
                    logging.info(f"[종료] '{search}'는 start_date보다 이전 게시글 도달")
                    break
                # 다음검색 링크 처리
                next_link_tag = soup.find('a', string='다음검색')

                if next_link_tag:
                    next_href = next_link_tag.get('href')
                    next_url = f"https://www.etoland.co.kr{next_href.lstrip('..')}"

                    parsed = urlparse(next_url)
                    query = parse_qs(parsed.query)


                    if 'sword' in query:
                        raw_keyword = query['sword'][0]
                        reencoded_keyword = quote(raw_keyword, encoding='euc-kr')
                        query['sword'] = [reencoded_keyword]


                    new_query = urlencode(query, doseq=True)
                    current_url = urlunparse((
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        parsed.params,
                        new_query,
                        parsed.fragment
                    ))
                    logging.info(f"[다음검색 이동] {current_url}")
                else:
                    break

            except Exception as e:
                logging.error(f"[페이지 로딩 실패] {e}")
                break

    wd.quit()
    wd_dp1.quit()
    if not stop_event.is_set():
        result_dir = '결과/이토랜드'
        if not os.path.exists(result_dir):
            os.makedirs(result_dir)

        all_data = pd.concat([
            result_csv_data(search, platform='이토랜드', subdir='26.이토랜드')
            for search in searchs
        ])
        all_data.to_csv(f'{result_dir}/이토랜드_raw data_{today}.csv', encoding='utf-8', index=False)
        print(f"[최종 저장 완료] 결과/이토랜드/이토랜드_raw data_{today}.csv")
