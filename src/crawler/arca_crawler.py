import os
import re
import time
import logging
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from datetime import datetime

from src.crawler.setup import setup_driver, save_to_csv, clean_title

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

logging.basicConfig(
    filename=f'아카라이브_log_{today}.txt',
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)


def arca_crw(wd, url, search):
    try:
        logging.info(f"크롤링 시작: {url}")
        wd.set_page_load_timeout(10)
        wd.get(f'{url}')
        logging.info(f"접속: {url}")
        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'article-body')))
        time.sleep(1)
        soup = BeautifulSoup(wd.page_source, 'html.parser')

        # 추후 수정하기
        search_word_list = []
        search_plt_list = []
        writer_list = []
        url_list = []
        title_list = []
        content_list = []
        date_list = []
        current_date_list = []
        image_check_list = []

        div_tag = soup.find('div', class_='title')

        for span in div_tag.find_all('span'):
            span.extract()

        content_div = soup.find('div', class_='article-body')
        raw_title = div_tag.text
        cleaned_title = clean_title(raw_title)  # 제목 정리 함수 사용
        title_list.append(cleaned_title)
        logging.info(f"제목 추출 성공: {cleaned_title}")

        # 1. 기사 포함 내용
        # content_tag = soup.find('div', class_='article-body')
        # if content_tag:
        #     content_strip = ' '.join(content_tag.text.split())
        #     content_list.append(content_strip)
        # else:
        #     content_list.append('')
        # logging.info("내용 추출 성공")

        # 기사 제외
        for scrap_box in content_div.find_all('div', class_='scrap_bx'):
            scrap_box.decompose()

        # 본문 추출 (띄어쓰기 유지)
        post_content = content_div.get_text(separator=' ', strip=True)

        # URL 제거
        post_content_cleaned = re.sub(r'https?://[^\s]+', '', post_content).strip()

        # 최종 저장
        content_list.append(post_content_cleaned)
        logging.info("내용 추출 성공 (URL 제거됨)")

        search_plt_list.append('웹페이지(아카라이브)')
        url_list.append(url)

        search_word_list.append(search)

        date_str = soup.find('div', class_='info-row').find('time').get_text()
        date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        date_list.append(date)
        logging.info(f"날짜 추출 성공: {date_str}")

        # 채널명
        writer_list.append(soup.find('div', class_='info-row').find('span', class_='user-info').find('a').get_text())
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
            "수집시간": current_date_list
        })

        # 데이터 저장
        save_to_csv(main_temp, f'../csv/9.아카라이브/{today}/아카라이브_{search}.csv')
        logging.info(f'csv/{today}/9.아카라이브_{search}.csv')

    except TimeoutException as e:
        logging.error(f"페이지 로딩 시간 초과: {e}")
        return None

    except WebDriverException as e:
        logging.error(f"웹드라이버 에러: {e}")
        return None

    except Exception as e:
        logging.error(f"오류 발생: {e}")
        return None


def arca_main_crw(searchs, start_date, end_date):
    if not os.path.exists(f'../csv/9.아카라이브/{today}'):
        os.makedirs(f'../csv/9.아카라이브/{today}')
        print(f"폴더 생성 완료: {today}")

    logging.info(f"========================================================")
    logging.info(f"                   아카라이브 크롤링 시작")
    logging.info(f"========================================================")
    wd = setup_driver()
    wd_dp1 = setup_driver()
    for search in searchs:
        page_num = 1
        time.sleep(10)
        while True:
            try:
                logging.info(f"크롤링 시작-검색어: {search}")
                url = f'https://arca.live/b/breaking?keyword={search}&p={page_num}'
                wd_dp1.get(url)
                WebDriverWait(wd_dp1, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'article-list')))

                time.sleep(1)

                soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                # 검색결과 리스트
                tr_tags = soup_dp1.find('div', class_='list-table table').find_all('a', class_='vrow column')
                logging.info(f"검색목록 찾음.")

                if not tr_tags:
                    break

                for tr in tr_tags:

                    after_start_date = False  # 날짜가 시작 날짜 이후인 경우
                    try:
                        date_str = tr.find('span', class_='vcol col-time').find('time').text
                        date = datetime.strptime(date_str, '%Y.%m.%d').date()
                        logging.info(f"날짜 찾음")
                    except Exception as e:
                        logging.error(f"날짜 오류 발생: {e}")
                        continue
                    if date > end_date:
                        # date_flag = True
                        continue
                    if date < start_date:
                        after_start_date = True
                        break

                    # if date.day <= 7:
                    date_flag = True
                    url = 'https://arca.live' + tr.get('href')
                    logging.info(f"url 찾음.")
                    arca_crw(wd, url, search)

                if after_start_date:
                    break
                else:
                    page_num += 1

            except Exception as e:
                print(f"오류 발생: {e}")
                logging.error(f"오류 발생: {e}")
                break
    wd.quit()
    wd_dp1.quit()