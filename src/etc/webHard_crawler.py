import time
import re
import pandas as pd
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================
# 설정
# ============================
BASE_URL = "https://www.applefile.com"
LOGIN_URL = f"{BASE_URL}/"
CONTENTS_URL = f"{BASE_URL}/contents/#tab=MVO&limit=20"

# 사용자 계정 정보
USER_ID = "gms1123"
USER_PW = "gms11234!!"

# 수집할 10개 카테고리 명시
TARGET_CATEGORIES = [
    "영화", "드라마", "동영상", "게임", "애니",
    "만화", "도서", "교육", "이미지", "기타"
]

FILENAME = f"애플파일_10개카테고리_집계_{datetime.now().strftime('%Y%m%d')}.xlsx"
OUTPUT_PATH = Path.cwd() / FILENAME


def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1600,1000")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options
    )
    return driver


def login(driver):
    print(">>> [로그인] 접속 중...")
    driver.get(LOGIN_URL)
    time.sleep(1.5)

    try:
        driver.find_element(By.CSS_SELECTOR, "input[name='userid']").send_keys(USER_ID)
        driver.find_element(By.CSS_SELECTOR, "input[name='userpw']").send_keys(USER_PW)

        btn = driver.find_element(By.CSS_SELECTOR, "#login_btn")
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2.0)
        print(">>> [로그인] 성공\n")
    except Exception as e:
        print(f"[오류] 로그인 실패: {e}")
        raise


def get_current_page_number(driver):
    """현재 활성화된(class='current') 페이지 번호를 반환"""
    try:
        # div.pagination 내부의 strong 또는 li.current 찾기
        current_el = driver.find_elements(By.CSS_SELECTOR, "div.pagination li.current, div.pagination strong")
        if current_el:
            txt = current_el[0].text.strip()
            if txt.isdigit():
                return int(txt)
    except:
        pass
    return 1


def count_category_realtime(driver, category_name, total_accumulated):
    """
    페이지를 넘기며 실시간으로 확인된 게시물 수를 출력
    total_accumulated: 이전 카테고리까지의 총 합계
    """
    print(f"--- [{category_name}] 집계 시작 ---")

    last_page_num = 1

    while True:
        try:
            # 현재 페이지 번호 확인
            current_page = get_current_page_number(driver)
            last_page_num = current_page

            # 현재까지 파악된 대략적 개수 (현재페이지 * 20개)
            estimated_count = (current_page - 1) * 20

            print(f"\r   >> [{category_name}] {current_page}페이지 도달.. (현재 누적 약 {estimated_count:,}건)", end="",
                  flush=True)

            next_btns = driver.find_elements(By.CSS_SELECTOR, "div.pagination a.next")
            if not next_btns:
                next_btns = [a for a in driver.find_elements(By.CSS_SELECTOR, "div.pagination a") if ">" in a.text]

            if next_btns:
                driver.execute_script("arguments[0].click();", next_btns[0])
                time.sleep(0.5)  # 페이지 로딩 대기 (너무 빠르면 차단될 수 있으므로 조절)

                try:
                    WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.pagination"))
                    )
                except:
                    time.sleep(1)
            else:
                # 더 이상 Next 버튼이 없으면 루프 종료 (마지막 페이지 그룹 도착)
                break

        except Exception as e:
            print(f"\n[오류] 페이지 이동 중 에러: {e}")
            break

    print()  # 줄바꿈

    try:
        pages = driver.find_elements(By.CSS_SELECTOR, "div.pagination ul li a")
        # 숫자만 있는 링크 중 가장 큰 것 찾기
        page_nums = []
        for p in pages:
            txt = p.text.strip()
            if txt.isdigit():
                page_nums.append((int(txt), p))

        if page_nums:
            page_nums.sort(key=lambda x: x[0])
            real_last_page = page_nums[-1][0]
            real_last_el = page_nums[-1][1]

            # 현재 페이지보다 더 뒤에 페이지가 있다면 클릭
            if real_last_page > last_page_num:
                driver.execute_script("arguments[0].click();", real_last_el)
                time.sleep(1.0)
                last_page_num = real_last_page
    except:
        pass

    # 3. 마지막 페이지의 실제 게시물 수(row) 세기
    rows = driver.find_elements(By.CSS_SELECTOR, "table.table_hoz tbody tr")
    valid_rows = 0
    for row in rows:
        if row.find_elements(By.CSS_SELECTOR, "td.title"):
            valid_rows += 1

    final_count = ((last_page_num - 1) * 20) + valid_rows

    print(f"   [완료] {category_name}: 총 {final_count:,}건 (마지막 {last_page_num}페이지)")
    return final_count


def main():
    driver = create_driver()
    results = []
    grand_total = 0

    try:
        login(driver)

        driver.get(CONTENTS_URL)
        time.sleep(2)

        print(f"[{' / '.join(TARGET_CATEGORIES)}] 순서로 수집을 시작합니다.\n")

        for target_name in TARGET_CATEGORIES:
            driver.get(CONTENTS_URL)
            time.sleep(1.5)

            tabs = driver.find_elements(By.CSS_SELECTOR, "div.category ul.depth1 li a")
            target_tab = None
            for tab in tabs:
                if tab.text.strip() == target_name:
                    target_tab = tab
                    break

            if target_tab:
                driver.execute_script("arguments[0].click();", target_tab)
                time.sleep(1.5)

                # 집계 수행
                count = count_category_realtime(driver, target_name, grand_total)
                grand_total += count

                results.append({
                    "카테고리": target_name,
                    "게시물 수": count
                })

                print(f"   => 현재까지 총 누적 수집량: {grand_total:,}건\n")
            else:
                print(f"[경고] '{target_name}' 카테고리 탭을 찾지 못했습니다. 건너뜁니다.\n")

    except Exception as e:
        print(f"[치명적 오류] {e}")
    finally:
        driver.quit()

    if results:
        df = pd.DataFrame(results)
        # 합계 행 추가
        df.loc[len(df)] = ["합계", grand_total]

        df.to_excel(OUTPUT_PATH, index=False)
        print(f"==========================================")
        print(f" 모든 작업 완료! 총 {grand_total:,}건")
        print(f" 파일 저장됨: {OUTPUT_PATH}")
        print(f"==========================================")


if __name__ == "__main__":
    main()