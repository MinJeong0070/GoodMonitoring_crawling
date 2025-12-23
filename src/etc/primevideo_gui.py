# primevideo_gui.py
# -------------------------------
# primevideo_crawler.py의 함수를 import하여
# GUI(그래픽 인터페이스)로 실행하는 스크립트
# -------------------------------

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading
import sys
import os
import re
import time
import logging

# --- primevideo_crawler.py에서 실제 함수 Import ---
# (두 파일이 같은 폴더에 있다고 가정)
try:
    from primevideo_crawler import (
        run_category,
        make_logger,
        make_driver,
        parse_section_file,
        scrape_detail_page,  # run_category가 의존함
        get_text_safe,  # scrape_detail_page가 의존함
    )
    HAS_CRAWLER = True
except ImportError as e:
    HAS_CRAWLER = False
    print("\n" + "=" * 60)
    print(f"!!! 크롤러 불러오기 실패 원인: {e}")  # <--- 진짜 에러 메시지를 출력함
    print("=" * 60 + "\n")
    print("경고: primevideo_crawler.py가 없거나, 필요한 라이브러리가 설치되지 않았습니다.")

    def parse_section_file(path):
        print(f"[DUMMY] {path} 파일 읽기 시도...")
        if "영화" in path:
            return [(f"영화 섹션 {i}", "http://dummy.url") for i in range(1, 17)]
        if "TV" in path:
            return [(f"TV 섹션 {i}", "http://dummy.url") for i in range(1, 19)]
        if "스포츠" in path:
            return [(f"스포츠 섹션 {i}", "http://dummy.url") for i in range(1, 7)]
        return []

    def run_category(driver, logger, txt_path, out_xlsx, *args, **kwargs):
        print(f"[DUMMY 크롤링 실행] {txt_path} -> {out_xlsx}")
        for i in range(5):
            print(f"{txt_path} 진행 중... {i * 25}%")
            time.sleep(0.5)
        print(f"[DUMMY 크롤링 완료] {txt_path}")
        return driver

    def make_logger():
        print("[DUMMY 로거 생성]")
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
        )
        return logging.getLogger("dummy")

    def make_driver(headless, block_images):
        print(f"[DUMMY 드라이버 생성] Headless: {headless}, Block Images: {block_images}")
        return None


