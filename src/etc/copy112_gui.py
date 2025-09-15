# -*- coding: utf-8 -*-
import threading
import time
import pandas as pd
from datetime import datetime, date
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

# 달력
try:
    from tkcalendar import DateEntry
except ImportError:
    DateEntry = None

from copy112_crawler import run_crawl, STATUS_GROUPS

ACCOUNTS_XLSX = "../copy112_계정.xlsx"   # 필요시 경로 조정
OUTPUT_DIR = "./output"                  # 저장 폴더

class Copy112GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("COPY112 크롤러 (기간·현황·계정 선택 GUI)")
        self.geometry("980x640")

        # 상태
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.worker = None
        self.is_paused = False

        # 데이터
        self.accounts_df = pd.DataFrame()
        self.filtered_indices = []  # 필터링된 계정 인덱스
        self._load_accounts()

        # UI
        self._build_filters()
        self._build_accounts_selector()
        self._build_controls()
        self._build_log()

        self._refresh_accounts_list()

    # ───────────────────────── UI 빌드 ───────────────────────── #
    def _build_filters(self):
        frm = ttk.LabelFrame(self, text="필터")
        frm.pack(fill="x", padx=10, pady=8)

        # 기간
        ttk.Label(frm, text="시작일").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(frm, text="종료일").grid(row=0, column=2, padx=6, pady=6, sticky="w")

        default_start = date.today().replace(day=max(1, date.today().day-29))
        default_end = date.today()

        if DateEntry:
            self.start_date = DateEntry(frm, width=12, year=default_start.year, month=default_start.month, day=default_start.day)
            self.end_date = DateEntry(frm, width=12, year=default_end.year, month=default_end.month, day=default_end.day)
        else:
            # fallback: 일반 Entry (YYYY-MM-DD)
            self.start_date = ttk.Entry(frm, width=14)
            self.start_date.insert(0, default_start.strftime("%Y-%m-%d"))
            self.end_date = ttk.Entry(frm, width=14)
            self.end_date.insert(0, default_end.strftime("%Y-%m-%d"))

        self.start_date.grid(row=0, column=1, padx=6, pady=6)
        self.end_date.grid(row=0, column=3, padx=6, pady=6)

        # 처리현황
        ttk.Label(frm, text="처리현황").grid(row=0, column=4, padx=6, pady=6, sticky="w")
        self.status_var = tk.StringVar()
        self.status_combo = ttk.Combobox(frm, textvariable=self.status_var, state="readonly", width=22,
                                         values=list(STATUS_GROUPS.keys()))
        self.status_combo.grid(row=0, column=5, padx=6, pady=6)
        self.status_combo.set("전체 현황")

    def _build_accounts_selector(self):
        frm = ttk.LabelFrame(self, text="계정 선택")
        frm.pack(fill="both", padx=10, pady=8, expand=True)

        # 검색
        top = ttk.Frame(frm)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="검색(성명/아이디)").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_accounts_list())
        ttk.Entry(top, textvariable=self.search_var, width=32).pack(side="left", padx=6)
        ttk.Button(top, text="계정 새로고침", command=self._load_accounts_and_refresh).pack(side="left", padx=4)
        ttk.Button(top, text="전체 선택", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(top, text="전체 해제", command=self._deselect_all).pack(side="left", padx=4)

        # 리스트
        middle = ttk.Frame(frm)
        middle.pack(fill="both", expand=True, padx=6, pady=6)

        self.accounts_list = tk.Listbox(middle, selectmode="extended")
        self.accounts_list.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(middle, orient="vertical", command=self.accounts_list.yview)
        sb.pack(side="left", fill="y")
        self.accounts_list.configure(yscrollcommand=sb.set)

        # 우측 정보
        right = ttk.Frame(frm)
        right.pack(fill="y", side="right", padx=6, pady=6)
        self.sel_count_lbl = ttk.Label(right, text="선택 0명")
        self.sel_count_lbl.pack(anchor="e")

        # 선택 변화 업데이트
        self.accounts_list.bind("<<ListboxSelect>>", lambda e: self._update_sel_count())

    def _build_controls(self):
        frm = ttk.Frame(self)
        frm.pack(fill="x", padx=10, pady=6)

        self.btn_start = ttk.Button(frm, text="시작", command=self.on_start)
        self.btn_pause = ttk.Button(frm, text="중지(일시정지)", command=self.on_pause)
        self.btn_stop = ttk.Button(frm, text="종료(저장 후 중단)", command=self.on_stop)

        self.btn_start.pack(side="left", padx=4)
        self.btn_pause.pack(side="left", padx=4)
        self.btn_stop.pack(side="left", padx=4)

    def _build_log(self):
        frm = ttk.LabelFrame(self, text="로그")
        frm.pack(fill="both", padx=10, pady=6, expand=True)

        self.log_text = ScrolledText(frm, height=12)
        self.log_text.pack(fill="both", expand=True)

    # ───────────────────────── 데이터/선택 관리 ───────────────────────── #
    def _load_accounts(self):
        try:
            df = pd.read_excel(ACCOUNTS_XLSX).rename(columns={"비번":"비밀번호"})
            # 기대 컬럼: 성명, 아이디, 비밀번호
            for col in ["성명","아이디","비밀번호"]:
                if col not in df.columns:
                    if col == "성명" and "이름" in df.columns:
                        df["성명"] = df["이름"]
                    else:
                        df[col] = ""
            self.accounts_df = df[["성명","아이디","비밀번호"]].copy()
        except Exception as e:
            messagebox.showerror("계정 로드 실패", f"엑셀({ACCOUNTS_XLSX}) 읽기 실패: {e}")
            self.accounts_df = pd.DataFrame(columns=["성명","아이디","비밀번호"])

    def _load_accounts_and_refresh(self):
        self._load_accounts()
        self._refresh_accounts_list()

    def _refresh_accounts_list(self):
        query = (self.search_var.get() or "").strip().lower()
        self.accounts_list.delete(0, tk.END)
        self.filtered_indices = []
        for idx, row in self.accounts_df.iterrows():
            name = str(row.get("성명",""))
            uid = str(row.get("아이디",""))
            text = f"{name} ({uid})" if name else uid
            if query:
                if (query in name.lower()) or (query in uid.lower()):
                    self.accounts_list.insert(tk.END, text)
                    self.filtered_indices.append(idx)
            else:
                self.accounts_list.insert(tk.END, text)
                self.filtered_indices.append(idx)
        self._update_sel_count()

    def _update_sel_count(self):
        self.sel_count_lbl.config(text=f"선택 {len(self.accounts_list.curselection())}명")

    def _select_all(self):
        self.accounts_list.select_set(0, tk.END)
        self._update_sel_count()

    def _deselect_all(self):
        self.accounts_list.select_clear(0, tk.END)
        self._update_sel_count()

    # ───────────────────────── 버튼 핸들러 ───────────────────────── #
    def on_start(self):
        if self.worker and self.worker.is_alive():
            if self.is_paused:
                self.pause_event.clear()
                self.is_paused = False
                self._log("재개합니다.")
            else:
                messagebox.showinfo("진행 중", "이미 실행 중입니다.")
            return

        if not self._validate_inputs():
            return

        selected_accounts = self._collect_selected_accounts()
        if not selected_accounts:
            messagebox.showwarning("선택 필요", "최소 1개 이상의 계정을 선택해 주세요.")
            return

        start_date, end_date = self._get_period()
        status_group = self.status_var.get()

        self.stop_event.clear()
        self.pause_event.clear()
        self.is_paused = False

        def work():
            try:
                # ‘신고 접수 완료’일 때만 상세 진입 허용
                detail_flag = (status_group == "신고 접수 완료")
                _, final_path = run_crawl(
                    selected_accounts=selected_accounts,
                    start_date=start_date,
                    end_date=end_date,
                    status_group=status_group,
                    excel_path=ACCOUNTS_XLSX,
                    output_dir=OUTPUT_DIR,
                    detailed_for_done=detail_flag,
                    log_callback=self._log,
                    stop_event=self.stop_event,
                    pause_event=self.pause_event,
                )
                if final_path:
                    self._log(f"작업 완료. 파일: {final_path}")
                else:
                    self._log("작업 완료(최종 파일 저장 경로 없음).")
            except Exception as e:
                self._log(f"오류 발생: {e}")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self._log("작업을 시작합니다.")

    def on_pause(self):
        if not self.worker or not self.worker.is_alive():
            messagebox.showinfo("대기", "실행 중인 작업이 없습니다.")
            return
        if not self.is_paused:
            self.pause_event.set()
            self.is_paused = True
            self._log("일시정지했습니다. 다시 시작하려면 '시작' 버튼을 누르세요.")
        else:
            self._log("이미 일시정지 상태입니다. '시작'으로 재개하세요.")

    def on_stop(self):
        if not self.worker or not self.worker.is_alive():
            self.destroy()
            return
        if messagebox.askyesno("종료 확인", "현재까지 수집된 데이터를 저장하고 종료할까요?"):
            self.stop_event.set()
            self._log("종료 신호를 보냈습니다. 잠시만 기다려 주세요.")

            def wait_and_close():
                while self.worker and self.worker.is_alive():
                    time.sleep(0.2)
                self._log("작업이 종료되었습니다.")
                self.destroy()

            threading.Thread(target=wait_and_close, daemon=True).start()

    # ───────────────────────── 유틸 ───────────────────────── #
    def _get_period(self):
        def to_date(x):
            if DateEntry and isinstance(x, DateEntry):
                return x.get_date()
            try:
                return pd.to_datetime(x.get().strip()).date()
            except:
                return None
        s = to_date(self.start_date)
        e = to_date(self.end_date)
        return s, e

    def _validate_inputs(self):
        s, e = self._get_period()
        if s and e and s > e:
            messagebox.showwarning("기간 오류", "시작일이 종료일보다 늦습니다.")
            return False
        if self.status_var.get() not in STATUS_GROUPS:
            messagebox.showwarning("현황 오류", "처리현황을 선택하세요.")
            return False
        return True

    def _collect_selected_accounts(self):
        sel = self.accounts_list.curselection()
        if not sel:
            return []
        picked = []
        for list_idx in sel:
            df_idx = self.filtered_indices[list_idx]
            row = self.accounts_df.loc[df_idx]
            picked.append({"성명": row.get("성명",""), "아이디": row.get("아이디",""), "비밀번호": row.get("비밀번호","")})
        return picked

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        if int(self.log_text.index('end-1c').split('.')[0]) > 400:
            self.log_text.delete('1.0', '200.0')

if __name__ == "__main__":
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    app = Copy112GUI()
    app.mainloop()
