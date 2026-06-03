"""Summary panel showing engine statistics."""
import tkinter as tk
from tkinter import ttk

from models import AppData, ENGINE_IDS, PERIOD_START, PERIOD_END, engine_by_id, hex_lighten


class SummaryPanel(tk.Frame):
    def __init__(self, parent, app_data: AppData, **kw):
        super().__init__(parent, bg="white", **kw)
        self.app_data = app_data

        cols = ("engine", "init_h", "accum_h", "total_days", "swaps", "maint_cnt")
        hdrs = ("ガスタービン", "初期稼働時間(h)", "累積稼働時間(h)",
                "総稼働日数(日)", "交換回数", "メンテナンス回数")

        tk.Label(self, text="集計", bg="white", fg="black",
                 font=("Meiryo UI", 10, "bold"),
                 padx=8, pady=4, anchor="w", relief="flat",
                 bd=0,
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

        col_widths = {"engine": 70, "init_h": 110, "accum_h": 110,
                      "total_days": 95, "swaps": 70, "maint_cnt": 110}
        for col, hdr in zip(cols, hdrs):
            self._tree.heading(col, text=hdr)
            self._tree.column(col, width=col_widths[col], minwidth=col_widths[col],
                              anchor="center", stretch=False)

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
            self._tree.tag_configure(tag,
                                     background=hex_lighten(color, 0.88),
                                     foreground="black")

            self._tree.insert(
                "", "end",
                values=(eid, f"{init_h:,.0f}", f"{accum_h:,.0f}",
                        f"{total_days:,}", swaps, maint_cnt),
                tags=(tag,),
            )


