"""別枠履歴パネル — 2028年6月以降の未搭載を時系列採番で一覧表示。"""
import tkinter as tk
from tkinter import ttk
from datetime import date
from typing import Callable, Optional

from models import AppData, engine_by_id, hex_lighten

# 2028年6月の2450→2445載せ替えを「1回目」とする基準日
HISTORY_START = date(2028, 6, 1)

COLUMNS  = ("count", "engine", "start", "end", "days", "status", "req_dur")
COL_HEADS = {
    "count":    "回数",
    "engine":   "ガスタービン",
    "start":    "開始日",
    "end":      "終了日",
    "days":     "期間(日)",
    "status":   "点検種別 ✎",
    "req_dur":  "必要工期",
}
COL_W = {
    "count":   40,
    "engine":  84,
    "start":   82,
    "end":     82,
    "days":    64,
    "status":  225,
    "req_dur": 64,
}

_STATUS_COL  = "#6"  # 6番目の列
_REQDUR_COL  = "#7"  # 7番目の列


def _fmt_short(d: date) -> str:
    """YY年MM月DD日 形式（西暦下2桁）。"""
    return f"{d.year % 100:02d}年{d.month:02d}月{d.day:02d}日"


def _history_bars(app_data: AppData):
    """HISTORY_START以降の別枠バーを開始日順で返す。"""
    bars = [b for b in app_data.maintenance_bars if b.start >= HISTORY_START]
    bars.sort(key=lambda b: b.start)
    return bars


def _history_rows(app_data: AppData) -> list[tuple]:
    rows = []
    for i, b in enumerate(_history_bars(app_data), 1):
        span = (b.end - b.start).days + 1
        rows.append((i, b.engine_id, _fmt_short(b.start), _fmt_short(b.end), span,
                     b.status, b.required_duration))
    return rows


def _engine_color(app_data: AppData, engine_id: str) -> str:
    e = engine_by_id(app_data, engine_id)
    return e.color if e else "#888888"


class MaintenanceHistoryPanel(tk.Frame):
    def __init__(self, parent, app_data: AppData,
                 on_status_change: Optional[Callable[[int, str], None]] = None,
                 on_reqdur_change: Optional[Callable[[int, str], None]] = None,
                 **kw):
        super().__init__(parent, bg="white", **kw)
        self.app_data = app_data
        self._on_status_change = on_status_change
        self._on_reqdur_change = on_reqdur_change
        self._edit_entry: Optional[tk.Entry] = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        hdr = tk.Label(self, text="点検整備期間",
                       bg="white", fg="black",
                       font=("Meiryo UI", 9, "bold"), anchor="w")
        hdr.pack(fill="x", padx=6, pady=(4, 0))

        frame = tk.Frame(self, bg="white")
        frame.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        vsb = ttk.Scrollbar(frame, orient="vertical")
        vsb.pack(side="right", fill="y")

        self._tree = ttk.Treeview(
            frame,
            columns=COLUMNS,
            show="headings",
            height=6,
            selectmode="none",
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

        self._tree.bind("<Double-1>", self._on_double)
        self._tree.bind("<Motion>",   self._on_motion)
        self._tree.bind("<Leave>",    lambda _: self._tree.config(cursor=""))

    def _on_motion(self, event) -> None:
        col = self._tree.identify_column(event.x)
        self._tree.config(cursor="hand2" if col in (_STATUS_COL, _REQDUR_COL) else "")

    def _on_double(self, event) -> None:
        col  = self._tree.identify_column(event.x)
        item = self._tree.identify_row(event.y)
        if not item:
            return
        if col == _STATUS_COL:
            self._open_edit(item, col, val_idx=5,
                            callback=self._on_status_change)
        elif col == _REQDUR_COL:
            self._open_edit(item, col, val_idx=6,
                            callback=self._on_reqdur_change)

    def _open_edit(self, item: str, col: str, val_idx: int,
                   callback: Optional[Callable]) -> None:
        if self._edit_entry:
            self._edit_entry.destroy()
            self._edit_entry = None

        bbox = self._tree.bbox(item, column=col)
        if not bbox:
            return
        x, y, w, h = bbox

        children = self._tree.get_children()
        try:
            row_idx = list(children).index(item)
        except ValueError:
            return

        current = self._tree.item(item, "values")[val_idx]

        entry = tk.Entry(self._tree, justify="center",
                         font=("Meiryo UI", 8), bd=1, relief="solid",
                         bg="#FFFDE7")
        entry.insert(0, current)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        self._edit_entry = entry

        def _save(event=None):
            text = entry.get()
            entry.destroy()
            self._edit_entry = None
            if callback:
                callback(row_idx, text)

        entry.bind("<Return>",   _save)
        entry.bind("<KP_Enter>", _save)
        entry.bind("<Escape>",   lambda e: (entry.destroy(),
                                            setattr(self, "_edit_entry", None)))
        entry.bind("<FocusOut>", _save)

    def refresh(self) -> None:
        if self._edit_entry:
            self._edit_entry.destroy()
            self._edit_entry = None
        for row in self._tree.get_children():
            self._tree.delete(row)

        seen_tags: set[str] = set()
        for row in _history_rows(self.app_data):
            eid = row[1]
            tag = f"gt_{eid}"
            if tag not in seen_tags:
                color = hex_lighten(_engine_color(self.app_data, eid), 0.88)
                self._tree.tag_configure(tag, background=color, foreground="black")
                seen_tags.add(tag)
            self._tree.insert("", "end", values=row, tags=(tag,))

    def set_data(self, app_data: AppData) -> None:
        self.app_data = app_data
        self.refresh()
