"""Summary panel showing engine statistics."""
import tkinter as tk
from tkinter import ttk

from models import AppData, ENGINE_IDS, PERIOD_START, PERIOD_END, engine_by_id


class SummaryPanel(tk.Frame):
    def __init__(self, parent, app_data: AppData, **kw):
        super().__init__(parent, bg="#F0F4FA", **kw)
        self.app_data = app_data

        cols = ("engine", "init_h", "accum_h", "total_days", "swaps", "maint_cnt")
        hdrs = ("エンジン", "初期稼働時間(h)", "累積稼働時間(h)",
                "総稼働日数(日)", "交換回数", "メンテナンス回数")

        tk.Label(self, text="集計", bg="#3B6EA5", fg="white",
                 font=("Meiryo UI", 10, "bold"),
                 padx=8, pady=4, anchor="w"
                 ).pack(fill="x", side="top")

        frame = tk.Frame(self, bg="#F0F4FA")
        frame.pack(fill="both", expand=True, padx=6, pady=6)

        self._tree = ttk.Treeview(
            frame, columns=cols, show="headings",
            height=5, selectmode="none",
        )
        style = ttk.Style()
        style.configure("Summary.Treeview", rowheight=26, font=("Meiryo UI", 9))
        style.configure("Summary.Treeview.Heading", font=("Meiryo UI", 9, "bold"))
        self._tree.configure(style="Summary.Treeview")

        for col, hdr in zip(cols, hdrs):
            width = 140 if col == "engine" else 130
            self._tree.heading(col, text=hdr)
            self._tree.column(col, width=width, anchor="center")

        sb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.refresh()

    def set_data(self, app_data: AppData) -> None:
        self.app_data = app_data
        self.refresh()

    def refresh(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)

        for eid in ENGINE_IDS:
            eng = engine_by_id(self.app_data, eid)
            init_h = eng.initial_hours if eng else 0.0

            mbars = [b for b in self.app_data.machine_bars if b.engine_id == eid]
            total_days  = sum(b.days for b in mbars)
            accum_h     = init_h + sum(b.hours for b in mbars)
            swaps       = len(mbars)

            mnts   = [b for b in self.app_data.maintenance_bars if b.engine_id == eid]
            maint_cnt = len(mnts)

            color = eng.color if eng else "#888888"
            tag   = f"eng_{eid}"
            self._tree.tag_configure(tag, background=_hex_lighten(color, 0.88))

            self._tree.insert(
                "", "end",
                values=(eid, f"{init_h:,.0f}", f"{accum_h:,.0f}",
                        f"{total_days:,}", swaps, maint_cnt),
                tags=(tag,),
            )


def _hex_lighten(hex_color: str, factor: float) -> str:
    """Blend hex_color toward white by factor (0=original, 1=white)."""
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return "#FFFFFF"
