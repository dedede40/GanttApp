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
    engine_by_id,
)
from tooltip import Tooltip

# ── Layout constants ──────────────────────────────────────────────────────────

LABEL_W  = 120   # width of left label column
MONTH_W  = 30    # pixels per month
YEAR_H   = 24    # height of year header row
MONTH_H  = 22    # height of month header row
HEADER_H = YEAR_H + MONTH_H   # 46
ROW_H    = 48    # height of each machine/maintenance row
SEP_H    = 16    # separator between machine rows and maintenance row
SEG_GAP  = 32    # vertical gap between segment 1 and segment 2

BAR_PAD  = 6     # vertical padding inside row for bar
EDGE_TOL = 6     # pixels from edge to trigger resize cursor

SEG_H = HEADER_H + 3 * ROW_H + SEP_H + ROW_H
# = 46 + 144 + 16 + 48 = 254

CANVAS_W = LABEL_W + 60 * MONTH_W           # 120 + 1800 = 1920
CANVAS_H = 2 * SEG_H + SEG_GAP              # 508 + 32 = 540

MONTHS_SHORT = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]

# ── Coordinate helpers ────────────────────────────────────────────────────────

def _seg_y(seg: int) -> int:
    return seg * (SEG_H + SEG_GAP)


def _machine_row_y(seg: int, row: int) -> int:
    return _seg_y(seg) + HEADER_H + row * ROW_H


def _maint_row_y(seg: int) -> int:
    return _seg_y(seg) + HEADER_H + 3 * ROW_H + SEP_H


def _date_to_x(d: date, seg: int) -> float:
    """Left-edge x for a date within a segment."""
    ref = date(2025 + seg * 5, 1, 1)
    months = (d.year - ref.year) * 12 + (d.month - ref.month)
    frac   = (d.day - 1) / days_in_month(d.year, d.month)
    return LABEL_W + (months + frac) * MONTH_W


def _date_to_x2(d: date, seg: int) -> float:
    """Right-edge x for a date within a segment."""
    ref = date(2025 + seg * 5, 1, 1)
    months = (d.year - ref.year) * 12 + (d.month - ref.month)
    frac   = d.day / days_in_month(d.year, d.month)
    return LABEL_W + (months + frac) * MONTH_W


