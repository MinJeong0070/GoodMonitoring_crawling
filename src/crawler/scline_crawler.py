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

from src.etc.utils import setup_driver, save_to_csv, clean_title, result_csv_data

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'log'):
    os.makedirs(f'log')

logging.basicConfig(
    filename=f'사커라인_log_{today}.txt',
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)


def scline_crw(wd, url, search):
    """
    사커라인 상세 페이지 크롤러
    - renderer timeout( 'Timed out receiving message from renderer' ) 도 예외 처리하여
      콘솔에 긴 에러 스택이 찍히지 않도록 처리
    """
    try:
        logging.info(f"크롤링 시작: {url}")

        # 페이지 로드 타임아웃 살짝 여유 있게
        wd.set_page_load_timeout(20)

        try:
            wd.get(url)
        except TimeoutException as e:
            # 페이지 로드 타임아웃일 경우 현재까지 로드된 내용으로만 시도
            logging.warning(f"[상세] 페이지 로딩 시간 초과(TimeoutException) → 현재까지 로드된 소스로 진행: {url} / {e}")
        except WebDriverException as e:
            # renderer timeout 등 WebDriverException 처리
            if "Timed out receiving message from renderer" in str(e):
                logging.warning(f"[상세] renderer 타임아웃 발생, 해당 URL 스킵: {url} / {e}")
                return None
            logging.error(f"[상세] 웹드라이버 에러: {url} / {e}")
            return None

        logging.info(f"접속: {url}")

        WebDriverWait(wd, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'txtBox'))
        )
        time.sleep(2)
        soup = BeautifulSoup(wd.page_source, 'html.parser')

        # 추후 수정하기
        search_word_list = []
        search_plt_list = []
        writer_list = []
        url_list = []
        title_list = []
        content_list = []
        date_list = []
        image_check_list = []

        content_div = soup.find('div', class_='txtBox')
        if not content_div:
            logging.error(f"본문 영역(txtBox)을 찾지 못함: {url}")
            return None

        tit_box = soup.find('div', class_='titBox')
        if not tit_box:
            logging.error(f"제목 영역(titBox)을 찾지 못함: {url}")
            return None

        raw_title = tit_box.find('h2').get_text()
        cleaned_title = clean_title(raw_title)  # 제목 정리 함수 사용
        title_list.append(cleaned_title)
        logging.info(f"제목 추출 성공: {cleaned_title}")

        post_content = content_div.get_text(separator='\n', strip=True)
        post_content = re.sub(r'https?://\S+', '', post_content)
        post_content = re.sub(r'\n+', '\n', post_content).strip()

        content_list.append(post_content)
        logging.info(f"내용 추출 성공: {post_content}")

        search_plt_list.append('웹페이지(사커라인)')
        url_list.append(url)

        search_word_list.append(search)

        data_box = soup.find('div', class_='dataBox')
        if not data_box:
            logging.error(f"날짜 영역(dataBox)을 찾지 못함: {url}")
            return None

        date_tag = data_box.find_all('span')[0]
        date_match = re.search(r'\d{4}-\d{2}-\d{2}', date_tag.text)

        if date_match:
            date_str = date_match.group(0)
            date = datetime.strptime(date_str.split()[0], '%Y-%m-%d')
            date_list.append(date)
            logging.info(f"날짜 추출 성공: {date_str}")
        else:
            logging.error('날짜를 찾을 수 없음.')
            return None

        # 채널명
        name_box = soup.find('div', class_='nameBox')
        if name_box:
            writer_list.append(name_box.get_text())
        else:
            writer_list.append("")
            logging.warning(f"계정명(nameBox)을 찾지 못함: {url}")

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
        save_to_csv(main_temp, f'csv/16.사커라인/{today}/사커라인_{search}.csv')
        logging.info(f"csv/16.사커라인/{today}/사커라인_{search}.csv 저장 완료")

    except TimeoutException as e:
        logging.error(f"[상세] 페이지 로딩 시간 초과(outer): {url} / {e}")
        return None

    except WebDriverException as e:
        logging.error(f"[상세] 웹드라이버 에러(outer): {url} / {e}")
        return None

    except Exception as e:
        logging.error(f"[상세] 기타 오류 발생: {url} / {e}")
        return None


