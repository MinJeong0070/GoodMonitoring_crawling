# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
import threading
import pandas as pd
import os
from datetime import datetime, date
from pathlib import Path

# tkcalendar가 없어도 실행되도록 폴백
try:
    from tkcalendar import DateEntry
except ImportError:
    DateEntry = None

from copy112_crawler import run_crawl, STATUS_GROUPS

ACCOUNTS_XLSX = "copy112_계정.xlsx"
OUTPUT_DIR = "output"


class CrawlerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("신고내역 크롤링")
        self.root.geometry("940x640")

        # 상태 플래그
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.is_paused = False
        self.worker_thread = None  # 동시 실행 방지용

        # UI
        self._build_filters()
        self._build_accounts_panel()
        self._build_controls()
        self._build_log()
        self.load_accounts()

    # ── 필터 영역 ─────────────────────────────────────────────
    def _build_filters(self):
        frm = ttk.LabelFrame(self.root, text="필터")
        frm.pack(fill="x", padx=10, pady=8)

        ttk.Label(frm, text="시작일").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        self.start_date = self._build_date_widget(frm)
        self.start_date.grid(row=0, column=1, padx=6, pady=6)

        ttk.Label(frm, text="종료일").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        self.end_date = self._build_date_widget(frm)
        self.end_date.grid(row=0, column=3, padx=6, pady=6)

        ttk.Label(frm, text="처리현황").grid(row=0, column=4, padx=6, pady=6, sticky="w")
        self.status_var = tk.StringVar(value="전체 현황")
        self.cmb_status = ttk.Combobox(
            frm,
            textvariable=self.status_var,
            values=list(STATUS_GROUPS.keys()),
            state="readonly",
            width=20,
        )
        self.cmb_status.grid(row=0, column=5, padx=6, pady=6)

    def _build_date_widget(self, parent):
        if DateEntry is not None:
            return DateEntry(parent, date_pattern="yyyy-mm-dd", width=12)
        e = ttk.Entry(parent, width=14)
        e.insert(0, date.today().strftime("%Y-%m-%d"))
        return e

    def _get_date_value(self, widget):
        try:
            if (DateEntry is not None) and isinstance(widget, DateEntry):
                return widget.get_date()
            txt = widget.get().strip()
            if not txt:
                return None
            return pd.to_datetime(txt, errors="coerce").date()
        except Exception:
            return None

    # ── 계정 선택 영역 ─────────────────────────────────────────
    def _build_accounts_panel(self):
        frm = ttk.LabelFrame(self.root, text="계정 선택")
        frm.pack(fill="both", padx=10, pady=6, expand=True)

        top = ttk.Frame(frm)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="검색(성명/아이디)").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_accounts_list())
        ttk.Entry(top, textvariable=self.search_var, width=28).pack(side="left", padx=6)
        ttk.Button(top, text="계정 새로고침", command=self.load_accounts).pack(side="left", padx=4)
        ttk.Button(top, text="전체 선택", command=lambda: self.select_all(True)).pack(side="left", padx=4)
        ttk.Button(top, text="전체 해제", command=lambda: self.select_all(False)).pack(side="left", padx=4)

        body = ttk.Frame(frm)
        body.pack(fill="both", expand=True, padx=6, pady=6)

        self.lst_accounts = tk.Listbox(body, selectmode="extended")
        self.lst_accounts.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(body, orient="vertical", command=self.lst_accounts.yview)
        sb.pack(side="left", fill="y")
        self.lst_accounts.configure(yscrollcommand=sb.set)

        right = ttk.Frame(body)
        right.pack(side="right", fill="y", padx=6)
        self.sel_count_lbl = ttk.Label(right, text="선택 0명")
        self.sel_count_lbl.pack(anchor="e")
        self.lst_accounts.bind("<<ListboxSelect>>", lambda e: self._update_sel_count())

    # ── 실행/일시정지/종료 버튼 ─────────────────────────────────
    def _build_controls(self):
        frm = ttk.Frame(self.root)
        frm.pack(fill="x", padx=10, pady=6)
        self.btn_start = ttk.Button(frm, text="시작", command=self.start_crawl, width=12)
        self.btn_start.pack(side="left", padx=6)
        self.btn_pause = ttk.Button(frm, text="중지(일시정지)", command=self.pause_crawl, width=14)
        self.btn_pause.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(frm, text="종료", command=self.stop_crawl, width=10)
        self.btn_stop.pack(side="left", padx=6)

    def _build_log(self):
        frm = ttk.LabelFrame(self.root, text="로그")
        frm.pack(fill="both", padx=10, pady=6, expand=True)
        self.txt_log = ScrolledText(frm, height=12)
        self.txt_log.pack(fill="both", expand=True)

    # ── 계정 로딩/검색/선택 ─────────────────────────────────────
    def load_accounts(self):
        self.lst_accounts.delete(0, tk.END)
        if not os.path.exists(ACCOUNTS_XLSX):
            messagebox.showerror("오류", f"계정 파일이 없습니다: {ACCOUNTS_XLSX}")
            self.accounts = []
            return
        try:
            df = pd.read_excel(ACCOUNTS_XLSX).rename(columns={"비번": "비밀번호"})
        except Exception as e:
            messagebox.showerror("오류", f"계정 파일을 불러올 수 없습니다: {e}")
            self.accounts = []
            return

        for col in ["성명", "아이디", "비밀번호"]:
            if col not in df.columns:
                if col == "성명" and "이름" in df.columns:
                    df["성명"] = df["이름"]
                else:
                    df[col] = ""
        self.accounts = df[["성명", "아이디", "비밀번호"]].to_dict(orient="records")
        self._refresh_accounts_list()

    def _refresh_accounts_list(self):
        keyword = (self.search_var.get() or "").strip().lower()
        self.lst_accounts.delete(0, tk.END)
        for acc in self.accounts:
            name = str(acc.get("성명", "") or "")
            uid = str(acc.get("아이디", "") or "")
            text = f"{name} ({uid})" if name else uid
            if keyword:
                if (keyword in name.lower()) or (keyword in uid.lower()):
                    self.lst_accounts.insert(tk.END, text)
            else:
                self.lst_accounts.insert(tk.END, text)
        self._update_sel_count()

    def select_all(self, flag=True):
        self.lst_accounts.select_clear(0, tk.END)
        if flag:
            self.lst_accounts.select_set(0, tk.END)
        self._update_sel_count()

    def _update_sel_count(self):
        self.sel_count_lbl.config(text=f"선택 {len(self.lst_accounts.curselection())}명")

    # ── 실행/일시정지/종료 ─────────────────────────────────────
    def start_crawl(self):
        # 동시 실행 가드
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("경고", "이미 실행 중입니다.")
            return

        self.stop_event.clear()
        self.pause_event.clear()
        self.is_paused = False

        start = self._get_date_value(self.start_date)
        end = self._get_date_value(self.end_date)
        if start and end and start > end:
            messagebox.showwarning("기간 오류", "시작일이 종료일보다 늦습니다.")
            return

        status = self.status_var.get()
        sel_idx = self.lst_accounts.curselection()
        if not sel_idx:
            messagebox.showwarning("경고", "계정을 선택하세요.")
            return
        selected_accounts = [self.accounts[i] for i in sel_idx]

        self.btn_start.config(state="disabled")  # 시작 중복 방지

        self.worker_thread = threading.Thread(
            target=self._crawl_thread,
            args=(selected_accounts, start, end, status),
            daemon=True
        )
        self.worker_thread.start()

    def _crawl_thread(self, selected_accounts, start, end, status):
        def log(msg):
            self.txt_log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            self.txt_log.see(tk.END)

        df, saved_path = run_crawl(
            selected_accounts=selected_accounts,
            start_date=start, end_date=end,
            status_group=status,
            output_dir=OUTPUT_DIR,
            detailed_for_done=True,   # ‘신고 접수 완료’일 때 상세 수집
            log_callback=log,
            stop_event=self.stop_event,
            pause_event=self.pause_event
        )

        if saved_path:
            log(f"작업 완료. 파일: {saved_path}")
        else:
            log("작업 완료. (수집 0건이어서 파일 저장 생략)")

        self.btn_start.config(state="normal")  # 버튼 복구

    def pause_crawl(self):
        if not self.pause_event.is_set():
            self.pause_event.set()
            self.is_paused = True
            self._log_ui("크롤링 일시정지")
        else:
            self.pause_event.clear()
            self.is_paused = False
            self._log_ui("크롤링 재개")

    def stop_crawl(self):
        self.stop_event.set()
        self._log_ui("종료 신호 전송")

    def _log_ui(self, msg):
        self.txt_log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.txt_log.see(tk.END)


if __name__ == "__main__":
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    app = CrawlerGUI(root)
    root.mainloop()
