"""別枠履歴パネル — 2028年6月以降の未搭載を時系列採番で一覧表示。"""
import tkinter as tk
from tkinter import ttk
from datetime import date

from models import AppData

# 2028年6月の2450→2445載せ替えを「1回目」とする基準日
HISTORY_START = date(2028, 6, 1)

COLUMNS = ("count", "engine", "days", "status")
COL_HEADS = {"count": "回数", "engine": "タービン", "days": "別枠期間(日)", "status": "点検種別"}
COL_W     = {"count": 46, "engine": 72, "days": 88, "status": 90}


def _history_rows(app_data: AppData) -> list[tuple]:
    bars = [b for b in app_data.maintenance_bars if b.start >= HISTORY_START]
    bars.sort(key=lambda b: b.start)
    rows = []
    for i, b in enumerate(bars, 1):
        span = (b.end - b.start).days + 1
        rows.append((i, b.engine_id, span, b.status))
    return rows


class MaintenanceHistoryPanel(tk.Frame):
    def __init__(self, parent, app_data: AppData, **kw):
        super().__init__(parent, bg="white", **kw)
        self.app_data = app_data
        self._build()
        self.refresh()

    def _build(self) -> None:
        # ヘッダ
        hdr = tk.Label(self, text="別枠履歴（2028年6月〜）",
                       bg="white", fg="black",
                       font=("Meiryo UI", 9, "bold"), anchor="w")
        hdr.pack(fill="x", padx=6, pady=(4, 0))

        # Treeview + scrollbar
        frame = tk.Frame(self, bg="white")
        frame.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        vsb = ttk.Scrollbar(frame, orient="vertical")
        vsb.pack(side="right", fill="y")

        self._tree = ttk.Treeview(
            frame,
            columns=COLUMNS,
            show="headings",
            height=6,
            yscrollcommand=vsb.set,
        )
        vsb.config(command=self._tree.yview)

        style = ttk.Style()
        style.configure("History.Treeview",
                        background="white", foreground="black",
                        fieldbackground="white", rowheight=20,
                        font=("Meiryo UI", 8))
        style.configure("History.Treeview.Heading",
                        background="#DDDDDD", foreground="black",
                        font=("Meiryo UI", 8, "bold"))
        self._tree.configure(style="History.Treeview")

        for col in COLUMNS:
            self._tree.heading(col, text=COL_HEADS[col])
            self._tree.column(col, width=COL_W[col], anchor="center", stretch=False)

        self._tree.pack(side="left", fill="both", expand=True)

    def refresh(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)
        for row in _history_rows(self.app_data):
            self._tree.insert("", "end", values=row)

    def set_data(self, app_data: AppData) -> None:
        self.app_data = app_data
        self.refresh()
