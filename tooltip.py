"""Hover tooltip for tkinter."""
import tkinter as tk


class Tooltip:
    """Lightweight tooltip that follows mouse cursor."""

    def __init__(self, widget: tk.Widget):
        self._widget = widget
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None

    def show(self, text: str, x: int, y: int) -> None:
        if self._win is None:
            self._win = tk.Toplevel(self._widget)
            self._win.wm_overrideredirect(True)
            self._win.wm_attributes("-topmost", True)
            self._label = tk.Label(
                self._win, text=text, justify="left",
                background="#FFFFE0", relief="solid", borderwidth=1,
                font=("Meiryo UI", 9), padx=6, pady=4,
            )
            self._label.pack()
        else:
            self._label.config(text=text)  # type: ignore[union-attr]

        # Position slightly below-right of cursor
        rx = self._widget.winfo_rootx() + x + 14
        ry = self._widget.winfo_rooty() + y + 14
        self._win.wm_geometry(f"+{rx}+{ry}")

    def hide(self) -> None:
        if self._win:
            self._win.destroy()
            self._win = None
            self._label = None
