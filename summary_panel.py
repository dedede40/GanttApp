"""Summary panel showing engine statistics."""
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from models import AppData, ENGINE_IDS, engine_by_id, hex_lighten

# 初期稼働時間列の列番号（1始まり）
_INIT_H_COL = "#2"


class SummaryPanel(tk.Frame):
    def __init__(self, parent, app_data: AppData,
                 on_init_h_change: Optional[Callable[[str, float], None]] = None,
                 **kw):
        super().__init__(parent, bg="white", **kw)
        self.app_data         = app_data
        self._on_init_h_change = on_init_h_change
        self._edit_entry: Optional[tk.Entry] = None

        cols = ("engine", "init_h", "accum_h", "total_days")
        hdrs = ("ガスタービン", "初期稼働時間(h) ✎", "累積稼働時間(h)", "総稼働日数(日)")

        tk.Label(self, text="集計", bg="white", fg="black",
                 font=("Meiryo UI", 10, "bold"),
                 padx=8, pady=4, anchor="w", relief="flat", bd=0,
                 ).pack(fill="x", side="top")

        frame = tk.Frame(self, bg="white")
        frame.pack(fill="both", expand=True, padx=6, pady=6)

        self._tree = ttk.Treeview(
            frame, columns=cols, show="headings",
            height=5, selectmode="none",
        )
        style = ttk.Style()
        style.configure("Summary.Treeview",
                        rowheight=26, font=("Meiryo UI", 9),
                        foreground="black", background="white",
                        fieldbackground="white")
        style.configure("Summary.Treeview.Heading",
                        font=("Meiryo UI", 9, "bold"),
                        foreground="black", background="white",
                        relief="flat")
        style.map("Summary.Treeview.Heading",
                  background=[("active", "#DDDDDD")])
        style.map("Summary.Treeview",
                  foreground=[("selected", "black")],
                  background=[("selected", "#DDDDDD")])
        self._tree.configure(style="Summary.Treeview")

        col_widths = {"engine": 70, "init_h": 118, "accum_h": 110, "total_days": 95}
        for col, hdr in zip(cols, hdrs):
            self._tree.heading(col, text=hdr)
            self._tree.column(col, width=col_widths[col], minwidth=col_widths[col],
                              anchor="center", stretch=False)

        self._tree.pack(side="left", fill="both", expand=True)

        self._tree.bind("<Double-1>",  self._on_double)
        self._tree.bind("<Motion>",    self._on_motion)
        self._tree.bind("<Leave>",     lambda _: self._tree.config(cursor=""))

        self.refresh()

    # ── データ更新 ────────────────────────────────────────────────────────

    def set_data(self, app_data: AppData) -> None:
        self.app_data = app_data
        self.refresh()

    def refresh(self) -> None:
        if self._edit_entry:
            self._edit_entry.destroy()
            self._edit_entry = None
        for row in self._tree.get_children():
            self._tree.delete(row)

        for eid in ENGINE_IDS:
            eng    = engine_by_id(self.app_data, eid)
            init_h = eng.initial_hours if eng else 0.0
            mbars  = [b for b in self.app_data.machine_bars if b.engine_id == eid]
            total_days = sum(b.days for b in mbars)
            accum_h    = init_h + sum(b.hours for b in mbars)
            swaps      = len(mbars)
            mnts       = [b for b in self.app_data.maintenance_bars if b.engine_id == eid]
            maint_cnt  = len(mnts)
            color      = eng.color if eng else "#888888"
            tag        = f"eng_{eid}"
            self._tree.tag_configure(tag,
                                     background=hex_lighten(color, 0.88),
                                     foreground="black")
            self._tree.insert(
                "", "end",
                values=(eid, f"{init_h:,.0f}", f"{accum_h:,.0f}", f"{total_days:,}"),
                tags=(tag,),
            )

    # ── マウスイベント ────────────────────────────────────────────────────

    def _on_motion(self, event) -> None:
        col = self._tree.identify_column(event.x)
        self._tree.config(cursor="hand2" if col == _INIT_H_COL else "")

    def _on_double(self, event) -> None:
        col  = self._tree.identify_column(event.x)
        item = self._tree.identify_row(event.y)
        if col != _INIT_H_COL or not item:
            return
        self._open_edit(item)

    # ── インライン編集エントリ ────────────────────────────────────────────

    def _open_edit(self, item: str) -> None:
        if self._edit_entry:
            self._edit_entry.destroy()

        bbox = self._tree.bbox(item, column=_INIT_H_COL)
        if not bbox:
            return
        x, y, w, h = bbox

        # 現在値（カンマ除去）
        current = self._tree.item(item, "values")[1].replace(",", "")
        engine_id = self._tree.item(item, "values")[0]

        entry = tk.Entry(self._tree, justify="center",
                         font=("Meiryo UI", 9), bd=1, relief="solid",
                         bg="#FFFDE7")   # 薄い黄色で「編集中」を視覚化
        entry.insert(0, current)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        self._edit_entry = entry

        def _save(event=None):
            text = entry.get().strip()
            entry.destroy()
            self._edit_entry = None
            try:
                val = float(text)
                if val < 0:
                    return
            except ValueError:
                return
            if self._on_init_h_change:
                self._on_init_h_change(engine_id, val)

        entry.bind("<Return>",   _save)
        entry.bind("<KP_Enter>", _save)
        entry.bind("<Escape>",   lambda e: (entry.destroy(), setattr(self, "_edit_entry", None)))
        entry.bind("<FocusOut>", _save)
