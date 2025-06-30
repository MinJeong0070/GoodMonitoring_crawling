import re
import os
import time
import logging
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from datetime import datetime

from src.crawler.setup import setup_driver, save_to_csv, clean_title
from src.etc.csv_to_excel import csv_to_excel
# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

logging.basicConfig(
    filename=f'../log/KBDIO_log_{today}.txt',  # 로그 파일 이름
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)


def result_csv_data(search):
    file_path = f'../csv/25.KBDIO/{today}/KBDIO_{search}.csv'

    # 파일 존재 여부 확인
    if not os.path.isfile(file_path):
        print(f"파일 '{file_path}'이 존재하지 않습니다. 스킵합니다.")
        return

    # CSV 파일 읽기
    df_fm = pd.read_csv(file_path, encoding='utf-8')

    return df_fm
# 한페이지 크롤링
def kbdio_crw(wd, url,valid_domains,final_file):
    try:
        wd.get(url)
        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'article-wrap')))
        time.sleep(2)

        soup = BeautifulSoup(wd.page_source, 'html.parser')

        # 제목
        title_tag = soup.select_one('div.article-header > h1.article-subject')
        title = clean_title(title_tag.get_text(strip=True)) if title_tag else '제목없음'

        # 등록일자
        date_tag = soup.select_one('div.article-meta > span')
        raw_date = date_tag.get_text(strip=True).replace("입력 :", "").strip() if date_tag else ''
        try:
            post_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except:
            post_date = raw_date  # 형식이 다르면 원본 그대로

        # 본문 내용
        content_div = soup.select_one('div.tt_article_useless_p_margin')
        if not content_div:
            logging.warning(f"[본문 없음] {url}")
            return

        # 원문기사 URL (본문 내 a 태그 중 '원문기사' 텍스트 포함 링크)
        original_url = ''
        for a_tag in content_div.find_all('a', href=True):
            href = a_tag['href']
            if any(domain in href for domain in valid_domains):
                original_url = href
                break
        if not original_url:
            logging.info(f"[건너뜀] 유효한 원문기사 URL 없음: {url}")
            return  # ❌ 저장하지 않고 종료

        # 하이퍼링크 제거
        for a in content_div.find_all('a'):
            a.decompose()

        content_text = content_div.get_text(separator='\n', strip=True)
        content_text = re.sub(r'\n{2,}', '\n', content_text)

        # 저장
        df = pd.DataFrame([{
            "플랫폼": "웹사이트(kbdio)",
            "게시물 URL": url,
            "게시물 제목": title,
            "게시물 내용": content_text,
            "게시물 등록일자": post_date,
            "원문기사 URL": original_url
        }])


        save_to_csv(df, final_file)
        logging.info(f"[저장 완료] {title}")

    except Exception as e:
        logging.error(f"[본문 오류] {url} / {e}")




def kbdio_main_crw(search,start_date, end_date):
    final_file = f'../csv/25.KBDIO/{today}/KBDIO.csv'
    if not os.path.exists(f'../csv/25.KBDIO/{today}'):
        os.makedirs(f'../csv/25.KBDIO/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")

    logging.info("======== KBDIO 전체 게시글 크롤링 시작 ========")

    wd = setup_driver()
    wd_dp1 = setup_driver()
    page_num = 10
    stop_flag = False

    domain_df = pd.read_excel('../(언진) 전처리용 도메인 주소.xlsx')
    valid_domains = domain_df['도메인'].dropna().unique().tolist()

    while True:
        try:
            url = f"https://www.kbdio.com/?page={page_num}"
            logging.info(f"[페이지 {page_num}] 접근 중: {url}")
            wd.get(url)
            WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'list-item')))
            time.sleep(3)
            soup = BeautifulSoup(wd.page_source, 'html.parser')
            article_blocks = soup.select('div.list-item')

            if not article_blocks:
                logging.info("더 이상 게시물이 없습니다. 종료.")
                break

            for block in article_blocks:
                try:
                    a_tag = block.select_one('a.list-link')

                    if not a_tag:
                        continue

                    post_url = a_tag['href']
                    post_url = f"https://www.kbdio.com{post_url}"

                    info = block.select_one('div.list-info')
                    title = info.select_one('h1.list-subject').get_text(strip=True)
                    date_str = info.select('div.list-meta > span')[-1].get_text(strip=True)
                    post_date = datetime.strptime(date_str, '%Y. %m. %d.').date()

                    if post_date > end_date:
                        continue
                    if post_date < start_date:
                        stop_flag = True
                        break
                    logging.info(f"상세 페이지 진입 시도: {post_url}")
                    kbdio_crw(wd_dp1, post_url, valid_domains,final_file)

                except Exception as e:
                    logging.error(f"게시글 처리 오류: {e}")
                    continue

            if stop_flag:
                logging.info("시작 날짜 이전 글 도달 → 종료")
                break

            # 페이지 이동 가능 여부 확인
            next_page = soup.select_one(f'a[href="/?page={page_num + 1}"]')
            if not next_page:
                logging.info("다음 페이지 없음 → 종료")
                break

            page_num += 1

        except Exception as e:
            logging.error(f"[페이지 {page_num}] 오류: {e}")
            break

    wd.quit()
    wd_dp1.quit()

    csv_to_excel(final_file)

