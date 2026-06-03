"""All dialog windows for GanttApp."""
import copy
import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk, messagebox
from typing import Callable, List, Optional, Tuple

from models import (
    AppData, Engine, MachineBar, MaintenanceBar,
    ENGINE_IDS, MACHINE_IDS, MACHINE_NAMES, MAINTENANCE_STATUSES,
    PERIOD_START, PERIOD_END, DEFAULT_COLORS,
    days_in_month, dump_date8, parse_date8, engine_by_id,
)
from validation import validate


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _center(win: tk.Toplevel, parent: tk.Widget) -> None:
    win.update_idletasks()
    pw = parent.winfo_rootx() + parent.winfo_width()  // 2
    ph = parent.winfo_rooty() + parent.winfo_height() // 2
    ww = win.winfo_width()
    wh = win.winfo_height()
    win.geometry(f"+{pw - ww // 2}+{ph - wh // 2}")


class DateEntry(tk.Frame):
    """YYYY/MM/DD date entry composed of three spinboxes."""

    def __init__(self, parent, initial: date, **kw):
        super().__init__(parent, **kw)
        self._year_var  = tk.StringVar(value=str(initial.year))
        self._month_var = tk.StringVar(value=str(initial.month))
        self._day_var   = tk.StringVar(value=str(initial.day))

        tk.Spinbox(self, from_=2025, to=2034, width=5, textvariable=self._year_var
                   ).pack(side="left")
        tk.Label(self, text="/").pack(side="left")
        tk.Spinbox(self, from_=1, to=12, width=3, textvariable=self._month_var
                   ).pack(side="left")
        tk.Label(self, text="/").pack(side="left")
        tk.Spinbox(self, from_=1, to=31, width=3, textvariable=self._day_var
                   ).pack(side="left")

    def get(self) -> date:
        y = int(self._year_var.get())
        m = int(self._month_var.get())
        d = min(int(self._day_var.get()), days_in_month(y, m))
        return date(y, m, d)


def _label_entry(frame, text, row, initial="", width=20) -> tk.StringVar:
    tk.Label(frame, text=text, anchor="e").grid(row=row, column=0, sticky="e", padx=6, pady=4)
    var = tk.StringVar(value=str(initial))
    tk.Entry(frame, textvariable=var, width=width).grid(row=row, column=1, sticky="w", padx=6)
    return var


def _label_date(frame, text, row, initial: date) -> DateEntry:
    tk.Label(frame, text=text, anchor="e").grid(row=row, column=0, sticky="e", padx=6, pady=4)
    de = DateEntry(frame, initial)
    de.grid(row=row, column=1, sticky="w", padx=6)
    return de


def _label_combo(frame, text, row, values, initial="") -> ttk.Combobox:
    tk.Label(frame, text=text, anchor="e").grid(row=row, column=0, sticky="e", padx=6, pady=4)
    cb = ttk.Combobox(frame, values=values, state="readonly", width=14)
    cb.set(initial)
    cb.grid(row=row, column=1, sticky="w", padx=6)
    return cb


# ── New file wizard ────────────────────────────────────────────────────────────