def _x_to_date(x: float, seg: int) -> date:
    """Convert canvas x to date within segment seg, snapped to day."""
    ref  = date(2025 + seg * 5, 1, 1)
    frac = max(0.0, (x - LABEL_W) / MONTH_W)
    frac = min(frac, 60.0 - 1e-9)
    mi   = int(frac)          # whole months
    df   = frac - mi           # day fraction
    year  = ref.year  + mi // 12
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

        for seg in range(2):
            sy  = _seg_y(seg)
            ref = date(2025 + seg * 5, 1, 1)

            # Background rect
            c.create_rectangle(
                0, sy, CANVAS_W, sy + SEG_H,
                fill="#F7F7F7", outline="",
            )

            # Alternating row shading for machine rows
            for row in range(3):
                ry = _machine_row_y(seg, row)
                shade = "#FFFFFF" if row % 2 == 0 else "#F0F4FA"
                c.create_rectangle(LABEL_W, ry, CANVAS_W, ry + ROW_H,
                                   fill=shade, outline="")

            # Maintenance row
            my = _maint_row_y(seg)
            c.create_rectangle(LABEL_W, my, CANVAS_W, my + ROW_H,
                               fill="#F5F0FB", outline="")

            # Year header bands + labels
            year_y = sy
            col_y  = sy + YEAR_H
            prev_x = LABEL_W
            for mi in range(60):
                m   = add_months(ref, mi)
                x1  = LABEL_W + mi * MONTH_W
                x2  = x1 + MONTH_W

                # Month divider line (light)
                c.create_line(x1, sy, x1, sy + SEG_H, fill="#D0D0D0")

                # Year change → draw year label
                if mi == 0 or m.month == 1:
                    # Year header rectangle
                    # find how many months this year spans in segment
                    yr = m.year
                    yr_start_mi = mi
                    yr_end_mi   = min(59, yr_start_mi + (12 - m.month))
                    yr_x1 = LABEL_W + yr_start_mi * MONTH_W
                    yr_x2 = LABEL_W + (yr_end_mi + 1) * MONTH_W
                    fill  = "#3B6EA5" if yr % 2 == 0 else "#2E5C8A"
                    c.create_rectangle(yr_x1, year_y, yr_x2, year_y + YEAR_H,
                                       fill=fill, outline="")
                    c.create_text(
                        (yr_x1 + yr_x2) / 2, year_y + YEAR_H / 2,
                        text=f"{yr}年", fill="white",
                        font=("Meiryo UI", 9, "bold"), anchor="center",
                    )
                    prev_x = yr_x2

                # Month label
                c.create_rectangle(x1, col_y, x2, col_y + MONTH_H,
                                   fill="#EEF2F8", outline="#D0D0D0")
                c.create_text(
                    x1 + MONTH_W / 2, col_y + MONTH_H / 2,
                    text=MONTHS_SHORT[m.month - 1], fill="#333",
                    font=("Meiryo UI", 8), anchor="center",
                )

            # Horizontal grid lines
            for row in range(4):
                ry = _machine_row_y(seg, row) if row < 3 else _maint_row_y(seg)
                c.create_line(LABEL_W, ry, CANVAS_W, ry, fill="#C0C8D8")
            c.create_line(LABEL_W, sy + SEG_H, CANVAS_W, sy + SEG_H, fill="#C0C8D8")

            # Separator line between machines and maintenance
            sep_y = _seg_y(seg) + HEADER_H + 3 * ROW_H
            c.create_line(0, sep_y, CANVAS_W, sep_y + SEP_H // 2,
                          fill="#B0B0B0", width=1, dash=(4, 2))

            # Left label column background
            c.create_rectangle(0, sy, LABEL_W, sy + SEG_H,
                               fill="#E8EDF5", outline="")
            c.create_line(LABEL_W, sy, LABEL_W, sy + SEG_H,
                          fill="#A0A8B8", width=1)

            # Row labels
            for row, mid in enumerate(MACHINE_IDS):
                ry = _machine_row_y(seg, row)
                c.create_text(
                    LABEL_W // 2, ry + ROW_H // 2,
                    text=MACHINE_NAMES[mid], fill="#222",
                    font=("Meiryo UI", 10, "bold"), anchor="center",
                )

            my = _maint_row_y(seg)
            c.create_text(
                LABEL_W // 2, my + ROW_H // 2,
                text="未搭載", fill="#555",
                font=("Meiryo UI", 9), anchor="center",
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
            x1, y1, x2, y2, fill=color, outline="white", width=1.5,
        )
        label = f"{b.engine_id} / {int(b.operation_rate * 100)}%"
        tid = 0
        if x2 - x1 > 70:
            tid = self._canvas.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=label, fill="white",
                font=("Meiryo UI", 9, "bold"), anchor="center",
            )

        self._bars.append(BarRecord(kind, idx, seg, row, x1, y1, x2, y2, rid, tid))

    def _draw_one_maint_bar(self, b: MaintenanceBar, kind: str, idx: int, seg: int) -> None:
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
        y2 = my + ROW_H - BAR_PAD

        color = self._engine_color(b.engine_id)
        rid   = self._canvas.create_rectangle(
            x1, y1, x2, y2, fill=color, outline="white", width=1.5,
            stipple="gray50",   # maintenance bars shown with pattern
        )
        # stipple makes text hard to see; draw on top without stipple
        rid2 = self._canvas.create_rectangle(
            x1, y1, x2, y2, fill="", outline="white", width=1.5,
        )
        label = f"{b.engine_id}:{b.status}"
        tid = 0
        if x2 - x1 > 80:
            tid = self._canvas.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=label, fill="white",
                font=("Meiryo UI", 9), anchor="center",
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

    def _drag_machine(self, idx: int, mode: str, snap: MachineBar,
                      new_date: date, dx: float) -> None:
        bars   = self.app_data.machine_bars
        b      = bars[idx]
        mid    = b.machine_id
        m_bars = sorted([i for i, x in enumerate(bars) if x.machine_id == mid],
                        key=lambda i: bars[i].start)
        pos    = m_bars.index(idx)

        if mode == "right":
            # Drag right edge: clamp to next bar's end date minus 1 day, min 1 day
            next_end = PERIOD_END
            if pos < len(m_bars) - 1:
                next_bar = bars[m_bars[pos + 1]]
                next_end = next_bar.end
            new_end = _clamp_date(new_date, b.start, next_end)
            if new_end == b.end:
                return
            b.end = new_end
            # Adjust next bar's start
            if pos < len(m_bars) - 1:
                bars[m_bars[pos + 1]].start = new_end + timedelta(days=1)

        elif mode == "left":
            # Drag left edge: clamp to prev bar's start date plus 1 day
            prev_start = PERIOD_START
            if pos > 0:
                prev_bar = bars[m_bars[pos - 1]]
                prev_start = prev_bar.start
            new_start = _clamp_date(new_date, prev_start, b.end)
            if new_start == b.start:
                return
            b.start = new_start
            if pos > 0:
                bars[m_bars[pos - 1]].end = new_start - timedelta(days=1)

        self.redraw()
        self.on_change()

    def _drag_maint(self, idx: int, mode: str, snap: MaintenanceBar,
                    new_date: date, dx: float) -> None:
        b = self.app_data.maintenance_bars[idx]

        if mode == "right":
            new_end = _clamp_date(new_date, b.start, PERIOD_END)
            if new_end == b.end:
                return
            b.end = new_end
        elif mode == "left":
            new_start = _clamp_date(new_date, PERIOD_START, b.end)
            if new_start == b.start:
                return
            b.start = new_start
        elif mode == "move":
            orig_len  = (snap.end - snap.start).days
            new_start = _clamp_date(new_date - timedelta(days=orig_len // 2),
                                    PERIOD_START, PERIOD_END - timedelta(days=orig_len))
            new_end   = new_start + timedelta(days=orig_len)
            if new_start == b.start:
                return
            b.start = new_start
            b.end   = new_end

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
                label=f"ここでエンジン交換 ({seg_date.strftime('%Y/%m/%d')})",
                command=lambda d=seg_date, b=br: self._open_edit("insert", b.idx, d),
            )
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

    def _show_machine_row_menu(self, event, mid: str, cx: float, seg: int) -> None:
        seg_date = _x_to_date(cx, seg)
        menu = tk.Menu(self, tearoff=0)
        # Find last bar in machine to determine insert point
        bars  = [b for b in self.app_data.machine_bars if b.machine_id == mid]
        if bars:
            last = max(bars, key=lambda b: b.start)
            idx  = self.app_data.machine_bars.index(last)
            menu.add_command(
                label=f"エンジン交換を挿入 ({seg_date.strftime('%Y/%m/%d')})",
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
        self._tooltip.show(self._bar_tooltip(br), event.x, event.y)

    def _bar_tooltip(self, br: BarRecord) -> str:
        if br.kind == "machine":
            b = self.app_data.machine_bars[br.idx]
            duration = round_half_month(months_between(b.start, b.end))
            return (
                f"エンジン: {b.engine_id}\n"
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
                f"エンジン: {b.engine_id}\n"
                f"開始日: {fmt_date(b.start)}\n"
                f"終了日: {fmt_date(b.end)}\n"
                f"状態: {b.status}\n"
                f"期間: {duration}"
            )
