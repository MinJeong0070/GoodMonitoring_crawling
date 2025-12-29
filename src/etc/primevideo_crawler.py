import os
import re
import time
import argparse
import logging
from datetime import datetime
from urllib.parse import urljoin, urlparse

import pandas as pd
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchWindowException, WebDriverException


# -------------------------------
# 로깅 설정
# -------------------------------
def make_logger():
    os.makedirs("logs", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join("logs", f"primevideo_{ts}.log")

    logger = logging.getLogger("pv")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.info(f"로그 파일: {log_path}")
    return logger

def make_driver(headless=False, block_images=True):
    chrome_opts = uc.ChromeOptions()
    if headless:
        chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--disable-extensions")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")

    profile_dir = os.path.join(os.getcwd(), "primevideo_profile")
    os.makedirs(profile_dir, exist_ok=True)
    chrome_opts.add_argument(f"--user-data-dir={profile_dir}")
    # chrome_opts.add_argument("--profile-directory=Default")  # 필요시 사용

    chrome_prefs = {}
    if block_images:
        chrome_prefs["profile.managed_default_content_settings.images"] = 2
    chrome_opts.add_experimental_option("prefs", chrome_prefs)

    driver = uc.Chrome(options=chrome_opts)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(60)
    driver.implicitly_wait(0)
    return driver

# -------------------------------
# 유틸 함수들
# -------------------------------
def parse_section_file(path):
    sections = []
    if not path or not os.path.exists(path):
        return sections

    pat = re.compile(r"^\s*(.+?)\s*:\s*(https?://\S+)\s*$")
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = pat.search(line.strip())
            if m:
                name = m.group(1).strip()
                url = m.group(2).strip()
                sections.append((name, url))
    return sections


def has_korean_char(text):
    if not text:
        return False
    korean_pattern = re.compile(r"[가-힣]")
    return bool(korean_pattern.search(text))


def clean_url(url):
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path
    path = re.sub(r"/ref=.*", "", path)
    return urljoin(url, path)

# -------------------------------
# 리스트 페이지 수집 관련
# -------------------------------
GET_SCROLL_POS_JS = """
return [document.documentElement.scrollTop || document.body.scrollTop,
        document.documentElement.scrollHeight || document.body.scrollHeight,
        document.documentElement.clientHeight || document.body.clientHeight];
"""


def safe_exec_js(driver, script, fallback=(0, 0, 0)):
    try:
        res = driver.execute_script(script)
        if isinstance(res, (list, tuple)) and len(res) == 3:
            return res
        return fallback
    except Exception:
        return fallback


def extract_items_current_view(driver, logger):
    items = []
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
            if not href or "/detail/" not in href:
                continue

            title = a.get_attribute("data-card-title") or ""
            if not title:
                title = a.get_attribute("aria-label") or ""
            if not title:
                try:
                    t_el = a.find_element(By.CSS_SELECTOR, "[data-card-title]")
                    title = t_el.get_attribute("data-card-title") or t_el.text
                except Exception:
                    pass
            if not title:
                try:
                    t_el = a.find_element(By.CSS_SELECTOR, "[data-automation-id*='title']")
                    title = t_el.text.strip()
                except Exception:
                    pass
            if not title:
                title = (a.text or "").strip()
            if not title or len(title) < 1:
                continue
            items.append({"title": title, "href": href})
        except Exception:
            continue

    uniq = {}
    for it in items:
        uniq[it["href"]] = it
    return list(uniq.values())


def click_season_toggles(driver, logger, clicked_toggles):
    toggles_found_and_clicked = 0
    try:
        xpath = "//button[@role='tab' and @aria-controls]"
        toggles_to_process = []
        all_toggles = driver.find_elements(By.XPATH, xpath)

        for toggle in all_toggles:
            try:
                if toggle.get_attribute("aria-selected") == "true":
                    continue
                toggle_id = toggle.get_attribute("aria-controls")
                if not toggle_id:
                    continue
                if toggle_id not in clicked_toggles:
                    toggles_to_process.append((toggle, toggle_id))
            except Exception:
                continue

        if not toggles_to_process:
            return False

        logger.info(f"[시즌 토글] {len(toggles_to_process)}개 발견. 클릭 진행.")
        for toggle, toggle_id in toggles_to_process:
            try:
                driver.execute_script("arguments[0].click();", toggle)
                clicked_toggles.add(toggle_id)
                toggles_found_and_clicked += 1
                time.sleep(2.5)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"시즌 토글 오류: {e}")
        return False

    return toggles_found_and_clicked > 0