# --- 스크롤 가능한 프레임 (긴 목록을 위함) ---
class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        canvas = tk.Canvas(self, height=200, highlightthickness=0)  # 높이 조절
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel)
        canvas.bind("<MouseWheel>", self._on_mousewheel)
        scrollbar.bind("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        # 마우스 휠 스크롤 지원
        # (윈도우/리눅스 호환)
        if event.delta:  # 윈도우
            delta = -1 * (event.delta // 120)
        else:  # 리눅스
            if event.num == 5:
                delta = 1
            elif event.num == 4:
                delta = -1

        parent_canvas = self.winfo_children()[0]  # canvas
        parent_canvas.yview_scroll(delta, "units")


# --- 메인 GUI 애플리케이션 ---
class CrawlerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Prime Video 크롤러")
        self.geometry("450x600")  # 창 크기 조절

        self.vars = {}  # 모든 체크박스 변수
        self.all_sections = {}  # 파일에서 읽어온 섹션 (이름, URL) 저장
        self.category_frames = {}  # 스크롤 프레임 저장

        # 크롤링할 파일 경로 정의
        self.FILE_PATHS = {
            "movies": ("[영화].txt", "output_excel/primevideo_영화.xlsx"),
            "tv": ("[TV 프로그램].txt", "output_excel/primevideo_TV프로그램.xlsx"),
            "sports": ("[스포츠].txt", "output_excel/primevideo_스포츠.xlsx"),
        }

        # --- 1. 메인 카테고리 ---
        main_frame = ttk.LabelFrame(self, text="1. 메인 카테고리 선택")
        main_frame.pack(padx=10, pady=10, fill="x")

        self.vars["all"] = tk.BooleanVar()
        cb_all = ttk.Checkbutton(
            main_frame,
            text="전체 크롤링 (모두 선택)",
            variable=self.vars["all"],
            command=self.toggle_all,
        )
        cb_all.pack(anchor="w", padx=5, pady=2)

        ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=5, padx=5)

        self.vars["movies"] = tk.BooleanVar()
        cb_movies = ttk.Checkbutton(
            main_frame,
            text="영화",
            variable=self.vars["movies"],
            command=lambda: self.toggle_category("movies"),
        )
        cb_movies.pack(anchor="w", padx=5, pady=2)

        self.vars["tv"] = tk.BooleanVar()
        cb_tv = ttk.Checkbutton(
            main_frame,
            text="TV 프로그램",
            variable=self.vars["tv"],
            command=lambda: self.toggle_category("tv"),
        )
        cb_tv.pack(anchor="w", padx=5, pady=2)

        self.vars["sports"] = tk.BooleanVar()
        cb_sports = ttk.Checkbutton(
            main_frame,
            text="스포츠",
            variable=self.vars["sports"],
            command=lambda: self.toggle_category("sports"),
        )
        cb_sports.pack(anchor="w", padx=5, pady=2)

        # --- 2. 하위 섹션 (동적 생성) ---
        self.sections_container = ttk.Frame(self)
        self.sections_container.pack(padx=10, pady=5, fill="both", expand=True)

        self.create_section_frame("movies", "2. '영화' 하위 섹션 선택")
        self.create_section_frame("tv", "3. 'TV 프로그램' 하위 섹션 선택")
        self.create_section_frame("sports", "4. '스포츠' 하위 섹션 선택")

        # --- 3. 실행 버튼 ---
        self.start_button = ttk.Button(
            self, text="크롤링 시작", command=self.start_crawl_thread
        )
        self.start_button.pack(padx=10, pady=20, fill="x", ipady=5)

        # --- 초기 상태 설정 ---
        self.toggle_all()  # 처음엔 하위 섹션 모두 숨김

    def create_section_frame(self, key, title):
        """파일에서 섹션을 읽어 스크롤 가능한 프레임을 만듭니다."""

        frame = ttk.LabelFrame(self.sections_container, text=title)
        self.category_frames[key] = frame  # 나중에 숨기거나 보이기 위해 저장

        txt_path = self.FILE_PATHS[key][0]
        self.all_sections[key] = parse_section_file(txt_path)

        if not self.all_sections[key]:
            ttk.Label(frame, text=f"'{txt_path}' 파일을 찾을 수 없거나 비어있습니다.").pack(
                padx=5, pady=5
            )
            return

        # 스크롤 프레임 추가
        scroll_frame = ScrollableFrame(frame)
        scroll_frame.pack(fill="x", expand=True, padx=5, pady=5)

        # "전체" 체크박스
        all_key = f"{key}_all"
        self.vars[all_key] = tk.BooleanVar()
        cb_all = ttk.Checkbutton(
            scroll_frame.scrollable_frame,
            text=f"{title.split(' ')[1]} 전체 ({len(self.all_sections[key])}개)",
            variable=self.vars[all_key],
            command=lambda k=key: self.toggle_sub_sections(k),
        )
        cb_all.pack(anchor="w", padx=5, pady=2)

        ttk.Separator(scroll_frame.scrollable_frame, orient="horizontal").pack(
            fill="x", pady=5, padx=5
        )

        # 개별 섹션 체크박스
        for sec_name, sec_url in self.all_sections[key]:
            sec_key = f"{key}_{sec_name}"
            self.vars[sec_key] = tk.BooleanVar()
            cb = ttk.Checkbutton(
                scroll_frame.scrollable_frame,
                text=sec_name,
                variable=self.vars[sec_key],
            )
            cb.pack(anchor="w", padx=20, pady=2)

    def toggle_all(self):
        """ '전체 크롤링' 체크 시 다른 항목 체크/해제 """
        is_all = self.vars["all"].get()
        self.vars["movies"].set(is_all)
        self.vars["tv"].set(is_all)
        self.vars["sports"].set(is_all)
        self.toggle_category("movies")
        self.toggle_category("tv")
        self.toggle_category("sports")

    def toggle_category(self, key):
        """ 메인 카테고리 체크박스 상태에 따라 하위 섹션 프레임 숨김/표시 """
        if self.vars[key].get():
            self.category_frames[key].pack(fill="x", expand=True)
        else:
            self.category_frames[key].pack_forget()

    def toggle_sub_sections(self, key):
        """ "OO 전체" 체크 시 해당 카테고리 하위 섹션 모두 체크/해제 """
        is_all = self.vars[f"{key}_all"].get()
        for sec_name, _ in self.all_sections[key]:
            sec_key = f"{key}_{sec_name}"
            self.vars[sec_key].set(is_all)

    def start_crawl_thread(self):
        """ 크롤링 함수를 별도 스레드에서 실행 (GUI 멈춤 방지) """
        self.start_button.config(text="크롤링 진행 중...", state="disabled")

        # GUI에서 선택된 값을 실제 파일 경로로 변환
        self.crawl_jobs = []
        self.temp_files = []

        try:
            for key in ["movies", "tv", "sports"]:
                if not self.vars[key].get():
                    continue  # 메인 카테고리 스킵

                txt_path, out_xlsx = self.FILE_PATHS[key]

                if self.vars[f"{key}_all"].get():
                    # "OO 전체" 선택 시: 원본 파일 사용
                    self.crawl_jobs.append((txt_path, out_xlsx))
                else:
                    # "개별" 선택 시: 임시 파일 생성
                    selected_sections = []
                    for sec_name, sec_url in self.all_sections[key]:
                        if self.vars[f"{key}_{sec_name}"].get():
                            selected_sections.append((sec_name, sec_url))

                    if selected_sections:
                        temp_path = f"temp_{key}.txt"
                        self.temp_files.append(temp_path)

                        with open(temp_path, "w", encoding="utf-8") as f:
                            for name, url in selected_sections:
                                f.write(f"{name} : {url}\n")

                        self.crawl_jobs.append((temp_path, out_xlsx))

        except Exception as e:
            messagebox.showerror("작업 구성 오류", f"작업 목록 생성 중 오류:\n{e}")
            self.crawl_finished()
            return

        if not self.crawl_jobs:
            messagebox.showwarning("선택 오류", "크롤링할 카테고리나 섹션을 1개 이상 선택하세요.")
            self.crawl_finished()
            return

        # 별도 스레드에서 실제 크롤링 실행
        threading.Thread(target=self.run_crawl_logic, daemon=True).start()

    def run_crawl_logic(self):
        """ 실제 크롤링 로직 (별도 스레드에서 실행됨) """
        logger = make_logger()
        driver = None
        try:
            logger.info("=" * 60)
            logger.info("!!! [수동 로그인 필요] !!!")
            logger.info("크롤러가 메인 페이지로 이동합니다. 브라우저에서 [로그인]을 완료해주세요.")
            logger.info("로그인이 완료되면 GUI 창의 안내에 따라 진행해주세요.")
            logger.info("=" * 60)

            driver = make_driver(headless=False, block_images=False)
            driver.get("https://www.primevideo.com/")

            # [수정] input() 대신 messagebox로 로그인 대기
            messagebox.showinfo(
                "로그인 대기", "브라우저에서 로그인을 완료한 후, 이 창의 [확인] 버튼을 눌러주세요."
            )
            logger.info("로그인 대기 완료. 크롤링을 시작합니다.")

            for txt_path, out_xlsx in self.crawl_jobs:
                # run_category가 driver를 리턴하므로 갱신
                driver = run_category(
                    driver,
                    logger,
                    txt_path,
                    out_xlsx,
                    headless=False,
                    block_images=False,
                )

            messagebox.showinfo("크롤링 완료", "모든 작업이 완료되었습니다.")

        except Exception as e:
            logger.error(f"크롤링 중 심각한 오류 발생: {e}", exc_info=True)
            messagebox.showerror("오류 발생", f"크롤링 중 오류가 발생했습니다:\n{e}")
        finally:
            if driver:
                driver.quit()

            # 임시 파일 삭제
            for temp_path in self.temp_files:
                try:
                    os.remove(temp_path)
                    logger.info(f"임시 파일 삭제: {temp_path}")
                except Exception as e:
                    logger.warning(f"임시 파일 삭제 실패: {temp_path}, {e}")

            # GUI 버튼 원상 복구 (메인 스레드에서 실행)
            self.after(0, self.crawl_finished)

    def crawl_finished(self):
        self.start_button.config(text="크롤링 시작", state="normal")


if __name__ == "__main__":
    app = CrawlerGUI()
    app.mainloop()
