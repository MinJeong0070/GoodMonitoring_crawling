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
    filename=f'DVD프라임_log_{today}.txt',
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)

# 한페이지 크롤링
def dp_crw(wd, url, search):
    try:
        logging.info(f"크롤링 시작: {url}")
        wd.set_page_load_timeout(10)
        wd.get(f'{url}')
        logging.info(f"접속: {url}")
        time.sleep(1)
        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.ID, 'resContents')))
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

        content_div = soup.find('div', id='resContents')
        title_tags = soup.find_all('h1', id='writeSubject')
        for title_tag in title_tags:  # title_tags는 BeautifulSoup으로 찾은 태그 목록이라고 가정
            for span in title_tag.find_all('span'):
                span.extract()

            # 제목 텍스트를 가져오고 정리
            raw_title = title_tag.get_text(strip=True)
            cleaned_title = clean_title(raw_title)
            title_list.append(cleaned_title)

            logging.info(f"제목 추출 성공: {cleaned_title}")

        # content = soup.find('div', id='resContents').text.strip()
        # content_strip = ' '.join(content.split())
        # content_list.append(content_strip)

        # logging.info("내용 추출 성공")

        # 2. 기사제거
        # 모든 <a> 태그 제거 (기사, 유튜브 등 링크 제거)
        for a_tag in content_div.find_all('a'):
            a_tag.decompose()

        # URL 형태의 텍스트 제거 (http:// 또는 https://로 시작하는 모든 링크)
        post_content = content_div.get_text(separator='\n', strip=True)
        post_content = re.sub(r'http[s]?://\S+', '', post_content)

        # 여러 줄바꿈과 공백 정리
        post_content = content_div.get_text(separator=' ', strip=True)
        post_content = re.sub(r'https?://[^\s]+', '', post_content)

        # 게시글 내용 추가
        content_list.append(post_content)
        logging.info(f"내용 추출 성공: {post_content}")

        search_plt_list.append('웹페이지(DVD프라임)')
        url_list.append(url)

        search_word_list.append(search)

        date_str = soup.find('div', id='view_datetime').get_text(strip=True).split(' ')[2]
        date = datetime.strptime(date_str, '%Y-%m-%d')
        date_list.append(date)
        logging.info(f"날짜 추출 성공: {date_str}")

        # 채널명
        writer_list.append(soup.find('span', class_='member').get_text(strip=True))

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
            "수집시간": current_date_list,
            "이미지 유무": image_check_list
        })

        # 데이터 저장
        save_to_csv(main_temp, f'../csv/15.DVD프라임/{today}/DVD프라임_{search}.csv')
        logging.info(f'csv/15.DVD프라임/{today}/DVD프라임_{search}.csv')

    except TimeoutException as e:
        logging.error(f"페이지 로딩 시간 초과: {e}")
        return None

    except WebDriverException as e:
        logging.error(f"웹드라이버 에러: {e}")
        return None

    except Exception as e:
        logging.error(f"오류 발생: {e}")
        return None



def dp_main_crw(searchs, start_date, end_date):
    if not os.path.exists(f'../csv/15.DVD프라임/{today}'):
        os.makedirs(f'../csv/15.DVD프라임/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")
    logging.info(f"========================================================")
    logging.info(f"                    DVD프라임 크롤링 시작")
    logging.info(f"========================================================")
    wd = setup_driver()
    wd_dp1 = setup_driver()

    category = ['sisa', 'comm', 'humor']  # bo_table=comm
    for cate in category:
        page_num = 1
        for search in searchs:
            page_num = 1
            while True:
                try:
                    logging.info(f"크롤링 시작-검색어: {search}")
                    logging.info(f"크롤링 카테고리: {cate}")
                    url = f'https://dprime.kr/g2/bbs/board.php?bo_table={cate}&sca=&sfl=wr_subject%7C%7Cwr_content&stx={search}&sop=and&page={page_num}'
                    # url = f'https://dprime.kr/g2/bbs/board.php?bo_table={cate}&sca=&sfl=wr_subject%7C%7Cwr_content&stx={search}&sop=and&scrap_mode=&page={page_num}'

                    wd_dp1.get(url)
                    WebDriverWait(wd_dp1, 10).until(EC.presence_of_element_located((By.ID, 'list_table')))
                    time.sleep(1)

                    soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                    # 검색결과 리스트
                    div_tags = soup_dp1.find('div', id='list_table').find_all('div', attrs={
                        'class': ['relative', 'list_table_row']})
                    logging.info(f"검색목록 찾음.")

                    for div in div_tags:

                        after_start_date = False  # 날짜가 시작 날짜 이후인 경우
                        # 공지사항 글 발견시 continue
                        # notice_tag = div.find('span', class_=' list_category_text category_color4').text
                        # if notice_tag == '공지':
                        #     logging.info(f"공지사항 글 발견")
                        #     continue

                        try:
                            date_str = '20' + div.find('span', class_='list_table_dates').text.strip()
                            date = datetime.strptime(date_str, '%Y-%m-%d').date()
                            logging.info(f"날짜 찾음")
                        except Exception as e:
                            logging.error(f"날짜 오류 발생: {e}")
                            continue

                        if date > end_date:
                            continue

                        if date < start_date:
                            after_start_date = True
                            break

                        # if date.day <= 7:

                        url = 'https://dprime.kr' + div.find('a', class_='list_subject_a').get('href')
                        logging.info(f"url 찾음.")

                        dp_crw(wd, url, search)

                    if after_start_date:
                        break

                except Exception as e:
                    print(f"오류 발생: {e}")
                    logging.error(f"오류 발생: {e}")
                    break

                page_num += 1

                page_list = []
                max_page = 1
                page_tags = soup_dp1.find_all('li', class_='paging_num_li smalleng theme_key2')
                if page_tags:
                    for page in page_tags:
                        page_list.append(int(page.find('a').text))
                        max_page = max(page_list)
                        logging.info(f'최대 페이지 수 : {max_page}')

                elif after_start_date:
                    break

                elif not page_tags or page_num > max_page:

                    try:
                        # more_search_btn = wd_dp1.find_element(By.CSS_SELECTOR, "li.paging_num_li.smalleng.help a")
                        more_search_btn = EC.presence_of_element_located(By.XPATH, "//a[contains(., '더 검색')]")
                        more_search_btn.click()
                        logging.info("'더 검색' 버튼 클릭")

                        WebDriverWait(wd_dp1, 10).until(EC.presence_of_element_located((By.ID, 'list_table')))
                        time.sleep(1)

                        soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                        # 검사
                        div_tags = soup_dp1.find('div', class_='relative list_table_row')
                        if not div_tags:
                            logging.info(f"검색결과 없음 break")
                            break
                        # no_result = soup_dp1.find('div', class_='list_no_articles')
                        if page_tags:
                            page_num = 1
                    except Exception as e:
                        logging.error(f"'더 검색' 버튼 클릭 오류: {e}")
                        break
    wd.quit()
    wd_dp1.quit()