class NewFileWizard(tk.Toplevel):
    """3-step wizard to create a new schedule from scratch."""

    def __init__(self, parent: tk.Widget, callback: Callable[[AppData], None]):
        super().__init__(parent)
        self.title("新規作成ウィザード")
        self.resizable(False, False)
        self.grab_set()
        self._callback = callback
        self._step     = 0

        # wizard data
        self._init_hours: dict[str, tk.StringVar] = {}
        self._initial_engines: dict[str, ttk.Combobox] = {}  # machine_id → combobox

        self._outer = tk.Frame(self)
        self._outer.pack(fill="both", expand=True, padx=20, pady=14)

        self._nav = tk.Frame(self)
        self._nav.pack(fill="x", padx=20, pady=(0, 14))

        self._btn_back = tk.Button(self._nav, text="< 戻る", command=self._back, width=9)
        self._btn_next = tk.Button(self._nav, text="次へ >", command=self._next,
                                   width=9, default="active")
        self._btn_back.pack(side="left")
        self._btn_next.pack(side="right")

        self._show_step1()
        _center(self, parent)

    # ── Step 1: initial hours ─────────────────────────────────────────────

    def _show_step1(self) -> None:
        self._clear()
        tk.Label(self._outer, text="Step 1 / 3  ―  初期稼働時間の設定",
                 font=("Meiryo UI", 11, "bold")).pack(anchor="w", pady=(0, 10))
        tk.Label(self._outer,
                 text="2025年1月時点の各エンジン累積稼働時間 (h) を入力してください。"
                 ).pack(anchor="w", pady=(0, 8))

        frame = tk.Frame(self._outer)
        frame.pack(anchor="w")
        for i, eid in enumerate(ENGINE_IDS):
            tk.Label(frame, text=f"エンジン {eid}:", width=14, anchor="e"
                     ).grid(row=i, column=0, padx=6, pady=4)
            var = tk.StringVar(value="0")
            self._init_hours[eid] = var
            tk.Entry(frame, textvariable=var, width=12
                     ).grid(row=i, column=1, padx=6, pady=4)

        self._btn_back.config(state="disabled")
        self._btn_next.config(text="次へ >")

    # ── Step 2: initial placement ─────────────────────────────────────────

    def _show_step2(self) -> None:
        self._clear()
        tk.Label(self._outer, text="Step 2 / 3  ―  初期配置の設定",
                 font=("Meiryo UI", 11, "bold")).pack(anchor="w", pady=(0, 10))
        tk.Label(self._outer,
                 text="2025年1月1日時点で各本体に搭載するエンジンを選択してください。"
                 ).pack(anchor="w", pady=(0, 8))

        frame = tk.Frame(self._outer)
        frame.pack(anchor="w")
        for i, mid in enumerate(MACHINE_IDS):
            tk.Label(frame, text=f"{MACHINE_NAMES[mid]}:", width=8, anchor="e"
                     ).grid(row=i, column=0, padx=6, pady=4)
            cb = ttk.Combobox(frame, values=ENGINE_IDS, state="readonly", width=10)
            cb.current(i % len(ENGINE_IDS))
            cb.grid(row=i, column=1, padx=6, pady=4)
            self._initial_engines[mid] = cb

        self._btn_back.config(state="normal")
        self._btn_next.config(text="次へ >")

    # ── Step 3: confirm ───────────────────────────────────────────────────

    def _show_step3(self) -> None:
        self._clear()
        tk.Label(self._outer, text="Step 3 / 3  ―  確認",
                 font=("Meiryo UI", 11, "bold")).pack(anchor="w", pady=(0, 10))
        tk.Label(self._outer, text="以下の設定でスケジュールを作成します。"
                 ).pack(anchor="w", pady=(0, 8))

        frame = tk.Frame(self._outer)
        frame.pack(anchor="w")
        row = 0
        for eid in ENGINE_IDS:
            tk.Label(frame, text=f"エンジン {eid} 初期時間:"
                     ).grid(row=row, column=0, sticky="e", padx=6, pady=2)
            tk.Label(frame, text=f"{self._init_hours[eid].get()} h"
                     ).grid(row=row, column=1, sticky="w", padx=6)
            row += 1
        for mid in MACHINE_IDS:
            eid = self._initial_engines[mid].get()
            tk.Label(frame, text=f"{MACHINE_NAMES[mid]}:"
                     ).grid(row=row, column=0, sticky="e", padx=6, pady=2)
            tk.Label(frame, text=f"エンジン {eid}"
                     ).grid(row=row, column=1, sticky="w", padx=6)
            row += 1

        self._btn_back.config(state="normal")
        self._btn_next.config(text="作成")

    # ── Navigation ────────────────────────────────────────────────────────

    def _clear(self) -> None:
        for w in self._outer.winfo_children():
            w.destroy()

    def _back(self) -> None:
        self._step -= 1
        [self._show_step1, self._show_step2, self._show_step3][self._step]()

    def _next(self) -> None:
        if self._step == 0:
            if not self._validate_step1():
                return
            self._step = 1
            self._show_step2()
        elif self._step == 1:
            if not self._validate_step2():
                return
            self._step = 2
            self._show_step3()
        elif self._step == 2:
            self._create()

    def _validate_step1(self) -> bool:
        for eid, var in self._init_hours.items():
            try:
                v = float(var.get())
                if v < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("入力エラー",
                                     f"エンジン {eid} の稼働時間が不正です。", parent=self)
                return False
        return True

    def _validate_step2(self) -> bool:
        chosen = [cb.get() for cb in self._initial_engines.values()]
        if len(set(chosen)) != len(chosen):
            messagebox.showerror("入力エラー",
                                 "各本体に異なるエンジンを割り当ててください。", parent=self)
            return False
        return True

    def _create(self) -> None:
        engines = [
            Engine(id=eid, color=DEFAULT_COLORS[eid],
                   initial_hours=float(self._init_hours[eid].get()))
            for eid in ENGINE_IDS
        ]

        # Each machine gets the chosen engine for the full period
        machine_bars: list[MachineBar] = []
        for mid in MACHINE_IDS:
            eid = self._initial_engines[mid].get()
            machine_bars.append(MachineBar(
                machine_id=mid, engine_id=eid,
                start=PERIOD_START, end=PERIOD_END,
                operation_rate=0.8,
            ))

        app_data = AppData(engines=engines, machine_bars=machine_bars, maintenance_bars=[])
        self.destroy()
        self._callback(app_data)


