"""Gantt chart canvas widget."""
import copy
import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk
from typing import List, Optional, Tuple, Dict, Any

from models import (
    AppData, MachineBar, MaintenanceBar, Engine,
    MACHINE_IDS, MACHINE_NAMES,
    PERIOD_START, PERIOD_END, SEG1_START, SEG1_END, SEG2_START, SEG2_END,
    days_in_month, add_months, fmt_date, months_between, round_half_month,
    engine_by_id, hex_lighten,
)
from tooltip import Tooltip

# ── Layout constants ──────────────────────────────────────────────────────────

LABEL_W      = 80    # width of left label column
MONTH_W      = 23    # pixels per month
YEAR_H       = 20    # height of year header row
MONTH_H      = 18    # height of month header row
HEADER_H     = YEAR_H + MONTH_H   # 38
ROW_H        = 36    # height of each machine row
MAINT_ROW_H  = 58    # height of maintenance row (2-line text)
SEP_H        = 10    # separator between machine rows and maintenance row
SEG_GAP      = 20    # vertical gap between segment 1 and segment 2

BAR_PAD  = 4     # vertical padding inside row for bar
EDGE_TOL = 5     # pixels from edge to trigger resize cursor
MIN_GAP  = timedelta(days=14)    # 隣り合う境界の最小間隔＝バー最小長（14日）

SEG_H = HEADER_H + 3 * ROW_H + SEP_H + MAINT_ROW_H

SEG_MONTHS = 48                              # 4年×12ヶ月
CANVAS_W = LABEL_W + SEG_MONTHS * MONTH_W
CANVAS_H = 2 * SEG_H + SEG_GAP

MONTHS_SHORT = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]

# ── Coordinate helpers ────────────────────────────────────────────────────────

def _seg_y(seg: int) -> int:
    return seg * (SEG_H + SEG_GAP)


def _machine_row_y(seg: int, row: int) -> int:
    return _seg_y(seg) + HEADER_H + row * ROW_H


def _maint_row_y(seg: int) -> int:
    return _seg_y(seg) + HEADER_H + 3 * ROW_H + SEP_H

def _maint_row_h() -> int:
    return MAINT_ROW_H


def _seg_ref(seg: int) -> date:
    """First day of segment (seg=0→2026-01, seg=1→2030-01)."""
    return date(2026 + seg * 4, 1, 1)


def _date_to_x(d: date, seg: int) -> float:
    """Left-edge x for a date within a segment."""
    ref = _seg_ref(seg)
    months = (d.year - ref.year) * 12 + (d.month - ref.month)
    frac   = (d.day - 1) / days_in_month(d.year, d.month)
    return LABEL_W + (months + frac) * MONTH_W


def _date_to_x2(d: date, seg: int) -> float:
    """Right-edge x for a date within a segment."""
    ref = _seg_ref(seg)
    months = (d.year - ref.year) * 12 + (d.month - ref.month)
    frac   = d.day / days_in_month(d.year, d.month)
    return LABEL_W + (months + frac) * MONTH_W


def _x_to_date(x: float, seg: int) -> date:
    """Convert canvas x to date within segment seg, snapped to day."""
    ref  = _seg_ref(seg)
    frac = max(0.0, (x - LABEL_W) / MONTH_W)
    frac = min(frac, SEG_MONTHS - 1e-9)
    mi   = int(frac)
    df   = frac - mi
    year  = ref.year + mi // 12
    month = (ref.month - 1 + mi % 12) % 12 + 1
    year += (ref.month - 1 + mi % 12) // 12
    dim  = days_in_month(year, month)
    day  = max(1, min(int(df * dim) + 1, dim))
    return date(year, month, day)


def _clamp_date(d: date, lo: date, hi: date) -> date:
    if d < lo:
        return lo
    if d > hi:
        return hi
    return d


def _seg_for_date(d: date) -> int:
    return 0 if d <= SEG1_END else 1


def _seg_x_left(seg: int) -> float:
    return LABEL_W


def _seg_x_right(seg: int) -> float:
    return LABEL_W + 60 * MONTH_W


# ── Bar info records ──────────────────────────────────────────────────────────