def crawl_list_page(driver, url, logger, max_idle_rounds=3, per_round_pause=1.2, step_px=900):
    logger.info(f"이동: {url}")
    driver.get(url)

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/detail/']"))
        )
    except Exception:
        logger.warning("첫 카드 감지 실패(계속 진행)")
        time.sleep(2)

    seen = set()
    clicked_toggles = set()
    harvested = []
    idle = 0
    round_idx = 0
    time.sleep(0.8)

    while True:
        round_idx += 1
        toggles_clicked = click_season_toggles(driver, logger, clicked_toggles)
        current = extract_items_current_view(driver, logger)
        new_add = 0
        for it in current:
            if it["href"] not in seen:
                seen.add(it["href"])
                harvested.append(it)
                logger.info(f"수확: {it['title']}")
                new_add += 1

        top, height, client = safe_exec_js(driver, GET_SCROLL_POS_JS, fallback=(0, 10000, 800))
        is_at_bottom = (top + client + 10) >= height

        if not is_at_bottom:
            next_top = min(top + step_px, max(0, height - client))
            driver.execute_script(f"window.scrollTo(0, {next_top});")
            time.sleep(per_round_pause)
        else:
            logger.info("페이지 하단 도달.")

        if new_add == 0 and not toggles_clicked:
            idle += 1
        else:
            idle = 0

        if idle >= max_idle_rounds:
            logger.info("수집 종료(새 항목 없음)")
            break

        if round_idx > 200:
            logger.warning("최대 라운드 도달. 종료.")
            break

    return harvested

# -------------------------------
# 상세 페이지 스크래핑 헬퍼
# -------------------------------
def get_text_safe(driver_or_element, by, selector, logger, wait_time=0.5):
    try:
        if by == By.XPATH:
            el = WebDriverWait(driver_or_element, wait_time).until(
                EC.presence_of_element_located((By.XPATH, selector))
            )
        else:
            el = WebDriverWait(driver_or_element, wait_time).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
        return el.text.strip()
    except Exception:
        return ""


def click_details_tab(driver, logger):
    try:
        xpath = "//button[contains(., '세부 정보') or contains(., 'Details')]"
        try:
            tab_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            if tab_btn.get_attribute("aria-selected") != "true":
                driver.execute_script("arguments[0].click();", tab_btn)
                time.sleep(1.5)
        except:
            pass
    except Exception:
        pass


