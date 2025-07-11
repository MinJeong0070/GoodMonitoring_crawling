import os
import re
import time
import logging
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from datetime import datetime

from src.etc.utils import setup_driver, save_to_csv, clean_title,result_csv_data

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

logging.basicConfig(
    filename=f'포모스_log_{today}.txt',  # 로그 파일 이름
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)


def fomos_crw(wd, url, search):
    try:
        logging.info(f"크롤링 시작: {url}")
        wd.set_page_load_timeout(10)
        wd.get(f'{url}')
        logging.info(f"접속: {url}")
        time.sleep(1)
        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'view_area')))
        soup = BeautifulSoup(wd.page_source, 'html.parser')

        search_word_list = []
        search_plt_list = []
        writer_list = []
        url_list = []
        title_list = []
        content_list = []
        date_list = []
        image_check_list = []

        content_div = soup.find('div', class_='view_text')

        raw_title = soup.find('div', class_='board_area common_view').find('h3').get_text()
        cleaned_title = clean_title(raw_title)  # 제목 정리 함수 사용
        title_list.append(cleaned_title)
        logging.info(f"제목 추출 성공: {cleaned_title}")

        # <a> 태그 중 이미지가 없는 경우에만 삭제
        for a_tag in content_div.find_all('a'):
            if (
                    not a_tag.find('img') and
                    not a_tag.find('span', class_='scrap_img') and
                    not a_tag.find('video') and
                    not (a_tag.find('iframe') and 'youtube.com' in a_tag.decode_contents())
            ):
                a_tag.decompose()

        # URL 형태의 텍스트 제거 (http:// 또는 https://로 시작하는 모든 링크)
        post_content = content_div.get_text(separator='\n', strip=True)
        post_content = re.sub(r'http[s]?://\S+', '', post_content)

        # 본문 텍스트 추출 (줄바꿈 유지), URL 제거
        post_content = content_div.get_text(separator='\n', strip=True)
        post_content = re.sub(r'https?://\S+', '', post_content)
        post_content = re.sub(r'\n{2,}', '\n', post_content).strip()

        content_list.append(post_content)
        logging.info(f"내용 추출 성공: {post_content}")

        search_plt_list.append('웹페이지(포모스)')
        url_list.append(url)

        search_word_list.append(search)

        date_str = soup.find('p', class_='sub_tit').find_all('span')[1].text.split(' ')[0]

        date = datetime.strptime(date_str, '%Y-%m-%d')
        date_list.append(date)
        logging.info(f"날짜 추출 성공: {date_str}")

        # 채널명
        writer_list.append(soup.find('p', class_='sub_tit').find_all('span')[0].text)

        # # 이미지/비디오/유튜브 유무 확인
        # try:
        #     # 1. scrap_img로 표시된 background-image 확인
        #     bg_images = content_div.find_all('span', class_='scrap_img')
        #
        #     # 2. 일반 이미지 (img 태그) 확인
        #     images = content_div.find_all('img')
        #
        #     # 3. 비디오 확인 (video 태그)
        #     videos = content_div.find_all('video')
        #
        #     # 4. 유튜브 영상 확인 (iframe 태그의 youtube.com 포함 여부)
        #     iframes = content_div.find_all('iframe')
        #     youtube_videos = [iframe for iframe in iframes if iframe.get('src') and 'youtube.com' in iframe['src']]
        #
        #     # 5. 하이퍼링크로 포함된 모든 URL
        #     article_links = content_div.find_all('a', href=True)
        #     link_urls = [
        #         a['href'] for a in article_links if 'http' in a['href']
        #     ]
        #
        #     # 6. 텍스트 안에 포함된 URL 찾기 (일반 텍스트 URL 감지)
        #     text_content = content_div.get_text()
        #     text_urls = re.findall(r'(https?:\/\/[^\s]+|https?:)', text_content)
        #
        #     # 이미지, 비디오, 유튜브 영상이 하나라도 있으면 'O', 없으면 ' '
        #     if bg_images or images or videos or youtube_videos or link_urls or text_urls:
        #         image_check_list.append('O')
        #     else:
        #         image_check_list.append(' ')
        #         logging.info(f'이미지 없음: {url}')
        # except Exception as e:
        #     logging.error(f"미디어 확인 오류: {e}")
        #     image_check_list.append(' ')

        main_temp = pd.DataFrame({

            "검색어": search_word_list,
            "플랫폼": search_plt_list,
            "게시물 URL": url_list,
            "게시물 제목": title_list,
            "게시물 내용": content_list,
            "게시물 등록일자": date_list,
            "계정명": writer_list,
            # "이미지 유무": image_check_list
        })

        # 데이터 저장
        save_to_csv(main_temp, f'../csv/18.포모스/{today}/포모스_{search}.csv')
        logging.info(f'csv/18.포모스/{today}/포모스_{search}.csv')

    except Exception as e:
        logging.error(f"오류 발생: {e}")
        return pd.DataFrame()


def fomos_main_crw(searchs, start_date, end_date):
    if not os.path.exists(f'../csv/18.포모스/{today}'):
        os.makedirs(f'../csv/18.포모스/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")
    logging.info(f"========================================================")
    logging.info(f"                    포모스 크롤링 시작")
    logging.info(f"========================================================")
    wd = setup_driver()
    wd_dp1 = setup_driver()
    # wd_dp1 = setup_driver()
    for search in searchs:
        page_num = 1

        while True:
            try:
                logging.info(f"크롤링 시작-검색어: {search}")
                url = f'https://www.fomos.kr/search/list?menu=talk&fword={search}&page={page_num}'

                wd_dp1.get(url)

                WebDriverWait(wd_dp1, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'result_section.r_esports')))
                time.sleep(2)
                soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                # 검색결과 리스트
                li_tags = soup_dp1.find('ul', class_='webzine').find_all('li')
                logging.info(f"검색목록 찾음.")
                if not li_tags:
                    break

                for li in li_tags:
                    url_str = li.find('p', class_='tit').find('a').get('href')
                    url = 'https://www.fomos.kr' + url_str
                    logging.info(f"url 찾음.")
                    fomos_crw(wd, url, search)

            except Exception as e:
                logging.error(f"오류 발생: {e}")
                break

            page_num += 1  # 페이지 수 증가

            if page_num == 15:
                break
    wd.quit()
    wd_dp1.quit()

    result_dir = '../결과/포모스'
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)

    all_data = pd.concat([
        result_csv_data(search, platform='포모스', subdir='18.포모스')
        for search in searchs
    ])

    all_data.to_csv(f'{result_dir}/포모스_raw data_{today}.csv', encoding='utf-8', index=False)
