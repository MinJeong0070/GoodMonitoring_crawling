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

from src.crawler.setup import setup_driver, save_to_csv, clean_title

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

# 로그 설정
logging.basicConfig(
    filename=f'블라인드_log_{today}.txt',  # 로그 파일 이름
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)

def parse_blind_date(date_str, current_year=2025):
    from datetime import datetime, timedelta

    date_str = date_str.strip()
    date_str = date_str.replace("작성시간", "").replace("작성일", "").strip()
    if date_str.endswith('.'):
        date_str = date_str[:-1]  # 마지막 마침표 제거

    now = datetime.now()

    if '시간' in date_str:
        hours = int(date_str.replace('시간', '').strip())
        return (now - timedelta(hours=hours)).date()
    elif '일' in date_str:
        days = int(date_str.replace('일', '').strip())
        return (now - timedelta(days=days)).date()
    elif '주' in date_str:
        weeks = int(date_str.replace('주', '').strip())
        return (now - timedelta(weeks=weeks)).date()
    elif '달' in date_str:
        months = int(date_str.replace('달', '').strip())
        return (now - timedelta(days=months * 30)).date()

    elif date_str.count('.') == 1:
        # 월.일 형식
        try:
            month, day = date_str.split('.')
            return datetime.strptime(f"{current_year}-{month.zfill(2)}-{day.zfill(2)}", "%Y-%m-%d").date()
        except:
            return None

    elif date_str.count('.') == 2:
        # yyyy.MM.dd 형식
        try:
            return datetime.strptime(date_str, '%Y.%m.%d').date()
        except:
            return None

    return None  # 어떤 형식에도 안 맞으면 None 반환

def blind_crw(wd, url, search):
    try:
        logging.info(f"크롤링 시작: {url}")
        wd.set_page_load_timeout(10)
        wd.get(f'{url}')
        logging.info(f"접속: {url}")
        time.sleep(2)
        WebDriverWait(wd, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'contents')))
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

        content_div = soup.find('p', id='contentArea')

        raw_title = soup.find('div', class_='article-view-head').find('h2').text
        cleaned_title = clean_title(raw_title)  # 제목 정리 함수 사용
        title_list.append(cleaned_title)
        logging.info(f"제목 추출 성공: {cleaned_title}")

        # 1. 기사 포함
        # content = soup.find('p', id = 'contentArea').get_text()
        # content_strip = ' '.join(content.split())
        # content_list.append(content_strip)
        # logging.info("내용 추출 성공")

        # 2. 기사제거
        for a_tag in content_div.find_all('a'):
            if (
                    not a_tag.find('img') and
                    not a_tag.find('span', class_='scrap_img') and
                    not a_tag.find('video') and
                    not (a_tag.find('iframe') and 'youtube.com' in a_tag.decode_contents())
            ):
                a_tag.decompose()

        post_content = content_div.get_text(separator='\n', strip=True)
        post_content = re.sub(r'https?://\S+', '', post_content)
        content_list.append(post_content)
        logging.info(f"내용 추출 성공: {post_content}")

        search_plt_list.append('웹페이지(블라인드)')
        url_list.append(url)

        search_word_list.append(search)

        date_tag = soup.find('div', class_='wrap-info').find('span', class_='date').text.strip()
        date_only = date_tag.replace('작성일', '').strip()
        month, day = date_only.split('.')
        formatted_date = f"2024-{month.zfill(2)}-{day.zfill(2)}"
        date_list.append(formatted_date)
        logging.info(f"날짜 추출 성공: {formatted_date}")

        # 채널명
        writer = soup.find('div', class_='name').text.strip()
        writert_strip = ' '.join(writer.split())
        writer_list.append(writert_strip)

        # current_date_list.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
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
            "이미지 유무": image_check_list
            # "수집시간" : current_date_list
        })

        # 데이터 저장
        save_to_csv(main_temp, f'../csv/20.블라인드/{today}/블라인드_{search}.csv')
        logging.info(f"저장완료: csv/20.블라인드/{today}/블라인드_{search}.csv")

    except Exception as e:
        logging.error(f"오류 발생: {e}")
        return pd.DataFrame()