def extract_single_page_info(driver, logger, current_url):
    """현재 열려있는 페이지의 정보만 쏙 빼오는 함수"""
    WRAPPER_BASE_CSS = "div.DVWebNode-detail-vod-wrapper[data-apex='detail-vod']"
    WRAPPER_BASE_XPATH = "//div[@data-apex='detail-vod']"

    # [1] 장르
    extracted_genre = ""
    try:
        genre_nodes = driver.find_elements(
            By.CSS_SELECTOR,
            f"{WRAPPER_BASE_CSS} [data-testid='genre-texts'] a, {WRAPPER_BASE_CSS} [data-testid='genre-texts'] span"
        )
        genres = []
        for n in genre_nodes:
            t = (n.text or "").strip()
            if t and "검색" not in t:
                genres.append(t)
        if genres:
            extracted_genre = " · ".join(sorted(set(genres)))

        if not extracted_genre:
            metadata_rows = driver.find_elements(By.CSS_SELECTOR, f"{WRAPPER_BASE_CSS} dl")
            if not metadata_rows:
                metadata_rows = driver.find_elements(By.XPATH, "//*[@data-testid='metadata-row']")
            for row in metadata_rows:
                row_text = row.text.strip()
                if "장르" in row_text or "Genres" in row_text:
                    parts = row_text.split("\n")
                    if len(parts) > 1:
                        extracted_genre = parts[-1].strip()
                    break
    except:
        pass

    # [2] 기본정보(한국어)
    basic_info_kor = "X"
    try:
        synopsis_text = ""
        synopsis_selectors = [
            "div[data-testid='synopsis']",
            "div[data-automation-id='synopsis']",
            "div[class*='synopsis']",
            "div._3tB6mN"
        ]
        for sel in synopsis_selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, f"{WRAPPER_BASE_CSS} {sel}")
                text = el.text.strip()
                if text:
                    synopsis_text = text
                    break
            except:
                continue
        if has_korean_char(synopsis_text):
            basic_info_kor = "O"
    except:
        pass

    # [3] 자막(한국어)
    subtitle_kor = "X"
    try:
        metadata_rows = driver.find_elements(By.CSS_SELECTOR, f"{WRAPPER_BASE_CSS} dl")
        if not metadata_rows:
            metadata_rows = driver.find_elements(By.XPATH, "//*[@data-testid='metadata-row']")
        for row in metadata_rows:
            row_text = row.text.strip()
            if "자막" in row_text or "Subtitles" in row_text:
                if "한국어" in row_text or "Korean" in row_text:
                    subtitle_kor = "O"
                break
    except:
        pass

    # [4] 등급
    rating = ""
    try:
        xpath = f"{WRAPPER_BASE_XPATH}//*[contains(text(), '등급입니다')]"
        els = driver.find_elements(By.XPATH, xpath)
        for el in els:
            t = el.text.strip()
            m = re.search(r"이 콘텐츠는\s*([0-9]{1,2}\+|전체)\s*등급입니다", t)
            if m:
                rating = m.group(1)
                break

        if not rating:
            aria_els = driver.find_elements(By.XPATH, f"{WRAPPER_BASE_XPATH}//*[@aria-label]")
            for el in aria_els:
                label = el.get_attribute("aria-label") or ""
                m = re.search(r"이 콘텐츠는\s*([0-9]{1,2}\+|전체)\s*등급입니다", label)
                if m:
                    rating = m.group(1)
                    break
    except:
        pass

    # [5] 출시연도
    year = ""
    try:
        text = get_text_safe(
            driver,
            By.CSS_SELECTOR,
            f"{WRAPPER_BASE_CSS} span[data-automation-id='release-year-badge']",
            logger,
            0.7,
        )
        if not text:
            text = get_text_safe(
                driver,
                By.XPATH,
                f"{WRAPPER_BASE_XPATH}//span[number(text())>1900 and number(text())<2100]",
                logger,
                0.7,
            )
        if text:
            m = re.search(r"(19\d{2}|20\d{2})", text)
            if m:
                year = m.group(1)
    except:
        pass

    # ------------------------------------------------------------------
    # [6] 에피소드 수
    # ------------------------------------------------------------------
    episode_count = ""
    try:
        xpath = (
            f"{WRAPPER_BASE_XPATH}"
            "//*[contains(text(), ' 에피소드') or contains(text(), '개 에피소드')]"
        )
        candidates = driver.find_elements(By.XPATH, xpath)

        for el in candidates:
            text = el.text.strip()
            if "시즌" in text:
                continue
            if "에피소드" not in text:
                continue

            m = re.search(r"(\d+)", text)
            if m:
                episode_count = m.group(1)
                logger.info(f"시리즈 갯수 추출(텍스트): {episode_count} (from: '{text}')")
                break

    except Exception as e:
        logger.warning(f"시리즈 갯수 텍스트 탐색 중 오류: {e}")

    # [Fallback] 스크롤 후 카드 수로 추정
    if not episode_count:
        try:
            total_height = driver.execute_script("return document.body.scrollHeight")
            viewport_height = driver.execute_script("return window.innerHeight")
            c_scroll = 0
            attempts = 0
            while c_scroll < total_height and attempts < 15:
                c_scroll += viewport_height * 1.5
                driver.execute_script(f"window.scrollTo(0, {c_scroll});")
                time.sleep(0.3)
                new_h = driver.execute_script("return document.body.scrollHeight")
                if new_h == total_height:
                    attempts += 1
                else:
                    total_height = new_h
                    attempts = 0
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.0)

            selectors = [
                "div[data-testid='ep-card']",
                "div[data-automation-id='episode']",
                "li[data-automation-id='episode-list-item']",
            ]
            for sel in selectors:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    episode_count = str(len(els))
                    logger.info(f"시리즈 갯수 추출(스크롤): {episode_count}개")
                    break
        except:
            pass

    # [7] 시즌 번호
    season_num = "1"
    try:
        txt = get_text_safe(
            driver,
            By.XPATH,
            f"{WRAPPER_BASE_XPATH}//*[contains(text(), '시즌 ')]",
            logger,
            0.7,
        )
        m = re.search(r"(\d+)", txt)
        if m:
            season_num = m.group(1)
    except:
        pass

    return {
        "장르": extracted_genre,
        "등급": rating,
        "출시연도": year,
        "시즌": season_num,
        "시리즈 갯수": episode_count,
        "기본정보(한국어)": basic_info_kor,
        "자막(한국어)": subtitle_kor,
        "specific_url": current_url,
    }

