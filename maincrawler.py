import os
import sys
import tkinter as tk
import threading
from threading import Event
import pandas as pd
from datetime import datetime
from src.gui.main_gui import CrawlerGUI
from src.crawler.pp_crawler import pp_main_crw
from src.crawler.clien_crawler import clien_main_crw
from src.crawler.inven_crawler import inven_main_crw
from src.crawler.todayhumor_crawler import todayhumor_main_crw
from src.crawler.paan_crawler import paan_main_crw
from src.crawler.instiz_crawler import instiz_main_crw
from src.crawler.bobaedream_crawler import bobaedream_main_crw
from src.crawler.rw_crawler import rw_main_crw
from src.crawler.arca_crawler import arca_main_crw
from src.crawler.ilbe_crawler import ilbe_main_crw
from src.crawler.humoruniv_crawler import humoruniv_main_crw
from src.crawler.cook82_crawler import cook82_main_crw
from src.crawler.orbi_crawler import orbi_main_crw
from src.crawler.dogdrip_crawler import dogdrip_main_crw
from src.crawler.dp_crawler import dp_main_crw
from src.crawler.scline_crawler import scline_main_crw
from src.crawler.dongsaroma_crawler import dongsaroma_main_crw
from src.crawler.fomos_crawler import fomos_main_crw
from src.crawler.jjang0u_crawler import jjang0u_main_crw
from src.crawler.blind_crawler import blind_main_crw
from src.crawler.mlb_crawler import mlb_main_crw
from src.crawler.dc_crawler import dc_main_crw
from src.crawler.fm_crawler import fm_main_crw
from src.crawler.dq_crawler import dq_main_crw
from src.crawler.ygosu_crawler import ygosu_main_crw
from src.crawler.etoland_crawler import etoland_main_crw
# from src.crawler.kbdio_crawler import kbdio_main_crw
# from src.crawler.kbdiom_crawler import kbdiom_main_crw
from src.processing.process_file import process_file

# 검색어 추출
pd_search = pd.read_excel("(언진) 2025 매체사 검색어 목록.xlsx", sheet_name='검색어 목록')
searchs = pd_search['검색어명']

# 전역 중단 플래그
stop_event = Event()

# 기간 설정
start_date = datetime.strptime('2025-6-1', '%Y-%m-%d').date()
end_date = datetime.strptime('2025-6-30', '%Y-%m-%d').date()

# 사이트별 함수 매핑
crawlers = {
    "뽐뿌": pp_main_crw,
    "클리앙": clien_main_crw,
    "인벤": inven_main_crw,
    "루리웹": rw_main_crw,
    "오늘의유머": todayhumor_main_crw,
    "네이트판": paan_main_crw,
    "인스티즈": instiz_main_crw,
    "보배드림" : bobaedream_main_crw,
    "아카라이브": arca_main_crw,
    "일간베스트": ilbe_main_crw,
    "웃긴대학": humoruniv_main_crw,
    "82쿡": cook82_main_crw,
    "오르비": orbi_main_crw,
    "개드립": dogdrip_main_crw,
    "DVD프라임":dp_main_crw,
    "사커라인": scline_main_crw,
    "동사로마닷컴":dongsaroma_main_crw,
    "포모스": fomos_main_crw,
    "짱공유닷컴":jjang0u_main_crw,
    "블라인드": blind_main_crw,
    "엠엘비파크":mlb_main_crw,
    "디시인사이드":dc_main_crw,
    "에펨코리아": fm_main_crw,
    "더쿠":dq_main_crw,
    "와이고수":ygosu_main_crw,
    "이토랜드":etoland_main_crw
    # "케이비디오":kbdio_main_crw,
    # "티스토리 케이비디오":kbdiom_main_crw

}

class TextRedirector:
    def __init__(self, widget):
        self.widget = widget
    def write(self, msg):
        self.widget.after(0, self._write_gui, msg)
    def _write_gui(self, msg):
        self.widget.config(state='normal')
        self.widget.insert(tk.END, msg)
        self.widget.see(tk.END)
        self.widget.config(state='disabled')
    def flush(self): pass

def run_crawler(gui):
    stop_event.clear()  # 플래그 초기화
    threading.Thread(target=lambda: crawler_threaded(gui)).start()


def stop_crawler(gui):
    stop_event.set()  # 플래그 설정
    gui.status_label.config(text="⛔ 크롤링 중단 요청됨")

def crawler_threaded(gui):
    site = gui.site_combo.get()
    start_str = gui.start_entry.get()
    end_str = gui.end_entry.get()

    if site not in crawlers:
        gui.status_label.config(text="❌ 사이트를 선택해주세요.")
        return

    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    except:
        gui.status_label.config(text="❌ 날짜 형식 오류.")
        return

    try:
        gui.status_label.config(text=f"[{site}] 크롤링 중...")
        crw_func = crawlers[site]
        crw_func(searchs, start_date, end_date, stop_event)
        if stop_event.is_set():
            return
        gui.status_label.config(text="전처리 중...")
        today = datetime.now().strftime("%y%m%d")
        if not os.path.exists(f'결과/1.전처리'):
            os.makedirs(f'결과/1.전처리')

        process_file(
            search_excel_path="(언진) 2025 매체사 검색어 목록.xlsx",
            input_csv_template=f"결과/{site}/{site}_raw data_{today}.csv",
            output_excel_path=f"결과/1.전처리/{site}_전처리_{today}.xlsx",
            target_year=end_date.year,
            target_month=end_date.month
        )
        gui.status_label.config(text="✅ 전체 완료")
    except Exception as e:
        gui.status_label.config(text=f"❌ 에러 발생: {e}")

# 실행
if __name__ == "__main__":
    root = tk.Tk()
    gui = CrawlerGUI(root, list(crawlers.keys()))
    sys.stdout = TextRedirector(gui.log_text)

    tk.Button(root, text="크롤링 시작", command=lambda: run_crawler(gui)).pack(pady=20)
    tk.Button(root, text="크롤링 중단", command=lambda: stop_crawler(gui)).pack(pady=5)
    root.mainloop()