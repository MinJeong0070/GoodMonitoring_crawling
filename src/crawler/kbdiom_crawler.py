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

from src.etc.utils import setup_driver, save_to_csv, clean_title
from src.etc.csv_to_excel import csv_to_excel

# 실행날짜 변수 및 폴더 생성
today = datetime.now().strftime("%y%m%d")
if not os.path.exists(f'log'):
    os.makedirs(f'log')

logging.basicConfig(
    filename=f'log/KBDIOM_log_{today}.txt',  # 로그 파일 이름
    level=logging.INFO,  # 로그 레벨
    format='%(asctime)s - %(levelname)s - %(message)s',  # 로그 형식
    encoding='utf-8'  # 인코딩 설정
)

def normalize_date_string(raw_date):
    import re
    try:
        parts = re.findall(r'\d+', raw_date)
        if len(parts) == 3:
            y, m, d = map(int, parts)
            return datetime(year=y, month=m, day=d).date()
        else:
            raise ValueError("날짜 숫자 3개 못 찾음")
    except Exception as e:
        logging.warning(f"[normalize 실패] {raw_date} / {e}")
        return None

def result_csv_data(search):
    file_path = f'csv/26.KBDIOM/{today}/KBDIOM_{search}.csv'

    # 파일 존재 여부 확인
    if not os.path.isfile(file_path):
        print(f"파일 '{file_path}'이 존재하지 않습니다. 스킵합니다.")
        return

    # CSV 파일 읽기
    df_fm = pd.read_csv(file_path, encoding='utf-8')

    return df_fm
# 한페이지 크롤링
def tistory_crw(wd, url, valid_domains, final_file):
    try:
        wd.get(url)
        WebDriverWait(wd, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'h3.tit_blogview'))
        )
        time.sleep(1)

        soup = BeautifulSoup(wd.page_source, 'html.parser')

        # 제목
        title_tag = soup.select_one('h3.tit_blogview')
        title = clean_title(title_tag.get_text(strip=True)) if title_tag else '제목없음'
        logging.info(f"[제목] {title}")

        # 본문 내용 추출
        paragraphs = soup.select('p[data-ke-size="size16"]')
        if not paragraphs:
            logging.warning(f"[본문 없음] {url}")
            return

        # 본문 내용 합치기
        content_lines = []
        original_url = ''
        for p in paragraphs:
            # 원문 링크 추출
            a_tag = p.find('a', href=True)
            if a_tag and any(domain in a_tag['href'] for domain in valid_domains):
                original_url = a_tag['href']
                continue  # 본문에서는 제외 (링크만 있는 문단일 수 있음)

            # 일반 본문 텍스트 추가
            text = p.get_text(strip=True)
            if text:
                content_lines.append(text)

        content_text = "\n".join(content_lines)

        if not content_text.strip():
            logging.warning(f"[본문 비어있음] {url}")
            return

        if not original_url:
            logging.info(f"[건너뜀] 유효한 원문기사 URL 없음: {url}")
            return

        date_tag = soup.select_one('span.txt_date')
        raw_date = date_tag.get_text(strip=True) if date_tag else ''

        try:
            # '2025. 5. 31. 16:29' → '2025.05.31'
            raw_date_clean = re.search(r'\d{4}\.\s?\d{1,2}\.\s?\d{1,2}', raw_date).group()
            raw_date_clean = raw_date_clean.replace(" ", "")  # 공백 제거
            post_date = datetime.strptime(raw_date_clean, "%Y.%m.%d").strftime('%Y-%m-%d')
        except Exception as e:
            logging.warning(f"[날짜 파싱 실패] {raw_date} / {e}")
            post_date = ''

        # 저장
        df = pd.DataFrame([{
            "플랫폼": "티스토리(kbdio)",
            "게시물 URL": url,
            "게시물 제목": title,
            "게시물 내용": content_text,
            "게시물 등록일자": post_date,
            "원문기사 URL": original_url
        }])
        save_to_csv(df, final_file)
        logging.info(f"[저장 완료] {title}")

    except Exception as e:
        import traceback
        logging.error(f"[본문 오류] {url} / {e}")
        logging.error(traceback.format_exc())


