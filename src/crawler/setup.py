import os
import re
import logging
import pandas as pd
from datetime import datetime
import undetected_chromedriver as uc


# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'../log'):
    os.makedirs(f'../log')

def setup_driver():
    logging.info("웹드라이버 시작")
    options = uc.ChromeOptions()
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    options.add_argument(f"user-agent={user_agent}")
    options.page_load_strategy = 'eager'
    options.add_argument('--disable-popup-blocking')
    options.add_argument("--disable-javascript")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = uc.Chrome(options=options, enable_cdp_events=True, incognito=True)

    return driver

def result_csv_data(search):


    file_path = f'../csv/1.뽐뿌/{today}/뽐뿌_{search}.csv'
    # 파일 존재 여부 확인
    if not os.path.isfile(file_path):
        print(f"파일 '{file_path}'이 존재하지 않습니다. 스킵합니다.")
        return

    # CSV 파일 읽기
    df_fm = pd.read_csv(file_path, encoding='utf-8')

    return df_fm
# csv 저장
def save_to_csv(df, file_name):
    try:
        if os.path.isfile(file_name):
            # 기존 파일이 존재하는 경우
            df.to_csv(file_name, mode='a', header=False, index=False, encoding='utf-8')
        else:
            # 새로운 파일을 만드는 경우, 헤더 포함
            df.to_csv(file_name, index=False, encoding='utf-8')
        print(f"저장완료 : {file_name}")
    except Exception as e:
        print(f"파일 저장 오류: {e}")


def clean_title(title):
    # 제목 뒤 넘버링 제거
    title = re.sub(r'\d+$', '', title).strip()
    # 파일 확장자 제거 (.jpg, .mp4 등)
    title = re.sub(r'\.(jpg|png|gif|mp4|avi|mkv|webm|jpeg)$', '', title, flags=re.IGNORECASE).strip()
    # 초성 제거 (자음만 있는 경우)
    title = re.sub(r'^[ㄱ-ㅎㅏ-ㅣ]+$', '', title).strip()
    # 따옴표 제거
    title = title.replace('"', '').strip()
    return title
