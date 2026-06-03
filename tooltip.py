"""Hover tooltip for tkinter."""
import tkinter as tk


def _lighten(hex_color: str, factor: float = 0.75) -> str:
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


class Tooltip:
    """Hover tooltip with per-call background color."""

    def __init__(self, widget: tk.Widget):
        self._widget = widget
        self._win:   tk.Toplevel | None = None
        self._label: tk.Label    | None = None
        self._cur_bg = ""

    def show(self, text: str, x: int, y: int, bar_color: str = "#888888") -> None:
        bg = _lighten(bar_color, 0.72)

        if self._win is None:
            self._win = tk.Toplevel(self._widget)
            self._win.wm_overrideredirect(True)
            self._win.wm_attributes("-topmost", True)
            self._label = tk.Label(
                self._win, text=text, justify="left",
                background=bg, foreground="black",
                relief="solid", borderwidth=1,
                font=("Meiryo UI", 9), padx=8, pady=5,
            )
            self._label.pack()
            self._cur_bg = bg
        else:
            if text != self._label.cget("text") or bg != self._cur_bg:
                self._label.config(text=text, background=bg, foreground="black")
                self._cur_bg = bg

        rx = self._widget.winfo_rootx() + x + 16
        ry = self._widget.winfo_rooty() + y + 16
        self._win.wm_geometry(f"+{rx}+{ry}")

    def hide(self) -> None:
        if self._win:
            self._win.destroy()
            self._win  = None
            self._label = None
            self._cur_bg = ""