# -------------------------------
# 상세 페이지 메인 컨트롤러 (멀티 시즌 처리)
# -------------------------------
def scrape_detail_page(driver, logger):
    WRAPPER_BASE_CSS = "div.DVWebNode-detail-vod-wrapper[data-apex='detail-vod']"

    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, WRAPPER_BASE_CSS))
        )
        time.sleep(1.0)
    except Exception:
        logger.warning("상세 페이지 래퍼 로드 실패")
        return []

    click_details_tab(driver, logger)
    final_results = []

    # ----------------------------------------------------
    # [V4 강화] 멀티 시즌 탐색 로직
    # ----------------------------------------------------
    multi_season_found = False
    season_links = []

    try:
        dropdown_candidates = [
            "label[for='av-droplist-av-atf-season-selector']",
            "button[data-automation-id='season-selector']",
            "div[data-testid='season-selector'] button",
            "button[aria-label*='Season']",
            "button[aria-label*='시즌']",
        ]

        trigger_el = None
        for sel in dropdown_candidates:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    if el.is_displayed():
                        trigger_el = el
                        break
                if trigger_el:
                    break
            except:
                continue

        if trigger_el:
            logger.info(">>> 시즌 드롭다운 버튼 발견! 클릭을 시도합니다.")
            try:
                driver.execute_script("arguments[0].click();", trigger_el)
            except:
                trigger_el.click()

            time.sleep(2.0)

            list_selectors = [
                "//label[@for='av-droplist-av-atf-season-selector']/following-sibling::ul//li/a",
                "//div[contains(@class, 'SeasonSelector')]//ul//li//a",
                "//div[@data-testid='season-selector']//ul//li//a",
                "//ul[contains(@aria-label, 'Season')]//li//a",
            ]

            for xpath in list_selectors:
                try:
                    links = driver.find_elements(By.XPATH, xpath)
                    if links:
                        for l in links:
                            href = l.get_attribute("href")
                            txt = (l.get_attribute("textContent") or "").strip()
                            if href and txt:
                                season_links.append((txt, href))
                        if season_links:
                            break
                except:
                    continue

            if season_links:
                multi_season_found = True
                logger.info(f">>> 총 {len(season_links)}개의 시즌 링크를 수집했습니다.")

    except Exception as e:
        logger.warning(f"멀티 시즌 감지 로직 에러 (단일 시즌으로 진행): {e}")

    # ----------------------------------------------------
    # [Case 1] 멀티 시즌
    # ----------------------------------------------------
    if multi_season_found:
        for s_name, s_href in season_links:
            try:
                s_num = s_name
                m = re.search(r"(\d+)", s_name)
                if m:
                    s_num = m.group(1)

                logger.info(f"   [이동] {s_name} 크롤링 중... ({s_href})")
                driver.get(s_href)

                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, WRAPPER_BASE_CSS))
                )
                time.sleep(1.0)
                click_details_tab(driver, logger)

                data = extract_single_page_info(driver, logger, s_href)
                if s_num and s_num.isdigit():
                    data["시즌"] = s_num

                final_results.append(data)

            except Exception as e:
                logger.error(f"   [오류] {s_name} 처리 실패: {e}")
                continue

    # ----------------------------------------------------
    # [Case 2] 단일 시즌
    # ----------------------------------------------------
    else:
        logger.info(">>> 단일 시즌(또는 영화)으로 판단하여 처리합니다.")
        data = extract_single_page_info(driver, logger, driver.current_url)
        final_results.append(data)

    return final_results


