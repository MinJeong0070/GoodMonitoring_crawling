import os
import re
import time
import random
import logging
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime

from src.crawler.setup import setup_driver, save_to_csv, clean_title,result_csv_data

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

logging.basicConfig(
    filename=f'에펨코리아_log_{today}.txt',  # 로그 파일 이름
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)


# 한페이지 크롤링
def fm_crw(wd, url, search):
    try:
        wd.get(f'{url}')
        sleep_random_time = random.uniform(2, 4)
        time.sleep(sleep_random_time)
        soup = BeautifulSoup(wd.page_source, 'html.parser')

        writer_list = []
        title_list = []
        content_list = []
        url_list = []
        search_plt_list = []
        search_word_list = []
        date_list = []
        image_check_list = []

        content_div = soup.find('article')

        raw_title = soup.find('span', class_='np_18px_span').get_text()
        cleaned_title = clean_title(raw_title)  # 제목 정리 함수 사용
        title_list.append(cleaned_title)
        logging.info(f"제목 추출 성공: {cleaned_title}")

        # content = soup.find('article').text.strip()
        # content_strip = ' '.join(content.split())
        # content_list.append(content_strip)

        # <a> 태그 중 이미지가 없는 경우에만 삭제
        for a_tag in content_div.find_all('a'):
            if (
                    not a_tag.find('img') and
                    not a_tag.find('span', class_='scrap_img') and
                    not a_tag.find('video') and
                    not (a_tag.find('iframe') and 'youtube.com' in a_tag.decode_contents())
            ):
                a_tag.decompose()

        post_content = content_div.get_text(separator='\n', strip=True)
        post_content = re.sub(r'http[s]?://\S+', '', post_content)
        content_list.append(post_content)
        logging.info(f"내용 추출 성공: {post_content}")

        search_plt_list.append('웹페이지(에펨코리아)')
        url_list.append(url)

        search_word_list.append(search)

        date_list.append(soup.find('span', class_="date m_no").text.split()[0])

        writer_list.append(soup.find('a', class_=re.compile(r'^member_\d+')).get_text())

        # # 이미지/비디오/유튜브 유무 확인(현재는 사용하지않는 기능)
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
        save_to_csv(main_temp, f'../csv/23.에펨코리아/{today}/에펨코리아_{search}.csv')
        logging.info(f'저장완료 : csv/23.에펨코리아/{today}/에펨코리아_{search}.csv')

    except Exception as e:
        logging.error(f"오류 발생: {e}")
        return pd.DataFrame()


def fm_main_crw(searchs, start_date, end_date):
    if not os.path.exists(f'../csv/23.에펨코리아/{today}'):
        os.makedirs(f'../csv/23.에펨코리아/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")
    logging.info(f"========================================================")
    logging.info(f"                 에펨코리아 크롤링 시작")
    logging.info(f"========================================================")
    wd = setup_driver()
    wd_dp1 = setup_driver()

    for search in searchs:
        page_num = 1

        while True:
            try:
                url_dp1 = f'https://www.fmkorea.com/search.php?act=IS&is_keyword={search}&mid=home&where=document&page={page_num}'
                wd_dp1.get(url_dp1)
                sleep_random_time = random.uniform(2, 4)
                time.sleep(sleep_random_time)
                soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                # 검색결과 리스트
                li_tags = soup_dp1.find('ul', class_='searchResult').find_all('li')

                for li in li_tags:

                    after_start_date = False

                    try:
                        date_str = li.find('span', class_='time').text
                        date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except Exception as e:
                        logging.error("날짜 오류 발생: {e}")
                        continue

                    if date > end_date:
                        continue
                    if date < start_date:
                        after_start_date = True
                        break

                    url_dp2_num = li.find('a').get('href')
                    url = 'https://www.fmkorea.com' + url_dp2_num
                    logging.info(f"url 찾음.")
                    fm_crw(wd, url, search)

                if after_start_date:
                    break
                else:
                    page_num += 1

            except Exception as e:
                print(f"오류 발생: {e}")
                break
    wd.quit()
    wd_dp1.quit()

    result_dir = '../결과/에펨코리아'
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)

    all_data = pd.concat([
        result_csv_data(search, platform='에펨코리아', subdir='23.에펨코리아')
        for search in searchs
    ])

    all_data.to_csv(f'{result_dir}/에펨코리아_raw data_{today}.csv', encoding='utf-8', index=False)