# ── Edit machine bar dialog ────────────────────────────────────────────────────

class EditMachineBarDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget, bar: MachineBar,
                 on_save: Callable[[MachineBar], None]):
        super().__init__(parent)
        self.title(f"本体バー編集 — エンジン {bar.engine_id}")
        self.resizable(False, False)
        self.grab_set()
        self._bar    = bar
        self._on_save = on_save

        frame = tk.LabelFrame(self, text="バー情報", padx=10, pady=10)
        frame.pack(padx=16, pady=12, fill="both")

        tk.Label(frame, text="エンジン:", anchor="e"
                 ).grid(row=0, column=0, sticky="e", padx=6, pady=4)
        tk.Label(frame, text=bar.engine_id, anchor="w"
                 ).grid(row=0, column=1, sticky="w", padx=6)

        self._start = _label_date(frame, "開始日:", 1, bar.start)
        self._end   = _label_date(frame, "終了日:", 2, bar.end)

        tk.Label(frame, text="稼働率(%):", anchor="e"
                 ).grid(row=3, column=0, sticky="e", padx=6, pady=4)
        self._rate = tk.StringVar(value=str(int(bar.operation_rate * 100)))
        tk.Spinbox(frame, from_=0, to=100, textvariable=self._rate, width=6
                   ).grid(row=3, column=1, sticky="w", padx=6)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=(0, 12))
        tk.Button(btn_frame, text="キャンセル", command=self.destroy, width=10
                  ).pack(side="left", padx=6)
        tk.Button(btn_frame, text="保存", command=self._save,
                  width=10, default="active").pack(side="right", padx=6)

        _center(self, parent)

    def _save(self) -> None:
        try:
            start = self._start.get()
            end   = self._end.get()
            rate  = int(self._rate.get()) / 100.0
        except Exception as e:
            messagebox.showerror("エラー", str(e), parent=self)
            return
        if end < start:
            messagebox.showerror("エラー", "終了日が開始日より前です。", parent=self)
            return
        if start < PERIOD_START or end > PERIOD_END:
            messagebox.showerror("エラー", "対象期間外です。", parent=self)
            return
        self._bar.start          = start
        self._bar.end            = end
        self._bar.operation_rate = rate
        self._on_save(self._bar)
        self.destroy()


# ── Edit maintenance bar dialog ───────────────────────────────────────────────

class EditMaintenanceBarDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget, bar: MaintenanceBar,
                 on_save: Callable[[MaintenanceBar], None]):
        super().__init__(parent)
        self.title(f"別枠バー編集 — エンジン {bar.engine_id}")
        self.resizable(False, False)
        self.grab_set()
        self._bar     = bar
        self._on_save = on_save

        frame = tk.LabelFrame(self, text="バー情報", padx=10, pady=10)
        frame.pack(padx=16, pady=12, fill="both")

        tk.Label(frame, text="エンジン:", anchor="e"
                 ).grid(row=0, column=0, sticky="e", padx=6, pady=4)
        tk.Label(frame, text=bar.engine_id, anchor="w"
                 ).grid(row=0, column=1, sticky="w", padx=6)

        self._start  = _label_date(frame, "開始日:", 1, bar.start)
        self._end    = _label_date(frame, "終了日:", 2, bar.end)
        self._status = _label_combo(frame, "状態:", 3, MAINTENANCE_STATUSES, bar.status)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=(0, 12))
        tk.Button(btn_frame, text="キャンセル", command=self.destroy, width=10
                  ).pack(side="left", padx=6)
        tk.Button(btn_frame, text="保存", command=self._save,
                  width=10, default="active").pack(side="right", padx=6)

        _center(self, parent)

    def _save(self) -> None:
        start  = self._start.get()
        end    = self._end.get()
        status = self._status.get()
        if not status:
            messagebox.showerror("エラー", "状態を選択してください。", parent=self)
            return
        if end < start:
            messagebox.showerror("エラー", "終了日が開始日より前です。", parent=self)
            return
        if start < PERIOD_START or end > PERIOD_END:
            messagebox.showerror("エラー", "対象期間外です。", parent=self)
            return
        self._bar.start  = start
        self._bar.end    = end
        self._bar.status = status
        self._on_save(self._bar)
        self.destroy()


# ── Add maintenance bar dialog ────────────────────────────────────────────────

class AddMaintenanceBarDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget,
                 on_save: Callable[[MaintenanceBar], None]):
        super().__init__(parent)
        self.title("別枠バー追加")
        self.resizable(False, False)
        self.grab_set()
        self._on_save = on_save

        frame = tk.LabelFrame(self, text="新規別枠バー", padx=10, pady=10)
        frame.pack(padx=16, pady=12, fill="both")

        self._engine = _label_combo(frame, "エンジン:", 0, ENGINE_IDS, ENGINE_IDS[0])
        self._start  = _label_date(frame, "開始日:", 1, PERIOD_START)
        self._end    = _label_date(frame, "終了日:", 2, date(2025, 3, 31))
        self._status = _label_combo(frame, "状態:", 3, MAINTENANCE_STATUSES,
                                    MAINTENANCE_STATUSES[0])

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=(0, 12))
        tk.Button(btn_frame, text="キャンセル", command=self.destroy, width=10
                  ).pack(side="left", padx=6)
        tk.Button(btn_frame, text="追加", command=self._save,
                  width=10, default="active").pack(side="right", padx=6)

        _center(self, parent)

    def _save(self) -> None:
        eid    = self._engine.get()
        start  = self._start.get()
        end    = self._end.get()
        status = self._status.get()
        if not status:
            messagebox.showerror("エラー", "状態を選択してください。", parent=self)
            return
        if end < start:
            messagebox.showerror("エラー", "終了日が開始日より前です。", parent=self)
            return
        if start < PERIOD_START or end > PERIOD_END:
            messagebox.showerror("エラー", "対象期間外です。", parent=self)
            return
        self._on_save(MaintenanceBar(engine_id=eid, start=start, end=end, status=status))
        self.destroy()


# ── Insert engine (exchange) dialog ───────────────────────────────────────────