def blind_main_crw(searchs, start_date, end_date):
    if not os.path.exists(f'../csv/20.블라인드/{today}'):
        os.makedirs(f'../csv/20.블라인드/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")
    logging.info(f"========================================================")
    logging.info(f"                    블라인드 크롤링 시작")
    logging.info(f"========================================================")

    wd_dp1 = setup_driver()
    wd = setup_driver()
    wd_dp1.maximize_window()
    wd.maximize_window()

    current_year = 2025
    MAX_SCROLL_COUNT = 50

    for search in searchs:
        collected_urls = set()
        logging.info(f"[{search}] 크롤링 시작")

        search_url = f'https://www.teamblind.com/kr/search/"{search}"'
        wd_dp1.get(search_url)

        try:
            # 최신순 정렬 적용
            WebDriverWait(wd_dp1, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div.sort > select'))
            )
            time.sleep(1)
            wd_dp1.execute_script("""
                const select = document.querySelector('div.sort > select');
                if (select) {
                    select.value = 'id';
                    const event = new Event('change', { bubbles: true });
                    select.dispatchEvent(event);
                }
            """)
            logging.info(f"[{search}] 최신순 정렬 적용 완료")
            time.sleep(2)
        except Exception as e:
            logging.warning(f"[{search}] 최신순 정렬 실패: {e}")

        scroll_count = 0
        after_start_date = False

        while scroll_count < MAX_SCROLL_COUNT and not after_start_date:
            prev_height = wd_dp1.execute_script("return document.body.scrollHeight")
            time.sleep(2)

            soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')
            article_list_div = soup_dp1.find('div', class_='article-list')
            if not article_list_div:
                logging.warning(f"[{search}] article-list 요소 없음. 종료.")
                break

            div_tags = article_list_div.find_all('div', class_=re.compile(r'\barticle-list-pre\b'))
            if not div_tags:
                logging.info(f"[{search}] 더 이상 게시글 없음. 종료.")
                break

            for div in div_tags:
                info_div = div.find('div', class_='info_fnc')
                if not info_div:
                    logging.warning(f"[{search}] info_fnc 없음. 건너뜀.\n{div.prettify()}")
                    continue

                date_anchor = info_div.find('a', class_='past')
                if not date_anchor:
                    logging.warning(f"[{search}] 날짜 앵커 없음. 건너뜀.")
                    continue

                date_str = date_anchor.text.strip()
                parsed_date = parse_blind_date(date_str, current_year)
                if not parsed_date:
                    logging.warning(f"[{search}] 날짜 파싱 실패: {date_str}")
                    continue

                date_txt = parsed_date
                logging.info(f"[{search}] 날짜 찾음: {date_txt}")

                # 날짜 필터링
                if date_txt > end_date:
                    continue
                if date_txt < start_date:
                    after_start_date = True
                    logging.info(f"[{search}] 수집 범위 벗어남. 종료.")
                    break

                try:
                    post_url = div.find('div', class_='tit').find('h3').find('a')['href']
                    full_url = 'https://www.teamblind.com' + post_url
                except Exception as e:
                    logging.warning(f"[{search}] URL 추출 실패: {e}")
                    continue

                if full_url not in collected_urls:
                    collected_urls.add(full_url)
                    blind_crw(wd, full_url, search)

            # 스크롤 다운
            wd_dp1.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            current_height = wd_dp1.execute_script("return document.body.scrollHeight")

            if current_height == prev_height:
                logging.info(f"[{search}] 더 이상 스크롤 불가. 종료.")
                break

            scroll_count += 1
            logging.info(f"[{search}] 스크롤 {scroll_count}회 완료")

    wd.quit()
    wd_dp1.quit()
    logging.info("모든 검색어 크롤링 종료")
