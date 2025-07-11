import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
from datetime import datetime
from crawler.pp_crawler import pp_main_crw
from crawler.clien_crawler import clien_main_crw
from crawler.inven_crawler import inven_main_crw
from crawler.todayhumor_crawler import todayhumor_main_crw
from crawler.paan_crawler import paan_main_crw
from crawler.instiz_crawler import instiz_main_crw
from crawler.bobaedream_crawler import bobaedream_main_crw
from crawler.rw_crawler import rw_main_crw
from crawler.arca_crawler import arca_main_crw
from crawler.ilbe_crawler import ilbe_main_crw
from crawler.humoruniv_crawler import humoruniv_main_crw
from crawler.cook82_crawler import cook82_main_crw
from crawler.orbi_crawler import orbi_main_crw
from crawler.dogdrip_crawler import dogdrip_main_crw
from crawler.dp_crawler import dp_main_crw
from crawler.scline_crawler import scline_main_crw
from crawler.dongsaroma_crawler import dongsaroma_main_crw
from crawler.fomos_crawler import fomos_main_crw
from crawler.jjang0u_crawler import jjang0u_main_crw
from crawler.blind_crawler import blind_main_crw
from crawler.mlb_crawler import mlb_main_crw
from crawler.dc_crawler import dc_main_crw
from crawler.fm_crawler import fm_main_crw
from crawler.dq_crawler import dq_main_crw
from crawler.kbdio_crawler import kbdio_main_crw
from crawler.kbdiom_crawler import kbdiom_main_crw
from processing.process_file import process_file

# 검색어 추출
pd_search = pd.read_excel("../(언진) 2025 매체사 검색어 목록.xlsx", sheet_name='검색어 목록')
searchs = pd_search['검색어명']

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
    "케이비디오":kbdio_main_crw,
    "티스토리 케이비디오":kbdiom_main_crw

}

# 크롤러 실행 함수
def run_crawler():
    site = site_combo.get()
    start_str = start_entry.get()
    end_str = end_entry.get()

    # 유효성 검사
    if site not in crawlers:
        messagebox.showerror("오류", "사이트를 선택해주세요.")
        return

    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    except ValueError:
        messagebox.showerror("오류", "날짜 형식이 올바르지 않습니다. 예: 2025-06-01")
        return

    today = datetime.now().strftime("%y%m%d")
    crw_func = crawlers[site]

    try:
        status_label.config(text=f"[{site}] 크롤링 중...")
        root.update_idletasks()

        crw_func(searchs, start_date, end_date)

        status_label.config(text="전처리 중...")
        root.update_idletasks()

        filtered = process_file(
            search_excel_path="../(언진) 2025 매체사 검색어 목록.xlsx",
            input_csv_template=f"../결과/{site}/{site}_raw data_{today}.csv",
            output_excel_path=f"../결과/1.전처리/{site}_전처리_{today}.xlsx",
            target_year=end_date.year,
            target_month=end_date.month
        )

        messagebox.showinfo("완료", f"[{site}] 전체 완료!")
        status_label.config(text="전체 완료")
    except Exception as e:
        messagebox.showerror("에러 발생", str(e))
        status_label.config(text="에러 발생")

# GUI 구성
root = tk.Tk()
root.title("웹 크롤러 GUI")
root.geometry("400x300")

# 사이트 선택
tk.Label(root, text="사이트 선택:").pack(pady=5)
site_combo = ttk.Combobox(root, values=list(crawlers.keys()), state="readonly", width=35)
site_combo.set("사이트를 선택하세요")
site_combo.pack()

# 시작일
tk.Label(root, text="시작일 (YYYY-MM-DD):").pack(pady=5)
start_entry = tk.Entry(root)
start_entry.insert(0, "2025-06-01")
start_entry.pack()

# 종료일
tk.Label(root, text="종료일 (YYYY-MM-DD):").pack(pady=5)
end_entry = tk.Entry(root)
end_entry.insert(0, "2025-06-30")
end_entry.pack()

# 실행 버튼
tk.Button(root, text="크롤링 시작", command=run_crawler).pack(pady=20)

# 상태 표시
status_label = tk.Label(root, text="")
status_label.pack()

# 로그 텍스트 박스
log_frame = tk.Frame(root)
log_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)

log_text = tk.Text(log_frame, height=8, wrap=tk.WORD, state='disabled')
log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

scrollbar = tk.Scrollbar(log_frame, command=log_text.yview)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

log_text.config(yscrollcommand=scrollbar.set)

root.mainloop()