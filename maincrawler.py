import os
from pandas.errors import EmptyDataError
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
from src.crawler.serieamania_crawler import serieamania_main_crw
from src.crawler.fb_crawler import fb_main_crw
from src.crawler.instagram_crawler import instagram_main_crw
# from src.crawler.kbdio_crawler import kbdio_main_crw
# from src.crawler.kbdiom_crawler import kbdiom_main_crw
from src.processing.process_file import process_file
from tkinter import filedialog

# 검색어 엑셀 파일에서 검색어 목록 로드
pd_search = pd.read_excel("(언진) 2025 매체사 검색어 목록.xlsx", sheet_name='검색어 목록')
searchs = pd_search['검색어명']

# 크롤링 중단 신호를 위한 전역 이벤트 객체
stop_event = Event()

# 기본 기간 설정 (수정 가능)
start_date = datetime.strptime('2025-11-1', '%Y-%m-%d').date()
end_date = datetime.strptime('2025-11-30', '%Y-%m-%d').date()

# 사이트명과 해당 사이트의 크롤러 함수를 매핑
crawlers = {
    "뽐뿌": pp_main_crw,
    "클리앙": clien_main_crw,
    "인벤": inven_main_crw,
    "루리웹": rw_main_crw,
    "오늘의유머": todayhumor_main_crw,
    "네이트판": paan_main_crw,
    # "인스티즈": instiz_main_crw,  # 사용 안 함
    "보배드림": bobaedream_main_crw,
    # "아카라이브": arca_main_crw,  # 사용 안 함
    "일간베스트": ilbe_main_crw,
    "웃긴대학": humoruniv_main_crw,
    "82쿡": cook82_main_crw,
    "오르비": orbi_main_crw,
    "개드립": dogdrip_main_crw,
    "DVD프라임": dp_main_crw,
    "사커라인": scline_main_crw,
    "동사로마닷컴": dongsaroma_main_crw,
    "포모스": fomos_main_crw,
    # "짱공유닷컴": jjang0u_main_crw,  # 비활성화
    "블라인드": blind_main_crw,
    "엠엘비파크": mlb_main_crw,
    "디시인사이드": dc_main_crw,
    "에펨코리아": fm_main_crw,
    # "더쿠": dq_main_crw,
    # "와이고수": ygosu_main_crw,
    # "이토랜드": etoland_main_crw,
    "세리에매니아": serieamania_main_crw,
    "페이스북": fb_main_crw,
    "인스타그램": instagram_main_crw
    # "케이비디오": kbdio_main_crw,
    # "티스토리 케이비디오": kbdiom_main_crw
}

class TextRedirector:
    """tk.Text 위젯에 print 출력을 리디렉션하기 위한 클래스"""
    def __init__(self, widget):
        self.widget = widget

    def write(self, msg):
        self.widget.after(0, self._write_gui, msg)

    def _write_gui(self, msg):
        self.widget.config(state='normal')
        self.widget.insert(tk.END, msg)
        self.widget.see(tk.END)
        self.widget.config(state='disabled')

    def flush(self):
        pass  # 버퍼 비우기용 (필수 구현)

def run_crawler(gui):
    """크롤링 실행 버튼 클릭 시 비동기로 스레드 실행"""
    stop_event.clear()
    threading.Thread(target=lambda: crawler_threaded(gui)).start()

def stop_crawler(gui):
    """중단 이벤트 트리거"""
    stop_event.set()
    gui.status_label.config(text="⛔ 크롤링 중단 요청됨")

def crawler_threaded(gui):
    """크롤링 + 전처리까지 수행하는 메인 함수"""
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
            return  # 중단 요청 시 이후 전처리 생략

        gui.status_label.config(text="전처리 중...")
        today = datetime.now().strftime("%y%m%d")

        if not os.path.exists(f'결과/1.전처리'):
            os.makedirs(f'결과/1.전처리')

        input_path = f"결과/{site}/{site}_raw data_{today}.csv"
        if is_empty_csv(input_path):
            gui.status_label.config(text="ℹ️ 크롤링 결과가 0건이어서 전처리할 데이터가 없습니다.")
            print(f"[INFO] 전처리 스킵(빈 파일): {input_path}")
            return

        process_file(
            search_excel_path="(언진) 2025 매체사 검색어 목록.xlsx",
            input_csv_template=input_path,
            output_excel_path=f"결과/1.전처리/{site}_전처리_{today}.xlsx",
            target_year=end_date.year,
            target_month=end_date.month
        )
        gui.status_label.config(text="✅ 전체 완료")
    except Exception as e:
        gui.status_label.config(text=f"❌ 에러 발생: {e}")

