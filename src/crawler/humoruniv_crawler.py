import os
import re
import random
import time
import logging
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from dateutil.relativedelta import relativedelta
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from datetime import datetime, timedelta

from src.crawler.setup import setup_driver, save_to_csv, clean_title

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

# 로그 설정
logging.basicConfig(
    filename=f'웃긴대학_log_{today}.txt',  # 로그 파일 이름
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)


def humoruniv_crw(wd, url, search):
    try:
        logging.info(f"크롤링 시작: {url}")
        wd.set_page_load_timeout(10)
        wd.get(f'{url}')
        logging.info(f"접속: {url}")
        time.sleep(1)
        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.ID, 'cnts')))
        soup = BeautifulSoup(wd.page_source, 'html.parser')

        search_word_list = []
        search_plt_list = []
        writer_list = []
        url_list = []
        title_list = []
        content_list = []
        date_list = []
        current_date_list = []
        image_check_list = []

        content_div = soup.find('div', id='cnts')
        tb = soup.find('table', id='profile_table').find('table')
        raw_title = tb.find('span', id='ai_cm_title').get_text()
        cleaned_title = clean_title(raw_title)  # 제목 정리 함수 사용
        title_list.append(cleaned_title)
        logging.info(f"제목 추출 성공: {cleaned_title}")

        # content =  soup.find('div', id='cnts').get_text().strip()
        # content_strip = ' '.join(content.split())
        # content_list.append(content_strip)
        # logging.info("내용 추출 성공")

        # 2. 기사제거
        # <a> 태그 제거 (링크 제거 목적)
        for a_tag in content_div.find_all('a'):
            a_tag.decompose()

        # 본문 텍스트 추출 (띄어쓰기 유지)
        post_content = content_div.get_text(separator=' ', strip=True)

        # URL 제거 (텍스트 내 포함된 http/https 링크)
        post_content_cleaned = re.sub(r'https?://[^\s]+', '', post_content)

        # 최종 저장
        content_list.append(post_content_cleaned)
        logging.info("내용 추출 성공 (URL 제거 및 띄어쓰기 유지)")

        search_plt_list.append('웹페이지(웃긴대학)')
        url_list.append(url)

        search_word_list.append(search)

        date_str = tb.find('div', id='content_info').find_all('span')[5].get_text().strip().split(' ')[0]
        logging.info(f"날짜 추출: {date_str}")
        date = datetime.strptime(date_str, '%Y-%m-%d')
        date_list.append(date)
        logging.info(f"날짜 추출 성공: {date_str}")

        # 채널명
        writer_list.append(tb.find('span', class_='hu_nick_txt').get_text())

        current_date_list.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        # 이미지/비디오/유튜브 유무 확인
        try:
            # 1. scrap_img로 표시된 background-image 확인
            bg_images = content_div.find_all('span', class_='scrap_img')

            # 2. 일반 이미지 (img 태그) 확인
            images = content_div.find_all('img')

            # 3. 비디오 확인 (video 태그)
            videos = content_div.find_all('video')

            # 4. 유튜브 영상 확인 (iframe 태그의 youtube.com 포함 여부)
            iframes = content_div.find_all('iframe')
            youtube_videos = [iframe for iframe in iframes if iframe.get('src') and 'youtube.com' in iframe['src']]

            # 5. 하이퍼링크로 포함된 모든 URL
            article_links = content_div.find_all('a', href=True)
            link_urls = [
                a['href'] for a in article_links if 'http' in a['href']
            ]

            # 6. 텍스트 안에 포함된 URL 찾기 (일반 텍스트 URL 감지)
            text_content = content_div.get_text()
            text_urls = re.findall(r'(https?://[^\s]+)', text_content)

            # 이미지, 비디오, 유튜브 영상이 하나라도 있으면 'O', 없으면 ' '
            if bg_images or images or videos or youtube_videos or link_urls or text_urls:
                image_check_list.append('O')
            else:
                image_check_list.append(' ')
                logging.info(f'이미지 없음: {url}')
        except Exception as e:
            logging.error(f"미디어 확인 오류: {e}")
            image_check_list.append(' ')

        main_temp = pd.DataFrame({

            "검색어": search_word_list,
            "플랫폼": search_plt_list,
            "게시물 URL": url_list,
            "게시물 제목": title_list,
            "게시물 내용": content_list,
            "게시물 등록일자": date_list,
            "계정명": writer_list,
            # "수집시간" : current_date_list
            "이미지 유무": image_check_list
        })

        # 데이터 저장
        save_to_csv(main_temp, f'../csv/11.웃긴대학/{today}/웃긴대학_{search}.csv')
        logging.info(f"저장완료: csv/11.웃긴대학/{today}/웃긴대학_{search}.csv")

    except Exception as e:
        logging.error(f"오류 발생: {e}")
        return pd.DataFrame()