class InsertEngineDialog(tk.Toplevel):
    """Split a machine bar at a given date and assign a new engine."""

    def __init__(self, parent: tk.Widget, app_data: AppData,
                 bar_idx: int, split_date: date,
                 on_save: Callable[[int, date, str], None]):
        super().__init__(parent)
        self.title("エンジン交換")
        self.resizable(False, False)
        self.grab_set()
        self._on_save = on_save
        self._bar_idx = bar_idx

        bar = app_data.machine_bars[bar_idx]

        frame = tk.LabelFrame(self, text="エンジン交換設定", padx=10, pady=10)
        frame.pack(padx=16, pady=12, fill="both")

        tk.Label(frame, text="本体:", anchor="e"
                 ).grid(row=0, column=0, sticky="e", padx=6, pady=4)
        tk.Label(frame, text=MACHINE_NAMES[bar.machine_id], anchor="w"
                 ).grid(row=0, column=1, sticky="w", padx=6)

        tk.Label(frame, text="現在のエンジン:", anchor="e"
                 ).grid(row=1, column=0, sticky="e", padx=6, pady=4)
        tk.Label(frame, text=bar.engine_id, anchor="w"
                 ).grid(row=1, column=1, sticky="w", padx=6)

        self._split_date = _label_date(frame, "交換日:", 2,
                                       _clamp(split_date, bar.start + timedelta(days=1), bar.end))

        # Available engines: not on any machine at the exchange period
        avail = self._available_engines(app_data, bar)
        self._new_engine = _label_combo(frame, "新エンジン:", 3, avail,
                                        avail[0] if avail else "")

        if not avail:
            tk.Label(frame, text="⚠ 使用可能なエンジンがありません",
                     fg="red").grid(row=4, column=0, columnspan=2, pady=4)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=(0, 12))
        tk.Button(btn_frame, text="キャンセル", command=self.destroy, width=10
                  ).pack(side="left", padx=6)
        save_btn = tk.Button(btn_frame, text="交換", command=self._save,
                             width=10, default="active",
                             state="normal" if avail else "disabled")
        save_btn.pack(side="right", padx=6)

        _center(self, parent)

    def _available_engines(self, app_data: AppData, current_bar: MachineBar) -> List[str]:
        # Engines not assigned to any machine for any overlapping period
        used = set()
        for b in app_data.machine_bars:
            if b.machine_id != current_bar.machine_id:
                if b.start <= current_bar.end and current_bar.start <= b.end:
                    used.add(b.engine_id)
        used.add(current_bar.engine_id)  # exclude current engine
        return [eid for eid in ENGINE_IDS if eid not in used]

    def _save(self) -> None:
        split = self._split_date.get()
        new_e = self._new_engine.get()
        if not new_e:
            messagebox.showerror("エラー", "エンジンを選択してください。", parent=self)
            return
        self._on_save(self._bar_idx, split, new_e)
        self.destroy()


def _clamp(d: date, lo: date, hi: date) -> date:
    if d < lo:
        return lo
    if d > hi:
        return hi
    return d


# ── Settings / color editor ───────────────────────────────────────────────────

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget, app_data: AppData,
                 on_save: Callable[[AppData], None]):
        super().__init__(parent)
        self.title("設定")
        self.resizable(False, False)
        self.grab_set()
        self._app_data = copy.deepcopy(app_data)
        self._on_save  = on_save

        frame = tk.LabelFrame(self, text="エンジン色設定", padx=10, pady=10)
        frame.pack(padx=16, pady=12, fill="both")

        self._color_vars: dict[str, tk.StringVar] = {}
        for i, eng in enumerate(self._app_data.engines):
            tk.Label(frame, text=f"エンジン {eng.id}:", anchor="e", width=14
                     ).grid(row=i, column=0, sticky="e", padx=6, pady=4)
            var = tk.StringVar(value=eng.color)
            self._color_vars[eng.id] = var
            entry = tk.Entry(frame, textvariable=var, width=10)
            entry.grid(row=i, column=1, sticky="w", padx=4)
            preview = tk.Label(frame, text="  ", bg=eng.color, relief="solid", width=3)
            preview.grid(row=i, column=2, padx=4)
            var.trace_add("write", lambda *_, v=var, lbl=preview: self._update_preview(v, lbl))
            tk.Button(frame, text="選択…",
                      command=lambda e=eng.id: self._pick_color(e)
                      ).grid(row=i, column=3, padx=4)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=(0, 12))
        tk.Button(btn_frame, text="キャンセル", command=self.destroy, width=10
                  ).pack(side="left", padx=6)
        tk.Button(btn_frame, text="保存", command=self._save,
                  width=10, default="active").pack(side="right", padx=6)

        _center(self, parent)

    def _update_preview(self, var: tk.StringVar, label: tk.Label) -> None:
        try:
            label.config(bg=var.get())
        except Exception:
            pass

    def _pick_color(self, eid: str) -> None:
        from tkinter import colorchooser
        initial = self._color_vars[eid].get()
        color = colorchooser.askcolor(color=initial, title=f"エンジン {eid} の色", parent=self)
        if color and color[1]:
            self._color_vars[eid].set(color[1])

    def _save(self) -> None:
        for eng in self._app_data.engines:
            eng.color = self._color_vars[eng.id].get()
        self._on_save(self._app_data)
        self.destroy()
