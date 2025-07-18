import tkinter as tk
from tkinter import ttk
from tkcalendar import DateEntry
from datetime import datetime

class CrawlerGUI:
    def __init__(self, root, site_list):
        self.root = root
        self.root.title("웹 크롤러 GUI")
        self.root.geometry("500x400")

        self.should_stop = False

        self.site_combo = self.create_site_selector(site_list)
        self.start_entry = self.create_date_entry("시작일 (YYYY-MM-DD):", "2025-06-01")
        self.end_entry = self.create_date_entry("종료일 (YYYY-MM-DD):", "2025-06-30")
        self.status_label = self.create_status_label()
        self.log_text = self.create_log_text()

    def create_site_selector(self, site_list):
        tk.Label(self.root, text="사이트 선택:").pack(pady=5)
        combo = ttk.Combobox(self.root, values=site_list, state="readonly", width=35)
        combo.set("사이트를 선택하세요")
        combo.pack()
        return combo

    def create_date_entry(self, label_text, default_value):
        tk.Label(self.root, text=label_text).pack(pady=5)
        date = datetime.strptime(default_value, "%Y-%m-%d").date()
        entry = DateEntry(self.root, width=20, date_pattern='yyyy-mm-dd')
        entry.set_date(date)
        entry.pack()
        return entry

    def create_status_label(self):
        label = tk.Label(self.root, text="")
        label.pack()
        return label

    def stop_crawler(self):
        self.should_stop = True
        self.status_label.config(text="⛔ 크롤링 중단 요청됨")


    def create_log_text(self):
        frame = tk.Frame(self.root)
        frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)

        text = tk.Text(frame, height=8, wrap=tk.WORD, state='disabled')
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)

        return text