def humoruniv_main_crw(searchs, start_date, end_date):
    if not os.path.exists(f'../csv/11.웃긴대학/{today}'):
        os.makedirs(f'../csv/11.웃긴대학/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")
    logging.info(f"========================================================")
    logging.info(f"                    웃긴대학 크롤링 시작")
    logging.info(f"========================================================")
    wd = setup_driver()
    wd_dp1 = setup_driver()
    for search in searchs:
        while True:
            try:
                logging.info(f"크롤링 시작-검색어: {search}")

                url = f'https://web.humoruniv.com/main.html'
                wd_dp1.get(url)
                WebDriverWait(wd_dp1, 10).until(EC.presence_of_element_located((By.ID, 'wrap_sch')))
                time.sleep(1)
                # soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                # 검색하기
                try:
                    keyword_input_frm = wd_dp1.find_element(By.ID, 'search_text')
                    keyword_input_frm.click()
                    # 검색어 입력
                    keyword_input = wd_dp1.find_element(By.ID, 'search_text')
                    keyword_input.send_keys(search)
                    logging.info(f"검색어 {search} 입력")
                    # 검색
                    submit_button = wd_dp1.find_element(By.XPATH, '//input[@alt="검색"]')
                    submit_button.click()
                    logging.info(f"검색 엔터")
                except Exception as e:
                    logging.error(f"검색 실패: {e}")
                time.sleep(3)

                soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                date_flag = False
                after_start_date = False  # 날짜가 시작 날짜 이후인 경우

                # 검색결과 리스트
                tables = soup_dp1.find_all('table', {
                    'width': '100%',
                    'border': '0',
                    'cellspacing': '0',
                    'cellpadding': '5',
                    'bordercolor': '#666666',
                    'style': 'border-collapse:collapse;'
                })
                logging.info(f"검색목록 찾음.")
                while True:

                    for tb in tables:

                        after_start_date = False  # 날짜가 시작 날짜 이후인 경우
                        date_flag = False

                        date_str = tb.find('font', class_='gray').text.split(' ')[0]
                        date = datetime.strptime(date_str, '%Y-%m-%d').date()

                        if date > start_date:
                            after_start_date = True

                        if start_date <= date <= end_date:
                            date_flag = True
                            url = 'https:' + tb.find('a').get('href')
                            logging.info(f"url 찾음.")

                            humoruniv_crw(wd, url, search)

                    # 시작 날짜 이후의 게시글이 없고 기간 내 게시글도 없으면 종료
                    if not after_start_date and not date_flag:
                        logging.info("루프종료")
                        break

                        # 페이지 수 증가
                    try:
                        wd_dp1.find_element(By.CSS_SELECTOR, "def arrow").click()
                        time.sleep(3)  # 페이지 로딩 시간 대기

                        # **새로 페이지 로딩 후 다시 파싱**
                        soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')
                        tables = soup_dp1.find_all('table', {
                            'width': '100%',
                            'border': '0',
                            'cellspacing': '0',
                            'cellpadding': '5',
                            'bordercolor': '#666666',
                            'style': 'border-collapse:collapse;'
                        })
                        logging.info("다음 페이지로 이동 및 파싱 완료")

                    except Exception as e:
                        logging.error(f"페이징 오류 발생: {e}")
                        break

            except Exception as e:
                print(f"오류 발생: {e}")
                logging.error(f"오류 발생: {e}")
                break

            if not after_start_date and not date_flag:
                logging.info("루프종료")
                break

    wd.quit()
    wd_dp1.quit()