def scline_main_crw(searchs, start_date, end_date, stop_event):
    """
    사커라인 목록 페이지 순회 크롤러
    - 목록 페이지에서도 renderer timeout 에러를 잡아서
      크롤링이 중단되지 않고 다음 페이지/검색어로 넘어가도록 함
    """
    if not os.path.exists(f'csv/16.사커라인/{today}'):
        os.makedirs(f'csv/16.사커라인/{today}')
        print(f"폴더 생성 완료: {today}")
    else:
        print(f"해당 폴더 존재")

    logging.info(f"========================================================")
    logging.info(f"                    사커라인 크롤링 시작")
    logging.info(f"========================================================")

    wd = setup_driver()
    wd_dp1 = setup_driver()

    try:
        for search in searchs:
            if stop_event.is_set():
                print("🛑 크롤링 중단됨")
                break

            page_num = 0
            after_start_date = False
            no_search_flag = True

            while True:
                if stop_event.is_set():
                    break
                try:
                    logging.info(f"크롤링 시작-검색어: {search}, page={page_num}")
                    url = (
                        f'https://soccerline.kr/board?page={page_num}'
                        f'&categoryDepth01=0&searchWindow=&searchType=0&searchText={search}'
                    )

                    # 목록 페이지에도 타임아웃 설정
                    wd_dp1.set_page_load_timeout(20)
                    try:
                        wd_dp1.get(url)
                    except TimeoutException as e:
                        logging.warning(
                            f"[목록] 페이지 로딩 시간 초과(TimeoutException) → 현재까지 로드된 소스로 진행: {url} / {e}"
                        )
                    except WebDriverException as e:
                        if "Timed out receiving message from renderer" in str(e):
                            logging.warning(
                                f"[목록] renderer 타임아웃 발생, 해당 페이지 스킵: {url} / {e}"
                            )
                            # 이 페이지는 건너뛰고 다음 페이지로
                            page_num += 1
                            continue
                        logging.error(f"[목록] 웹드라이버 에러: {url} / {e}")
                        break

                    WebDriverWait(wd_dp1, 20).until(
                        EC.presence_of_element_located((By.CLASS_NAME, 'brdList'))
                    )
                    time.sleep(5)

                    soup_dp1 = BeautifulSoup(wd_dp1.page_source, 'html.parser')

                    # 검색결과 리스트
                    board_container = soup_dp1.find('div', id='boardListContainer')
                    if not board_container:
                        logging.info(f"[목록] 검색 결과 컨테이너 없음, 종료: {url}")
                        break

                    td_tags = board_container.find_all('tr')[2:]
                    logging.info(f"[목록] 검색목록 찾음 (행 수: {len(td_tags)})")
                    no_search_flag = False

                    if not td_tags:
                        break

                    for td in td_tags:  # td가 아니라 tr.
                        if stop_event.is_set():
                            break
                        after_start_date = False  # 날짜가 시작 날짜 이후인 경우

                        try:
                            date_str = td.find_all('td')[3].text.strip()
                            date = datetime.strptime(date_str, '%Y-%m-%d').date()
                            logging.info(f"[목록] 날짜 찾음: {date}")
                        except Exception as e:
                            logging.error(f"[목록] 날짜 파싱 오류 발생: {e}")
                            continue

                        if date > end_date:
                            # 지정 종료일 이후 글 → 계속 다음 글
                            continue

                        if date < start_date:
                            # 시작일보다 이전 글 → 이후 페이지는 더 과거이므로 중단
                            after_start_date = True
                            break

                        desc_td = td.find('td', class_='desc')
                        if not desc_td:
                            logging.warning("[목록] desc 컬럼을 찾지 못해 URL 추출 실패")
                            continue

                        a_tag = desc_td.find('a')
                        if not a_tag or not a_tag.get('href'):
                            logging.warning("[목록] a 태그/href 없음")
                            continue

                        detail_url = 'https://soccerline.kr' + a_tag.get('href')
                        logging.info(f"[목록] 상세 url 찾음: {detail_url}")
                        scline_crw(wd, detail_url, search)

                    if no_search_flag:
                        break

                    if len(td_tags) < 25:  # 게시물 25개 미만일시 break
                        logging.info("[목록] 현재 페이지 게시물 수가 25개 미만이므로 다음 페이지 없이 종료")
                        break

                    if after_start_date:
                        logging.info("[목록] 시작일 이전 데이터 도달로 크롤링 종료")
                        break
                    else:
                        page_num += 1

                except Exception as e:
                    # 여기서는 print 대신 logging만 사용해서 콘솔에 불필요한 에러 스택이 안 찍히도록
                    logging.error(f"[목록] 루프 내 기타 오류 발생: {e}")
                    break

    finally:
        # 드라이버 정리
        try:
            wd.quit()
        except Exception:
            pass
        try:
            wd_dp1.quit()
        except Exception:
            pass

    # 중단 없이 끝까지 돌았을 때만 결과 병합
    if not stop_event.is_set():
        result_dir = '결과/사커라인'
        if not os.path.exists(result_dir):
            os.makedirs(result_dir)

        all_data = pd.concat([
            result_csv_data(search, platform='사커라인', subdir='16.사커라인')
            for search in searchs
        ])

        all_data.to_csv(
            f'{result_dir}/사커라인_raw data_{today}.csv',
            encoding='utf-8',
            index=False
        )
        logging.info(f"[결과] 병합 파일 저장 완료: {result_dir}/사커라인_raw data_{today}.csv")