def is_empty_csv(path: str) -> bool:
    """
    CSV 파일이 비어있거나, 헤더도 없는 경우 True 반환
    - 처리할 필요 없음
    - 유효성 체크 필수
    """
    try:
        if not os.path.exists(path):
            return True
        if os.path.getsize(path) == 0:
            return True
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            first = f.readline().strip()
        if first == "":
            return True
        return False
    except Exception:
        # 오류 발생 시 전처리 방지 목적으로 True 반환
        return True

def run_preprocess(gui):
    """
    수동 CSV 전처리 실행 함수
    - GUI에서 끝 날짜 받아 연월 추출
    - 파일명에서 사이트 추론 시도 (실패 시 GUI 값 사용)
    - TODO: 사이트명 추론 정확도 개선 필요
    """
    try:
        end_str = gui.end_entry.get()
        try:
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        except Exception:
            gui.status_label.config(text="❌ 날짜 형식 오류(끝 날짜). YYYY-MM-DD 형식으로 입력하세요.")
            return

        csv_path = filedialog.askopenfilename(
            title="전처리할 raw CSV 선택",
            initialdir=os.path.join(os.getcwd(), "결과"),
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if not csv_path:
            gui.status_label.config(text="⚠️ 파일 선택이 취소되었습니다.")
            return

        base = os.path.basename(csv_path)
        if "_raw data_" in base:
            site = base.split("_raw data_")[0]
        else:
            site = gui.site_combo.get() or "SITE"

        today_out = datetime.now().strftime("%y%m%d")
        out_dir = os.path.join("결과", "1.전처리")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{site}_전처리_{today_out}.xlsx")

        gui.status_label.config(text=f"🧹 전처리 중... ({os.path.basename(csv_path)})")
        print(f"[INFO] 전처리 입력: {csv_path}")
        print(f"[INFO] 전처리 출력: {out_path}")

        if is_empty_csv(csv_path):
            gui.status_label.config(text="ℹ️ 전처리할 내용이 없습니다. (크롤링 결과 0건 또는 파일이 비어있음)")
            print(f"[INFO] 전처리 스킵(빈 파일): {csv_path}")
            return

        try:
            process_file(
                search_excel_path="(언진) 2025 매체사 검색어 목록.xlsx",
                input_csv_template=csv_path,
                output_excel_path=out_path,
                target_year=end_date.year,
                target_month=end_date.month
            )
        except EmptyDataError:
            gui.status_label.config(text="ℹ️ 전처리할 내용이 없습니다. (빈 CSV)")
            print(f"[INFO] 전처리 스킵(EmptyDataError): {csv_path}")
            return
        except ValueError as ve:
            if "No columns to parse from file" in str(ve):
                gui.status_label.config(text="ℹ️ 전처리할 내용이 없습니다. (헤더/컬럼 없음)")
                print(f"[INFO] 전처리 스킵(No columns to parse): {csv_path}")
                return
            raise

        gui.status_label.config(text=f"✅ 전처리 완료: {out_path}")
        print(f"[DONE] 전처리 완료 -> {out_path}")

    except Exception as e:
        gui.status_label.config(text=f"❌ 전처리 중 에러: {e}")
        print(f"[ERROR] 전처리 실패: {e}")

# GUI 실행 진입점
if __name__ == "__main__":
    root = tk.Tk()
    gui = CrawlerGUI(root, list(crawlers.keys()))
    sys.stdout = TextRedirector(gui.log_text)

    tk.Button(root, text="크롤링 시작", command=lambda: run_crawler(gui)).pack(pady=20)
    tk.Button(root, text="크롤링 중단", command=lambda: stop_crawler(gui)).pack(pady=5)
    tk.Button(root, text="전처리 실행(파일 선택)", command=lambda: run_preprocess(gui)).pack(pady=12)

    root.mainloop()