# -------------------------------
# 메인 실행 로직
# -------------------------------
def run_category(
    driver,
    logger,
    txt_path,
    out_xlsx,
    headless=False,
    block_images=True,
    flush_every=10,
    restart_every=100,
):

    sections = parse_section_file(txt_path)
    if not sections:
        logger.warning(f"파일 없음: {txt_path}")
        return driver

    os.makedirs(os.path.dirname(out_xlsx) or ".", exist_ok=True)

    # 체크포인트 저장용 디렉터리
    checkpoint_dir = os.path.join(os.path.dirname(out_xlsx) or ".", "_checkpoint")
    os.makedirs(checkpoint_dir, exist_ok=True)

    writer = pd.ExcelWriter(out_xlsx, engine="openpyxl")

    processed_count = 0

    for sec_name, url in sections:
        logger.info(f"=== [{sec_name}] 크롤링 시작 ===")

        # 시트 이름 및 체크포인트 파일명
        sheet = re.sub(r'[\\/*?:\[\]]', "_", sec_name)[:31]
        checkpoint_path = os.path.join(
            checkpoint_dir,
            f"{os.path.splitext(os.path.basename(out_xlsx))[0]}_{sheet}.csv",
        )

        # 리스트 페이지 수집 (NoSuchWindowException 대비)
        try:
            items = crawl_list_page(driver, url, logger)
        except NoSuchWindowException as e:
            logger.error(f"[{sec_name}] 리스트 페이지 수집 중 NoSuchWindowException 발생: {e}")
            try:
                driver.quit()
            except Exception:
                pass
            logger.info("[리스트] 브라우저 재시작 후 다시 시도합니다.")
            driver = make_driver(headless=headless, block_images=block_images)
            driver.get(url)
            items = crawl_list_page(driver, url, logger)

        if not items:
            pd.DataFrame().to_excel(writer, index=False, sheet_name=sheet)
            logger.info(f"[{sec_name}] 수집된 아이템이 없어 빈 시트 저장")
            continue

        all_data = []
        buffer_rows = []  # 체크포인트용 버퍼
        total = len(items)

        for i, item in enumerate(items):
            clean_href = clean_url(item["href"])
            logger.info(f"[{sec_name} {i + 1}/{total}] 상세 페이지 진입: {item['title']}")

            detail_retry = 0
            while True:
                try:
                    if (
                        restart_every
                        and processed_count > 0
                        and processed_count % restart_every == 0
                        and detail_retry == 0
                    ):
                        logger.info(
                            f"[안정화] 상세페이지 {processed_count}건 처리됨. "
                            f"브라우저를 재시작하여 메모리를 정리합니다."
                        )
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = make_driver(headless=headless, block_images=block_images)

                    # 실제 상세페이지 접속
                    driver.get(clean_href)

                    # 멀티 시즌/단일 시즌 모두 처리
                    results_list = scrape_detail_page(driver, logger)

                    if not results_list:
                        row = {
                            "title": item["title"],
                            "href": clean_href,
                            "장르": "",
                            "등급": "",
                            "출시연도": "",
                            "시즌": "",
                            "시리즈 갯수": "",
                            "기본정보(한국어)": "X",
                            "자막(한국어)": "X",
                        }
                        all_data.append(row)
                        buffer_rows.append(row)
                    else:
                        for res in results_list:
                            row = {
                                "title": item["title"],
                                "href": clean_url(res.get("specific_url", clean_href)),
                                "장르": res.get("장르", ""),
                                "등급": res.get("등급", ""),
                                "출시연도": res.get("출시연도", ""),
                                "시즌": res.get("시즌", ""),
                                "시리즈 갯수": res.get("시리즈 갯수", ""),
                                "기본정보(한국어)": res.get("기본정보(한국어)", "X"),
                                "자막(한국어)": res.get("자막(한국어)", "X"),
                            }
                            all_data.append(row)
                            buffer_rows.append(row)

                    processed_count += 1
                    break  # while True 탈출(해당 아이템 성공 처리)

                except NoSuchWindowException as e:
                    detail_retry += 1
                    logger.error(
                        f"[{sec_name} {i + 1}/{total}] NoSuchWindowException 발생 "
                        f"(재시도 {detail_retry}회): {e}"
                    )
                    try:
                        driver.quit()
                    except Exception:
                        pass

                    if detail_retry >= 3:
                        logger.error(
                            f"[{sec_name} {i + 1}/{total}] "
                            f"NoSuchWindowException 3회 발생으로 이 항목은 건너뜁니다."
                        )
                        row = {
                            "title": item["title"],
                            "href": clean_href,
                            "장르": "ERROR(NoSuchWindow)",
                            "등급": "",
                            "출시연도": "",
                            "시즌": "",
                            "시리즈 갯수": "",
                            "기본정보(한국어)": "X",
                            "자막(한국어)": "X",
                        }
                        all_data.append(row)
                        buffer_rows.append(row)
                        break

                    logger.info("[상세] 브라우저 재시작 후 같은 콘텐츠 다시 시도합니다.")
                    driver = make_driver(headless=headless, block_images=block_images)

                except WebDriverException as e:
                    detail_retry += 1
                    logger.error(
                        f"[{sec_name} {i + 1}/{total}] WebDriverException 발생 "
                        f"(재시도 {detail_retry}회): {e}"
                    )
                    try:
                        driver.quit()
                    except Exception:
                        pass

                    if detail_retry >= 3:
                        logger.error(
                            f"[{sec_name} {i + 1}/{total}] "
                            f"WebDriverException 3회 발생으로 이 항목은 건너뜁니다."
                        )
                        row = {
                            "title": item["title"],
                            "href": clean_href,
                            "장르": "ERROR(WebDriver)",
                            "등급": "",
                            "출시연도": "",
                            "시즌": "",
                            "시리즈 갯수": "",
                            "기본정보(한국어)": "X",
                            "자막(한국어)": "X",
                        }
                        all_data.append(row)
                        buffer_rows.append(row)
                        break

                    logger.info("[상세] 브라우저 재시작 후 같은 콘텐츠 다시 시도합니다.")
                    driver = make_driver(headless=headless, block_images=block_images)

                except Exception as e:
                    logger.error(
                        f"[{sec_name} {i + 1}/{total}] 상세 페이지 전체 처리 중 치명적 오류: {e}"
                    )
                    row = {
                        "title": item["title"],
                        "href": clean_href,
                        "장르": "ERROR",
                        "등급": "",
                        "출시연도": "",
                        "시즌": "",
                        "시리즈 갯수": "",
                        "기본정보(한국어)": "X",
                        "자막(한국어)": "X",
                    }
                    all_data.append(row)
                    buffer_rows.append(row)
                    break

            # ---- 10건마다 체크포인트 파일로 저장 ----
            if buffer_rows and (len(buffer_rows) >= flush_every or i == total - 1):
                try:
                    df_buf = pd.DataFrame(
                        buffer_rows,
                        columns=[
                            "title",
                            "href",
                            "장르",
                            "등급",
                            "출시연도",
                            "시즌",
                            "시리즈 갯수",
                            "기본정보(한국어)",
                            "자막(한국어)",
                        ],
                    )
                    header = not os.path.exists(checkpoint_path)
                    df_buf.to_csv(
                        checkpoint_path,
                        mode="a",
                        encoding="utf-8-sig",
                        index=False,
                        header=header,
                    )
                    logger.info(
                        f"[{sec_name}] 체크포인트 저장: {len(buffer_rows)}건 -> {checkpoint_path}"
                    )
                except Exception as e:
                    logger.error(f"[{sec_name}] 체크포인트 저장 중 오류: {e}")
                finally:
                    buffer_rows = []  # 버퍼 초기화

        # --- 기존 방식대로 섹션 단위로 최종 엑셀 시트 작성 ---
        df = pd.DataFrame(
            all_data,
            columns=[
                "title",
                "href",
                "장르",
                "등급",
                "출시연도",
                "시즌",
                "시리즈 갯수",
                "기본정보(한국어)",
                "자막(한국어)",
            ],
        )
        df.to_excel(writer, index=False, sheet_name=sheet)
        logger.info(f"[{sec_name}] {len(df)}건 데이터 저장 완료")

    writer.close()
    logger.info(f"엑셀 파일 저장 완료: {out_xlsx}")
    return driver

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--movies", default="[영화].txt")
    ap.add_argument("--sports", default="[스포츠].txt")
    ap.add_argument("--tv", default="[TV 프로그램].txt")
    ap.add_argument("--outdir", default="output_excel")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-block-images", action="store_true")
    args = ap.parse_args()

    logger = make_logger()
    driver = None
    try:
        driver = make_driver(
            headless=args.headless,
            block_images=not args.no_block_images,
        )
        logger.info("Chrome 실행. 프라임비디오로 이동합니다.")
        driver.get("https://www.primevideo.com/")

        logger.info("=" * 50)
        logger.info(" [로그인 대기] 브라우저에서 로그인을 완료해주세요.")
        logger.info(" 로그인이 끝나면, 이 창에서 [Enter] 키를 누르세요.")
        logger.info("=" * 50)
        input()

        outdir = args.outdir
        os.makedirs(outdir, exist_ok=True)

        driver = run_category(
            driver,
            logger,
            args.movies,
            os.path.join(outdir, "primevideo_영화.xlsx"),
            headless=args.headless,
            block_images=not args.no_block_images,
        )
        driver = run_category(
            driver,
            logger,
            args.sports,
            os.path.join(outdir, "primevideo_스포츠.xlsx"),
            headless=args.headless,
            block_images=not args.no_block_images,
        )
        driver = run_category(
            driver,
            logger,
            args.tv,
            os.path.join(outdir, "primevideo_TV프로그램.xlsx"),
            headless=args.headless,
            block_images=not args.no_block_images,
        )

        logger.info("=== 모든 작업이 완료되었습니다 ===")
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
