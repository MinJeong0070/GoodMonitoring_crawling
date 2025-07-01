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

from src.crawler.setup import setup_driver, save_to_csv, clean_title,result_csv_data

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

# 로그 설정
logging.basicConfig(
    filename=f'보배드림_log_{today}.txt',
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)


# 한페이지 크롤링
def bobaedream_crw(wd, url, search):
    try:
        logging.info(f"크롤링 시작: {url}")
        wd.set_page_load_timeout(10)
        wd.get(f'{url}')
        logging.info(f"접속: {url}")
        time.sleep(1)
        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'content02')))
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

        content_div = soup.find('div', class_='bodyCont').get_text().strip()

        raw_title = soup.find('div', class_='writerProfile').find('dt').get('title')
        cleaned_title = clean_title(raw_title)  # 제목 정리 함수 사용
        title_list.append(cleaned_title)
        logging.info(f"제목 추출 성공: {cleaned_title}")

        content_tag = soup.find('div', class_='bodyCont')
        content_text = content_tag.get_text(separator=' ', strip=True)

        # URL 제거
        content_cleaned = re.sub(r'https?://[^\s]+', '', content_text).strip()

        content_list.append(content_cleaned)
        logging.info("내용 추출 성공")

        search_plt_list.append('웹페이지(보배드림)')
        url_list.append(url)

        search_word_list.append(search)

        date_str_tag = soup.find('div', class_='writerProfile').find('span', class_='countGroup').text
        date_str = re.search(r'\d{4}\.\d{2}\.\d{2}', date_str_tag).group()
        date = datetime.strptime(date_str, '%Y.%m.%d')
        date_list.append(date)
        logging.info(f"날짜 추출 성공: {date_str}")

        # 채널명
        writer_list.append(
            soup.find('dd', class_='proflieInfo').find_all('li')[0].find('span', class_='proCont').get_text().lstrip())
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
        save_to_csv(main_temp, f'../csv/8.보배드림/{today}/보배드림_{search}.csv')
        logging.info(f'csv/보배드림/{today}/보배드림_{search}.csv')

    except TimeoutException as e:
        logging.error(f"페이지 로딩 시간 초과: {e}")
        return None

    except WebDriverException as e:
        logging.error(f"웹드라이버 에러: {e}")
        return None

    except Exception as e:
        logging.error(f"오류 발생: {e}")
        return None


def bobaedream_main_crw(searchs, start_date, end_date):
    if not os.path.exists(f'../csv/8.보배드림/{today}'):
        os.makedirs(f'../csv/8.보배드림/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")
    logging.info(f"========================================================")
    logging.info(f"                    보배드림 크롤링 시작")
    logging.info(f"========================================================")
    wd = setup_driver()
    wd_dp1 = setup_driver()

    for search in searchs:
        # page_num = 1

        while True:
            try:
                logging.info(f"크롤링 시작-검색어: {search}")

                wd_dp1.get('https://www.bobaedream.co.kr')
                WebDriverWait(wd_dp1, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'gnb-container')))
                time.sleep(1)
                # soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                try:
                    # 검색클릭
                    search_button = wd_dp1.find_element(By.CSS_SELECTOR, "button.square-util.btn-search.js-btn-srch")
                    search_button.click()
                    # 검색어 입력
                    keyword_input = wd_dp1.find_element(By.ID, "keyword")
                    keyword_input.send_keys(search)
                    logging.info(f"검색어 {search} 입력")
                    # 검색
                    submit_button = wd_dp1.find_element(By.CSS_SELECTOR, "button.btn-submit")
                    submit_button.click()
                    logging.info(f"검색 엔터")
                except Exception as e:
                    logging.error(f"검색 실패: {e}")

                time.sleep(1)

                # 커뮤니티 클릭
                community_btn = wd_dp1.find_element(By.XPATH, "//div[@class='lnb']//a[contains(text(), '커뮤니티')]")
                community_btn.click()
                logging.info(f"커뮤니티 클릭")
                time.sleep(1)
                # 새로 파싱
                WebDriverWait(wd_dp1, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'search_Community')))
                soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                # 검색결과 리스트
                li_tags = soup_dp1.find('div', class_='search_Community').find_all('li')
                logging.info(f"검색목록 찾음.")
                while True:

                    for li in li_tags:

                        after_start_date = False  # 날짜가 시작 날짜 이후인 경우

                        try:
                            date_str = li.find('dd', class_='path').find_all('span', class_='next')[1].text
                            date_str = '20' + date_str
                            date = datetime.strptime(date_str, '%Y. %m. %d').date()
                            logging.info(f"날짜 찾음 : {date}")
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
                        url = 'https://www.bobaedream.co.kr' + li.find('dt').find('a').get('href')
                        logging.info(f"url 찾음.")
                        bobaedream_crw(wd, url, search)

                    if after_start_date:
                        break
                    else:
                        # 페이지 수 증가
                        try:
                            wd_dp1.find_element(By.CSS_SELECTOR, "a.next").click()
                            time.sleep(1)  # 페이지 로딩 시간 대기
                            WebDriverWait(wd_dp1, 10).until(
                                EC.presence_of_element_located((By.CLASS_NAME, 'search_Community')))

                            # **새로 페이지 로딩 후 다시 파싱**
                            soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')
                            li_tags = soup_dp1.find('div', class_='search_Community').find_all('li')  # 새로운 페이지의 목록 불러오기
                            logging.info("다음 페이지로 이동 및 파싱 완료")

                        except Exception as e:
                            logging.error(f"페이징 오류 발생: {e}")
                            break

            except Exception as e:
                print(f"오류 발생: {e}")
                logging.error(f"오류 발생: {e}")
                break

            if date > end_date:
                continue

            if date < start_date:
                after_start_date = True
                logging.info("루프종료")
                break
    wd.quit()
    wd_dp1.quit()

    result_dir = '../결과/보배드림'
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)

    all_data = pd.concat([
        result_csv_data(search, platform='보배드림', subdir='8.보배드림')
        for search in searchs
    ])
    print(all_data.count())

    all_data.to_csv(f'{result_dir}/보배드림_raw data_{today}.csv', encoding='utf-8', index=False)