class BarRecord:
    """Describes one drawn bar rect (may be partial for cross-segment bars)."""
    __slots__ = ("kind", "idx", "seg", "row", "x1", "y1", "x2", "y2", "rect_id", "text_id")

    def __init__(self, kind, idx, seg, row, x1, y1, x2, y2, rect_id, text_id):
        self.kind = kind  # "machine" | "maint"
        self.idx  = idx   # index into machine_bars / maintenance_bars
        self.seg  = seg
        self.row  = row
        self.x1 = x1; self.y1 = y1; self.x2 = x2; self.y2 = y2
        self.rect_id = rect_id
        self.text_id = text_id


# ── Main widget ───────────────────────────────────────────────────────────────

class GanttCanvas(tk.Frame):
    def __init__(self, parent, app_data: AppData, on_change, open_edit_dialog, **kw):
        super().__init__(parent, **kw)
        self.app_data       = app_data
        self.on_change      = on_change          # () -> None
        self._open_edit     = open_edit_dialog   # (kind, idx, seg) -> None

        self._canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self._hbar   = ttk.Scrollbar(self, orient="horizontal", command=self._canvas.xview)
        self._vbar   = ttk.Scrollbar(self, orient="vertical",   command=self._canvas.yview)
        self._canvas.configure(
            xscrollcommand=self._hbar.set,
            yscrollcommand=self._vbar.set,
            scrollregion=(0, 0, CANVAS_W, CANVAS_H),
        )

        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vbar.grid(row=0, column=1, sticky="ns")
        self._hbar.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._tooltip  = Tooltip(self._canvas)
        self._bars: List[BarRecord] = []   # hit-test list
        self._drag: Optional[Dict[str, Any]] = None

        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",        self._on_drag)
        self._canvas.bind("<ButtonRelease-1>",  self._on_release)
        self._canvas.bind("<Double-Button-1>",  self._on_double)
        self._canvas.bind("<Button-3>",         self._on_right)
        self._canvas.bind("<Motion>",           self._on_motion)
        self._canvas.bind("<Leave>",            lambda _: self._tooltip.hide())

        self.redraw()

    # ── Public API ──────────────────────────────────────────────────────────

    def set_data(self, app_data: AppData) -> None:
        self.app_data = app_data
        self.redraw()

    def redraw(self) -> None:
        c = self._canvas
        c.delete("all")
        self._bars = []
        self._draw_background()
        self._draw_bars()

    # ── Drawing ─────────────────────────────────────────────────────────────

    def _draw_background(self) -> None:
        c = self._canvas
        BK = "white"
        FG = "black"
        GRID = "#888888"
        HEAD_BG = "#DDDDDD"

        for seg in range(2):
            sy  = _seg_y(seg)
            ref = date(2025 + seg * 5, 1, 1)

            # Whole segment background (white)
            c.create_rectangle(0, sy, CANVAS_W, sy + SEG_H,
                               fill=BK, outline="")

            ref    = _seg_ref(seg)

            # ── Year header row ──────────────────────────────────────────
            year_y = sy
            col_y  = sy + YEAR_H
            for mi in range(SEG_MONTHS):
                m  = add_months(ref, mi)
                x1 = LABEL_W + mi * MONTH_W

                if mi == 0 or m.month == 1:
                    yr = m.year
                    yr_end_mi = min(SEG_MONTHS - 1, mi + 11)
                    yr_x1 = LABEL_W + mi * MONTH_W
                    yr_x2 = LABEL_W + (yr_end_mi + 1) * MONTH_W
                    c.create_rectangle(yr_x1, year_y, yr_x2, year_y + YEAR_H,
                                       fill=HEAD_BG, outline=FG)
                    c.create_text(
                        (yr_x1 + yr_x2) / 2, year_y + YEAR_H / 2,
                        text=f"{yr}年", fill=FG,
                        font=("Meiryo UI", 9, "bold"), anchor="center",
                    )

            # ── Month header row ─────────────────────────────────────────
            for mi in range(SEG_MONTHS):
                m  = add_months(ref, mi)
                x1 = LABEL_W + mi * MONTH_W
                x2 = x1 + MONTH_W
                c.create_rectangle(x1, col_y, x2, col_y + MONTH_H,
                                   fill=HEAD_BG, outline=FG)
                c.create_text(
                    x1 + MONTH_W / 2, col_y + MONTH_H / 2,
                    text=MONTHS_SHORT[m.month - 1], fill=FG,
                    font=("Meiryo UI", 7), anchor="center",
                )

            # ── Vertical month grid lines across rows ────────────────────
            row_top = _seg_y(seg) + HEADER_H
            row_bot = _maint_row_y(seg) + ROW_H
            for mi in range(SEG_MONTHS + 1):
                x = LABEL_W + mi * MONTH_W
                c.create_line(x, row_top, x, row_bot, fill=GRID)

            # ── Horizontal row lines ─────────────────────────────────────
            for row in range(3):
                ry = _machine_row_y(seg, row)
                c.create_line(0, ry, CANVAS_W, ry, fill=FG)
            # line after machine 3
            sep_top = _seg_y(seg) + HEADER_H + 3 * ROW_H
            c.create_line(0, sep_top, CANVAS_W, sep_top, fill=FG)
            # line at top of maint row
            my = _maint_row_y(seg)
            c.create_line(0, my, CANVAS_W, my, fill=FG)
            # line at bottom of maint row (uses MAINT_ROW_H)
            c.create_line(0, my + MAINT_ROW_H, CANVAS_W, my + MAINT_ROW_H, fill=FG)

            # ── Left label column ────────────────────────────────────────
            c.create_rectangle(0, sy, LABEL_W, sy + SEG_H,
                               fill=HEAD_BG, outline="")
            c.create_line(LABEL_W, sy, LABEL_W, sy + SEG_H, fill=FG, width=2)

            for row, mid in enumerate(MACHINE_IDS):
                ry = _machine_row_y(seg, row)
                c.create_text(
                    LABEL_W // 2, ry + ROW_H // 2,
                    text=MACHINE_NAMES[mid], fill=FG,
                    font=("Meiryo UI", 9, "bold"), anchor="center",
                )

            c.create_text(
                LABEL_W // 2, my + MAINT_ROW_H // 2,
                text="未搭載", fill=FG,
                font=("Meiryo UI", 9), anchor="center",
            )

            # ── Segment label (年代) at top-left ─────────────────────────
            yr_start = 2026 + seg * 4
            yr_end   = yr_start + 3
            c.create_rectangle(0, year_y, LABEL_W, year_y + YEAR_H,
                               fill=HEAD_BG, outline=FG)
            c.create_text(
                LABEL_W // 2, year_y + YEAR_H / 2,
                text=f"{yr_start}〜{yr_end}", fill=FG,
                font=("Meiryo UI", 7, "bold"), anchor="center",
            )

    def _engine_color(self, eid: str) -> str:
        e = engine_by_id(self.app_data, eid)
        return e.color if e else "#888888"

    def _draw_bars(self) -> None:
        for idx, b in enumerate(self.app_data.machine_bars):
            for seg in range(2):
                self._draw_one_bar(b, "machine", idx, seg)

        for idx, b in enumerate(self.app_data.maintenance_bars):
            for seg in range(2):
                self._draw_one_maint_bar(b, "maint", idx, seg)

    def _draw_one_bar(self, b: MachineBar, kind: str, idx: int, seg: int) -> None:
        seg_lo = SEG1_START if seg == 0 else SEG2_START
        seg_hi = SEG1_END   if seg == 0 else SEG2_END

        cs = max(b.start, seg_lo)
        ce = min(b.end,   seg_hi)
        if cs > ce:
            return

        row = MACHINE_IDS.index(b.machine_id)
        ry  = _machine_row_y(seg, row)
        x1  = _date_to_x(cs,  seg)
        x2  = _date_to_x2(ce, seg)
        y1  = ry + BAR_PAD
        y2  = ry + ROW_H - BAR_PAD

        color = self._engine_color(b.engine_id)
        rid   = self._canvas.create_rectangle(
            x1, y1, x2, y2, fill=color, outline="black", width=1,
        )
        label = f"{b.engine_id} / {int(b.operation_rate * 100)}%"
        tid = 0
        if x2 - x1 > 50:
            tid = self._canvas.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=label, fill="black",
                font=("Meiryo UI", 8, "bold"), anchor="center",
            )

        self._bars.append(BarRecord(kind, idx, seg, row, x1, y1, x2, y2, rid, tid))

    # 未搭載バーの表示対象外とする期間
    _MAINT_HIDE_BEFORE = date(2028, 5, 1)   # 2028年4月末まで → 非表示
    _MAINT_HIDE_FROM   = date(2033, 1, 1)   # 2033年以降 → 非表示

    def _draw_one_maint_bar(self, b: MaintenanceBar, kind: str, idx: int, seg: int) -> None:
        # 表示フィルタ：2028年4月末までに終わるもの、2033年以降に始まるものは非表示
        if b.end < self._MAINT_HIDE_BEFORE:
            return
        if b.start >= self._MAINT_HIDE_FROM:
            return

        seg_lo = SEG1_START if seg == 0 else SEG2_START
        seg_hi = SEG1_END   if seg == 0 else SEG2_END

        cs = max(b.start, seg_lo)
        ce = min(b.end,   seg_hi)
        if cs > ce:
            return

        my = _maint_row_y(seg)
        x1 = _date_to_x(cs,  seg)
        x2 = _date_to_x2(ce, seg)
        y1 = my + BAR_PAD
        y2 = my + MAINT_ROW_H - BAR_PAD
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        color = hex_lighten(self._engine_color(b.engine_id), 0.68)
        rid = self._canvas.create_rectangle(
            x1, y1, x2, y2, fill=color, outline="black", width=1,
        )

        bar_w = x2 - x1
        tid = 0
        if bar_w > 30:
            # 1行目：GT名 ＋ 0.5ヶ月単位の期間
            duration = round_half_month(months_between(b.start, b.end))
            line1 = f"{b.engine_id}  {duration}" if bar_w > 70 else b.engine_id
            # 2行目：点検種別
            line2 = b.status

            self._canvas.create_text(
                cx, cy - 8,
                text=line1, fill="black",
                font=("Meiryo UI", 8, "bold"), anchor="center",
            )
            tid = self._canvas.create_text(
                cx, cy + 8,
                text=line2, fill="black",
                font=("Meiryo UI", 8), anchor="center",
            )

        self._bars.append(BarRecord(kind, idx, seg, -1, x1, y1, x2, y2, rid, tid))

    # ── Hit testing ─────────────────────────────────────────────────────────

    def _cx(self, event) -> float:
        return self._canvas.canvasx(event.x)

    def _cy(self, event) -> float:
        return self._canvas.canvasy(event.y)

    def _hit_bar(self, cx: float, cy: float) -> Optional[BarRecord]:
        """Return topmost BarRecord under (cx, cy), or None."""
        for br in reversed(self._bars):
            if br.x1 <= cx <= br.x2 and br.y1 <= cy <= br.y2:
                return br
        return None

    def _hit_mode(self, br: BarRecord, cx: float) -> str:
        """'left' | 'right' | 'move'"""
        if cx <= br.x1 + EDGE_TOL:
            return "left"
        if cx >= br.x2 - EDGE_TOL:
            return "right"
        return "move"

    # ── Mouse events ─────────────────────────────────────────────────────────

    def _on_press(self, event) -> None:
        cx, cy = self._cx(event), self._cy(event)
        br = self._hit_bar(cx, cy)
        if br is None:
            return
        mode = self._hit_mode(br, cx)

        # Take snapshot of bar for drag
        if br.kind == "machine":
            bar_snap = copy.copy(self.app_data.machine_bars[br.idx])
        else:
            bar_snap = copy.copy(self.app_data.maintenance_bars[br.idx])

        self._drag = {
            "br":       br,
            "mode":     mode,
            "cx_start": cx,
            "bar_snap": bar_snap,
            "seg":      br.seg,
        }
        self._canvas.config(cursor="fleur" if mode == "move" else "sb_h_double_arrow")

    def _on_drag(self, event) -> None:
        if self._drag is None:
            return
        cx   = self._cx(event)
        drag = self._drag
        br   = drag["br"]
        seg  = drag["seg"]
        mode = drag["mode"]
        snap = drag["bar_snap"]
        dx   = cx - drag["cx_start"]
        days_per_px = 1.0 / (MONTH_W / 30.44)

        def px_to_days(px: float) -> int:
            return round(px / MONTH_W * 30.44)

        new_d = _x_to_date(cx, seg)

        if br.kind == "machine":
            self._drag_machine(br.idx, mode, snap, new_d, dx)
        else:
            self._drag_maint(br.idx, mode, snap, new_d, dx)

    # ── 境界連動（タイル状スケジュールを保つ） ────────────────────────────
    #
    # 各タービンの時間軸は「本体バー」と「別枠バー」が隙間なく交互に並ぶ。
    # さらに本体バーは号機ごとにも隙間なく連続する。
    # ある「境界（日付）」を動かすと、そこに接する全バーの端が連動する。
    #   ・同一タービンで隣り合うバー（本体↔別枠）
    #   ・同一号機で隣り合う本体バー（号機交換）
    # これらを連鎖的にたどり、関係する全バーを同期させる。

    def _all_bars(self):
        return list(self.app_data.machine_bars) + list(self.app_data.maintenance_bars)

    @staticmethod
    def _adjacent(a, b) -> bool:
        """a と b が同一タービン、または同一号機（本体同士）で連動対象か。"""
        if a.engine_id == b.engine_id:
            return True
        if isinstance(a, MachineBar) and isinstance(b, MachineBar):
            return a.machine_id == b.machine_id
        return False

    def _group(self, bar, side: str):
        """bar.<side> が接する境界に集まる全バーを (rights, lefts) で返す。
        rights: 境界で終わるバー（end = 境界日 - 1）
        lefts : 境界で始まるバー（start = 境界日）
        """
        one  = timedelta(days=1)
        pool = self._all_bars()
        rights, lefts = [], []
        seen = set()
        stack = [(bar, side)]
        while stack:
            b, s = stack.pop()
            if (id(b), s) in seen:
                continue
            seen.add((id(b), s))
            if s == "right":
                if not any(b is x for x in rights):
                    rights.append(b)
                for ob in pool:
                    if ob is b or not self._adjacent(b, ob):
                        continue
                    if ob.start == b.end + one:
                        stack.append((ob, "left"))
            else:  # left
                if not any(b is x for x in lefts):
                    lefts.append(b)
                for ob in pool:
                    if ob is b or not self._adjacent(b, ob):
                        continue
                    if ob.end == b.start - one:
                        stack.append((ob, "right"))
        return rights, lefts

    def _move_boundary(self, bar, side: str, target: date) -> date:
        """bar.<side> の境界を target へ動かす。連動・最小幅(14日)・押し込みを処理。
        実際に到達した境界日を返す。"""
        one = timedelta(days=1)
        rights, lefts = self._group(bar, side)
        cur = lefts[0].start if lefts else rights[0].end + one

        # 全期間でクランプ
        if target < PERIOD_START:
            target = PERIOD_START
        if target > PERIOD_END + one:
            target = PERIOD_END + one
        if target == cur:
            return cur

        if target > cur:
            # 境界が右へ → lefts が縮む。14日未満なら相手の右境界を押す
            for l in lefts:
                if (l.end + one) - target < MIN_GAP:
                    achieved = self._move_boundary(l, "right", target + MIN_GAP)
                    if achieved - MIN_GAP < target:
                        target = achieved - MIN_GAP
        else:
            # 境界が左へ → rights が縮む。14日未満なら相手の左境界を押す
            for r in rights:
                if target - r.start < MIN_GAP:
                    achieved = self._move_boundary(r, "left", target - MIN_GAP)
                    if achieved + MIN_GAP > target:
                        target = achieved + MIN_GAP

        for r in rights:
            r.end = target - one
        for l in lefts:
            l.start = target
        return target

    def _drag_machine(self, idx: int, mode: str, snap: MachineBar,
                      new_date: date, dx: float) -> None:
        b = self.app_data.machine_bars[idx]
        if mode == "right":
            self._move_boundary(b, "right", new_date + timedelta(days=1))
        elif mode == "left":
            self._move_boundary(b, "left", new_date)
        self.redraw()
        self.on_change()

    def _drag_maint(self, idx: int, mode: str, snap: MaintenanceBar,
                    new_date: date, dx: float) -> None:
        b = self.app_data.maintenance_bars[idx]
        if mode == "right":
            self._move_boundary(b, "right", new_date + timedelta(days=1))
        elif mode == "left":
            self._move_boundary(b, "left", new_date)
        elif mode == "move":
            # バー全体を平行移動（両境界を同じだけ動かしタイルを保つ）
            center = snap.start + (snap.end - snap.start) // 2
            delta  = (new_date - center).days
            new_start = snap.start + timedelta(days=delta)
            new_end   = snap.end   + timedelta(days=delta)
            if delta > 0:   # 右へ：先に右境界を動かす
                self._move_boundary(b, "right", new_end + timedelta(days=1))
                self._move_boundary(b, "left",  new_start)
            elif delta < 0:  # 左へ：先に左境界を動かす
                self._move_boundary(b, "left",  new_start)
                self._move_boundary(b, "right", new_end + timedelta(days=1))
        self.redraw()
        self.on_change()

    def _on_release(self, event) -> None:
        self._canvas.config(cursor="")
        self._drag = None

    def _on_double(self, event) -> None:
        cx, cy = self._cx(event), self._cy(event)
        br = self._hit_bar(cx, cy)
        if br is None:
            return
        self._open_edit(br.kind, br.idx, br.seg)

    def _on_right(self, event) -> None:
        cx, cy = self._cx(event), self._cy(event)
        br = self._hit_bar(cx, cy)
        if br is None:
            # Check if clicked in a machine row → insert context
            clicked_seg, clicked_row = self._pos_to_row(cx, cy)
            if clicked_seg >= 0 and 0 <= clicked_row < 3:
                self._show_machine_row_menu(event, MACHINE_IDS[clicked_row], cx, clicked_seg)
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="編集…", command=lambda: self._open_edit(br.kind, br.idx, br.seg))
        if br.kind == "machine":
            menu.add_separator()
            seg_date = _x_to_date(cx, br.seg)
            menu.add_command(
                label=f"ここでガスタービン交換 ({seg_date.strftime('%Y/%m/%d')})",
                command=lambda d=seg_date, b=br: self._open_edit("insert", b.idx, d),
            )
        elif br.kind == "maint":
            menu.add_separator()
            menu.add_command(label="削除", command=lambda b=br: self._delete_maint_bar(b.idx))
        menu.tk_popup(event.x_root, event.y_root)

    def _pos_to_row(self, cx: float, cy: float) -> Tuple[int, int]:
        """Return (seg, row) for a canvas position, -1 if not in a row."""
        for seg in range(2):
            sy = _seg_y(seg)
            for row in range(3):
                ry = _machine_row_y(seg, row)
                if ry <= cy < ry + ROW_H and LABEL_W <= cx:
                    return seg, row
        return -1, -1

    def _delete_maint_bar(self, idx: int) -> None:
        del self.app_data.maintenance_bars[idx]
        self.redraw()
        self.on_change()

    def _show_machine_row_menu(self, event, mid: str, cx: float, seg: int) -> None:
        seg_date = _x_to_date(cx, seg)
        menu = tk.Menu(self, tearoff=0)
        # Find last bar in machine to determine insert point
        bars  = [b for b in self.app_data.machine_bars if b.machine_id == mid]
        if bars:
            last = max(bars, key=lambda b: b.start)
            idx  = self.app_data.machine_bars.index(last)
            menu.add_command(
                label=f"ガスタービン交換を挿入 ({seg_date.strftime('%Y/%m/%d')})",
                command=lambda d=seg_date, i=idx: self._open_edit("insert", i, d),
            )
        menu.tk_popup(event.x_root, event.y_root)

    def _on_motion(self, event) -> None:
        cx, cy = self._cx(event), self._cy(event)
        br = self._hit_bar(cx, cy)
        if br is None:
            self._tooltip.hide()
            self._canvas.config(cursor="")
            return
        mode = self._hit_mode(br, cx)
        self._canvas.config(cursor="sb_h_double_arrow" if mode != "move" else "fleur")
        if br.kind == "machine":
            color = self._engine_color(self.app_data.machine_bars[br.idx].engine_id)
        else:
            color = self._engine_color(self.app_data.maintenance_bars[br.idx].engine_id)
        self._tooltip.show(self._bar_tooltip(br), event.x, event.y, bar_color=color)

    def _bar_tooltip(self, br: BarRecord) -> str:
        if br.kind == "machine":
            b = self.app_data.machine_bars[br.idx]
            duration = round_half_month(months_between(b.start, b.end))
            return (
                f"ガスタービン: {b.engine_id}\n"
                f"開始日: {fmt_date(b.start)}\n"
                f"終了日: {fmt_date(b.end)}\n"
                f"稼働率: {int(b.operation_rate * 100)}%\n"
                f"稼働日数: {b.days} 日\n"
                f"稼働時間: {b.hours:,.0f} h\n"
                f"期間: {duration}"
            )
        else:
            b = self.app_data.maintenance_bars[br.idx]
            duration = round_half_month(months_between(b.start, b.end))
            return (
                f"ガスタービン: {b.engine_id}\n"
                f"開始日: {fmt_date(b.start)}\n"
                f"終了日: {fmt_date(b.end)}\n"
                f"状態: {b.status}\n"
                f"期間: {duration}"
            )
