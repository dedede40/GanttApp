"""GanttApp main window and entry point."""
import copy
import json
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

from models import (AppData, MachineBar, MaintenanceBar,
                    MACHINE_IDS, PERIOD_START, PERIOD_END, ENGINE_IDS, engine_by_id)
from data_io import load_json, save_json
from validation import validate
from gantt_canvas import GanttCanvas
from summary_panel import SummaryPanel
from dialogs import (
    NewFileWizard, EditMachineBarDialog, EditMaintenanceBarDialog,
    AddMaintenanceBarDialog, InsertEngineDialog, SettingsDialog,
)
from maintenance_history import MaintenanceHistoryPanel

# ── 未搭載バー自動生成 ────────────────────────────────────────────────────────

def _generate_maintenance_bars(app_data: AppData) -> list[MaintenanceBar]:
    """機体バーから各タービンの空き期間を計算し未搭載バーリストを返す。"""
    on_machine: dict[str, list[tuple[date, date]]] = {eid: [] for eid in ENGINE_IDS}
    for b in app_data.machine_bars:
        on_machine[b.engine_id].append((b.start, b.end))

    def merge(ivs):
        ivs = sorted(ivs)
        merged: list[list] = []
        for s, e in ivs:
            if merged and s <= merged[-1][1] + timedelta(days=1):
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        return merged

    maint: list[MaintenanceBar] = []
    for eid in ENGINE_IDS:
        segs = merge(on_machine[eid]) if on_machine[eid] else []
        free_start = PERIOD_START
        for seg_s, seg_e in segs:
            if free_start < seg_s:
                maint.append(MaintenanceBar(
                    engine_id=eid,
                    start=free_start,
                    end=seg_s - timedelta(days=1),
                    status="6k点検",
                ))
            free_start = seg_e + timedelta(days=1)
        if free_start <= PERIOD_END:
            maint.append(MaintenanceBar(
                engine_id=eid,
                start=free_start,
                end=PERIOD_END,
                status="6k点検",
            ))
    return maint


# ── Paths ─────────────────────────────────────────────────────────────────────

def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


APP_DIR     = _app_dir()
DATA_DIR    = APP_DIR / "data"
SAVE_DIR    = APP_DIR / "save"
DEFAULT_JSON = DATA_DIR / "default.json"
PREFS_FILE  = APP_DIR / ".gantt_prefs.json"


def _load_prefs() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_prefs(data: dict) -> None:
    try:
        PREFS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ── Main window ───────────────────────────────────────────────────────────────

class GanttApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GanttApp")
        self.minsize(820, 600)
        self.geometry("1280x700")
        self._win_resize_job = None
        self.bind("<Configure>", self._on_win_resize)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._app_data: AppData | None = None
        self._file_path: str | None = None
        self._modified  = False

        self._build_menu()
        self._build_ui()

        # Ensure save dir exists
        SAVE_DIR.mkdir(parents=True, exist_ok=True)

        # Auto-load last file
        prefs = _load_prefs()
        last  = prefs.get("last_file")
        if last and Path(last).exists():
            self._load_file(last)
        else:
            self._show_empty()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = tk.Menu(self)
        self.config(menu=mb)

        file_menu = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="ファイル", menu=file_menu)
        file_menu.add_command(label="新規作成…",       command=self._new_file,         accelerator="Ctrl+N")
        file_menu.add_command(label="開く…",          command=self._open_file,        accelerator="Ctrl+O")
        file_menu.add_command(label="初期計画に戻す", command=self._load_default)
        file_menu.add_separator()
        file_menu.add_command(label="上書き保存",     command=self._save_file,        accelerator="Ctrl+S")
        file_menu.add_command(label="名前を付けて保存…", command=self._save_as,       accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="終了",           command=self._on_close)

        edit_menu = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="編集", menu=edit_menu)
        edit_menu.add_command(label="別枠バーを追加…", command=self._add_maint_bar)
        edit_menu.add_separator()
        edit_menu.add_command(label="スケジュール検証", command=self._validate_now)

        settings_menu = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="設定", menu=settings_menu)
        settings_menu.add_command(label="ガスタービン色の設定…", command=self._open_settings)

        self.bind_all("<Control-n>", lambda _: self._new_file())
        self.bind_all("<Control-o>", lambda _: self._open_file())
        self.bind_all("<Control-s>", lambda _: self._save_file())
        self.bind_all("<Control-S>", lambda _: self._save_as())

    def _build_ui(self) -> None:
        self._paned = tk.PanedWindow(self, orient="vertical", sashwidth=6,
                                     bg="white", sashrelief="flat")
        self._paned.pack(fill="both", expand=True)

        self._gantt_frame = tk.Frame(self._paned, bg="white")
        self._paned.add(self._gantt_frame, minsize=300, stretch="always")

        # 下半分：左に集計パネル、右に別枠履歴パネル
        self._bottom_paned = tk.PanedWindow(self._paned, orient="horizontal",
                                            sashwidth=5, bg="white",
                                            sashrelief="flat")
        self._paned.add(self._bottom_paned, minsize=140, stretch="never")

        self._summary_frame = tk.Frame(self._bottom_paned)
        self._bottom_paned.add(self._summary_frame, minsize=200, stretch="always")

        self._history_frame = tk.Frame(self._bottom_paned, bg="white")
        self._bottom_paned.add(self._history_frame, minsize=320, stretch="never")

        self._gantt:   GanttCanvas | None = None
        self._summary: SummaryPanel | None = None
        self._history: MaintenanceHistoryPanel | None = None

        # 描画後にサッシ位置を最適化
        self.after(150, self._fit_sash)

        # Status bar
        self._status_var = tk.StringVar(value="ファイルを開いてください")
        status_bar = tk.Label(self, textvariable=self._status_var,
                              anchor="w", padx=8, bg="#E8EDF5",
                              relief="sunken", font=("Meiryo UI", 8))
        status_bar.pack(side="bottom", fill="x")

    # ── Data loading ─────────────────────────────────────────────────────────

    def _show_empty(self) -> None:
        lbl = tk.Label(self._gantt_frame,
                       text="ファイル > 新規作成、または ファイル > 開く でスケジュールを読み込んでください",
                       fg="#888", font=("Meiryo UI", 12))
        lbl.place(relx=0.5, rely=0.5, anchor="center")

    def _load_file(self, path: str) -> None:
        try:
            app_data = load_json(path)
        except Exception as e:
            result = messagebox.askquestion(
                "読み込みエラー",
                f"データの読み込みに失敗しました。ファイルが破損している可能性があります。\n\n"
                f"詳細: {e}\n\n"
                "デフォルトデータを読み込みますか？",
                parent=self,
            )
            if result == "yes":
                try:
                    app_data = load_json(str(DEFAULT_JSON))
                    path = None
                except Exception:
                    return
            else:
                return

        self._app_data  = app_data
        self._file_path = path
        self._modified  = False
        self._rebuild_widgets()
        self._update_title()
        if path:
            _save_prefs({"last_file": path})
        self._status_var.set(f"読み込み完了: {path or 'デフォルトデータ'}")

    def _rebuild_widgets(self) -> None:
        if self._app_data is None:
            return
        # Clear frames
        for w in self._gantt_frame.winfo_children():
            w.destroy()
        for w in self._summary_frame.winfo_children():
            w.destroy()

        self._gantt = GanttCanvas(
            self._gantt_frame,
            self._app_data,
            on_change=self._on_data_change,
            open_edit_dialog=self._open_edit_dialog,
        )
        self._gantt.pack(fill="both", expand=True)

        self._summary = SummaryPanel(
            self._summary_frame, self._app_data,
            on_init_h_change=self._on_init_h_change,
        )
        self._summary.pack(fill="both", expand=True)

        for w in self._history_frame.winfo_children():
            w.destroy()
        self._history = MaintenanceHistoryPanel(
            self._history_frame, self._app_data,
            on_status_change=self._on_maint_status_change,
            on_reqdur_change=self._on_maint_reqdur_change,
        )
        self._history.pack(fill="both", expand=True)

    # ── Dirty tracking ────────────────────────────────────────────────────────

    def _on_data_change(self) -> None:
        self._modified = True
        self._update_title()
        if self._summary:
            self._summary.refresh()
        if self._history:
            self._history.refresh()

    def _update_title(self) -> None:
        fname = Path(self._file_path).name if self._file_path else "新規ファイル"
        star  = "*" if self._modified else ""
        self.title(f"{fname}{star} - GanttApp")

    # ── File operations ──────────────────────────────────────────────────────

    def _new_file(self) -> None:
        if not self._confirm_discard():
            return
        NewFileWizard(self, callback=self._on_wizard_done)

    def _on_wizard_done(self, app_data: AppData) -> None:
        self._app_data  = app_data
        self._file_path = None
        self._modified  = True
        self._rebuild_widgets()
        self._update_title()

    def _open_file(self) -> None:
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="ファイルを開く",
            initialdir=str(SAVE_DIR),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._load_file(path)

    def _load_default(self) -> None:
        if not self._confirm_discard():
            return
        result = messagebox.askyesno(
            "初期計画に戻す",
            "初期計画（data/default.json）を読み込みます。\n"
            "現在の編集内容は破棄されます。よろしいですか？",
            parent=self,
        )
        if result:
            self._load_file(str(DEFAULT_JSON))
            # 初期データとして読み込んだことを明示するため file_path をリセット
            self._file_path = None
            self._modified  = False
            self._update_title()
            self._status_var.set("初期計画を読み込みました（保存先は save/ フォルダです）")

    def _save_file(self) -> None:
        if self._app_data is None:
            return
        # 未保存 or 初期データのまま → 必ず save/ フォルダへ名前を付けて保存
        if self._file_path is None or Path(self._file_path).resolve() == DEFAULT_JSON.resolve():
            self._save_as()
            return
        errors = validate(self._app_data)
        if errors:
            messagebox.showerror("検証エラー",
                                 "スケジュールに問題があります。保存できません。\n\n" +
                                 "\n".join(f"• {e}" for e in errors), parent=self)
            return
        save_json(self._app_data, self._file_path)
        self._modified = False
        self._update_title()
        self._status_var.set(f"保存しました: {self._file_path}")

    def _save_as(self) -> None:
        if self._app_data is None:
            return
        errors = validate(self._app_data)
        if errors:
            messagebox.showerror("検証エラー",
                                 "スケジュールに問題があります。保存できません。\n\n" +
                                 "\n".join(f"• {e}" for e in errors), parent=self)
            return
        path = filedialog.asksaveasfilename(
            title="名前を付けて保存",
            initialdir=str(SAVE_DIR),
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            save_json(self._app_data, path)
            self._file_path = path
            self._modified  = False
            self._update_title()
            _save_prefs({"last_file": path})
            self._status_var.set(f"保存しました: {path}")

    def _save_as_default(self) -> None:
        """機体バーから未搭載バーを自動生成し、data/default.json に上書き保存する。"""
        if self._app_data is None:
            return
        import copy
        data = copy.deepcopy(self._app_data)

        # 未搭載バーを機体バーから自動再計算
        data.maintenance_bars = _generate_maintenance_bars(data)

        # 重複チェック（警告のみ、保存は続行）
        from validation import validate as _validate
        errors = [e for e in _validate(data) if "重複" in e or "複数" in e]
        if errors:
            proceed = messagebox.askyesno(
                "重複の警告",
                "機体バーに以下の重複があります。\n\n" +
                "\n".join(f"• {e}" for e in errors) +
                "\n\nそのまま保存しますか？",
                parent=self,
            )
            if not proceed:
                return

        target = str(DEFAULT_JSON)
        save_json(data, target)
        # アプリ内データにも未搭載バーを反映
        self._app_data.maintenance_bars = data.maintenance_bars
        if self._gantt:
            self._gantt.set_data(self._app_data)
        if self._summary:
            self._summary.refresh()
        self._status_var.set(f"デフォルトデータを更新しました: {target}")
        messagebox.showinfo("保存完了",
                            f"data/default.json を更新しました。\n未搭載バー {len(data.maintenance_bars)} 件を自動生成しました。",
                            parent=self)

    def _on_win_resize(self, event) -> None:
        """ウィンドウリサイズ時に垂直サッシを追従させる（デバウンス付き）。"""
        if event.widget is not self:
            return
        if self._win_resize_job:
            self.after_cancel(self._win_resize_job)
        self._win_resize_job = self.after(80, self._fit_sash)

    def _fit_sash(self) -> None:
        """垂直サッシ：ガント2段を優先し、下パネルを縮める。水平サッシ：初回のみ設定。"""
        from gantt_canvas import CANVAS_H
        from maintenance_history import COL_W
        self.update_idletasks()
        # 垂直サッシ：ガントキャンバス＋内部パッド＋スクロールバーが収まる高さ
        gantt_h = CANVAS_H + 10 + 17   # 上パッド10 ＋ 水平スクロールバー17
        self._paned.sash_place(0, 0, gantt_h)
        # 水平サッシ：集計列幅ちょうどの位置に固定（初回のみ）
        if not getattr(self, "_hsash_set", False):
            from summary_panel import SummaryPanel as _SP
            # 集計パネルの列幅合計＋スクロールバー＋パディング
            sum_col_total = 70 + 118 + 110 + 95   # engine+init_h+accum_h+total_days
            summary_w = sum_col_total + 30
            self._bottom_paned.sash_place(0, summary_w, 0)
            self._hsash_set = True

    def _confirm_discard(self) -> bool:
        if not self._modified:
            return True
        result = messagebox.askyesnocancel(
            "未保存の変更", "保存されていない変更があります。保存しますか？", parent=self)
        if result is None:
            return False  # cancel
        if result:
            self._save_file()
        return True

    def _on_close(self) -> None:
        if self._confirm_discard():
            self.destroy()

    # ── Edit dialogs (called from canvas) ────────────────────────────────────

    def _open_edit_dialog(self, kind: str, idx: int, seg_or_date) -> None:
        if self._app_data is None:
            return
        if kind == "machine":
            bar = self._app_data.machine_bars[idx]
            EditMachineBarDialog(self, bar, on_save=self._on_machine_bar_saved)
        elif kind == "maint":
            bar = self._app_data.maintenance_bars[idx]
            EditMaintenanceBarDialog(self, bar, on_save=self._on_maint_bar_saved)
        elif kind == "insert":
            split_date = seg_or_date  # date object passed from canvas
            InsertEngineDialog(
                self, self._app_data, idx, split_date,
                on_save=self._on_insert_engine,
            )

    def _on_machine_bar_saved(self, bar: MachineBar) -> None:
        # Bar is already modified in-place; validate adjacency
        errors = self._validate_machine_adjacency(bar)
        if errors:
            messagebox.showwarning("警告", "\n".join(errors), parent=self)
        self._on_data_change()
        if self._gantt:
            self._gantt.redraw()

    def _validate_machine_adjacency(self, bar: MachineBar) -> list[str]:
        """Light check that this machine still has no gaps."""
        bars = sorted(
            [b for b in self._app_data.machine_bars if b.machine_id == bar.machine_id],
            key=lambda b: b.start,
        )
        errors = []
        for i in range(len(bars) - 1):
            if bars[i].end + timedelta(days=1) != bars[i + 1].start:
                errors.append(
                    f"{bars[i].engine_id} → {bars[i+1].engine_id} 間に隙間または重複があります"
                )
        return errors

    def _on_init_h_change(self, engine_id: str, new_hours: float) -> None:
        eng = engine_by_id(self._app_data, engine_id)
        if eng:
            eng.initial_hours = new_hours
        self._on_data_change()
        if self._summary:
            self._summary.refresh()

    def _on_maint_status_change(self, row_idx: int, new_status: str) -> None:
        from maintenance_history import _history_bars
        bars = _history_bars(self._app_data)
        if 0 <= row_idx < len(bars):
            bars[row_idx].status = new_status
            self._on_data_change()
            if self._gantt:
                self._gantt.redraw()

    def _on_maint_reqdur_change(self, row_idx: int, new_value: str) -> None:
        from maintenance_history import _history_bars
        bars = _history_bars(self._app_data)
        if 0 <= row_idx < len(bars):
            bars[row_idx].required_duration = new_value.strip()
            self._on_data_change()

    def _on_maint_bar_saved(self, bar: MaintenanceBar) -> None:
        self._on_data_change()
        if self._gantt:
            self._gantt.redraw()

    def _on_insert_engine(self, bar_idx: int, split_date: date, new_engine_id: str) -> None:
        """Split machine bar at split_date, replacing tail with new_engine_id."""
        bars  = self._app_data.machine_bars
        bar   = bars[bar_idx]
        mid   = bar.machine_id

        if split_date <= bar.start or split_date > bar.end:
            messagebox.showerror("エラー", "交換日がバーの期間外です。", parent=self)
            return

        # Shrink current bar
        old_end   = bar.end
        bar.end   = split_date - timedelta(days=1)

        # New bar takes from split_date to original end
        new_bar   = MachineBar(
            machine_id=mid, engine_id=new_engine_id,
            start=split_date, end=old_end, operation_rate=0.8,
        )
        # Insert after current bar index
        bars.insert(bar_idx + 1, new_bar)

        self._on_data_change()
        if self._gantt:
            self._gantt.set_data(self._app_data)

    # ── Additional edit operations ────────────────────────────────────────────

    def _add_maint_bar(self) -> None:
        if self._app_data is None:
            messagebox.showinfo("情報", "先にファイルを開いてください。", parent=self)
            return
        AddMaintenanceBarDialog(self, on_save=self._on_maint_added)

    def _on_maint_added(self, bar: MaintenanceBar) -> None:
        self._app_data.maintenance_bars.append(bar)
        self._on_data_change()
        if self._gantt:
            self._gantt.redraw()

    def _validate_now(self) -> None:
        if self._app_data is None:
            return
        errors = validate(self._app_data)
        if errors:
            messagebox.showerror("検証結果 — エラーあり",
                                 "\n".join(f"• {e}" for e in errors), parent=self)
        else:
            messagebox.showinfo("検証結果", "問題は見つかりませんでした。", parent=self)

    def _open_settings(self) -> None:
        if self._app_data is None:
            return
        SettingsDialog(self, self._app_data, on_save=self._on_settings_saved)

    def _on_settings_saved(self, app_data: AppData) -> None:
        self._app_data.engines = app_data.engines
        self._on_data_change()
        if self._gantt:
            self._gantt.set_data(self._app_data)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Windows DPI awareness（高解像度ディスプレイ対応）
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = GanttApp()
    app.mainloop()