from urllib.parse import urljoin

def kbdiom_main_crw(search, start_date, end_date,stop_event):
    today = datetime.now().strftime("%y%m%d")
    final_file = f'csv/26.KBDIOM/{today}/KBDIOM.csv'

    # 📁 결과 저장 폴더 생성
    if not os.path.exists(f'csv/26.KBDIOM/{today}'):
        os.makedirs(f'csv/26.KBDIOM/{today}')
        print(f"[폴더 생성 완료] {today}")
    else:
        print(f"[폴더 존재] {today}")

    logging.info("======== KBDIOM 전체 게시글 크롤링 시작 ========")

    wd = setup_driver()
    wd_dp1 = setup_driver()

    domain_df = pd.read_excel('(언진) 전처리용 도메인 주소.xlsx')
    valid_domains = domain_df['도메인'].dropna().unique().tolist()

    stop_flag = False
    blog_url = "https://www.kbdio.com/m"
    wd.get(blog_url)
    time.sleep(2)

    for _ in range(100):
        if stop_event.is_set():
            print("🛑 크롤링 중단됨")
            break
        soup = BeautifulSoup(wd.page_source, 'html.parser')
        article_blocks = soup.select('div.cont_item')

        if article_blocks:
            last_block = article_blocks[-1]
            date_tag = last_block.select_one('span.num_data > span.num_g')
            raw_date = date_tag.get_text(strip=True) if date_tag else ''

            try:
                if '전' in raw_date:
                    post_date_obj = datetime.now().date()
                else:
                    post_date_obj = normalize_date_string(raw_date)
            except Exception as e:
                logging.warning(f"[날짜 파싱 실패] {raw_date} / {e}")
                continue

            if post_date_obj and post_date_obj < start_date:
                logging.info(f"[중단] 마지막 게시글이 시작 날짜({start_date})보다 이전임 → 더보기 종료")
                break

        try:
            more_btn = WebDriverWait(wd, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, 'btn_more_post'))
            )
            wd.execute_script("arguments[0].scrollIntoView(true);", more_btn)
            more_btn.click()
            time.sleep(2)
        except:
            logging.info("[더보기 버튼 없음] 모든 게시글 로딩 완료")
            break

    # 📥 게시글 수집
    soup = BeautifulSoup(wd.page_source, 'html.parser')
    article_blocks = soup.select('div.cont_item')

    for block in article_blocks:
        if stop_event.is_set():
            break
        if stop_flag:
            break

        try:
            a_tag = block.select_one('a.wrap_item')
            if not a_tag:
                logging.warning("[스킵] 게시글 링크 없음")
                continue

            post_url = urljoin(wd.current_url, a_tag['href'])

            # 📅 날짜 추출
            date_tag = block.select_one('span.num_data > span.num_g')
            raw_date = date_tag.get_text(strip=True) if date_tag else ''

            # 날짜 정규화
            if '전' in raw_date:
                post_date_obj = datetime.now().date()
            else:
                post_date_obj = normalize_date_string(raw_date)

            if not post_date_obj:
                logging.warning(f"[날짜 파싱 실패 - 건너뜀] {raw_date}")
                continue

            logging.info(f"[게시글 날짜] {post_url} → {post_date_obj}")

            # 날짜 비교 (범위 내인지 확인)
            if post_date_obj > end_date:
                continue
            if post_date_obj < start_date:
                logging.info(f"[중단] 시작 날짜 이전 게시글 도달: {post_url}")
                stop_flag = True
                break

            # ✅ 상세 페이지 진입
            logging.info(f"[상세 진입] {post_url}")
            tistory_crw(wd_dp1, post_url, valid_domains, final_file)

        except Exception as e:
            logging.error(f"[게시글 처리 오류] {e}")
            continue

    wd.quit()
    wd_dp1.quit()
    if not stop_event.is_set():
      csv_to_excel(final_file)


