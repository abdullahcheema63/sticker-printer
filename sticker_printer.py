"""
Sticker Printer - prints carton (100x75 mm) and box (30x19 mm, 3-up) stickers
on a TSPL label printer, using the printer's built-in fonts.

Run:      python sticker_printer.py
Needs:    pip install pywin32           (Windows only; nothing on Mac/Linux)
"""

import json
import math
import os
import platform
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

# ============================================================ calibration ====
# Adjust these to match your printer and rolls.

DPMM = 8                    # 203 dpi printer = 8 dots per mm
DIRECTION = 1               # flip to 0 if labels come out upside down
DENSITY = 8                 # darkness 0-15
SPEED = 3
X_SHIFT = 0                 # dots; nudge everything right (+) or left (-)

CARTON_W, CARTON_H, CARTON_GAP = 100, 75, 2          # mm

BOX_W, BOX_H, BOX_GAP = 30, 19, 2                    # mm, single label
BOX_ACROSS = 3                                       # labels per row (3-up)
BOX_COL_GAP = 2                                      # mm between columns
BOX_SIDE_MARGIN = 2                                  # mm liner edge to first label
BOX_ROLL_W = BOX_SIDE_MARGIN * 2 + BOX_W * BOX_ACROSS + BOX_COL_GAP * (BOX_ACROSS - 1)

DEFAULT_BRAND = "irfan"

SETTINGS = os.path.join(os.path.expanduser("~"), ".sticker_printer.json")

# ================================================================= fonts =====
# TSPL built-in fixed-width fonts: name -> (char width, char height) in dots.
FONTS = {"2": (12, 20), "3": (16, 24), "4": (24, 32), "5": (32, 48)}

# Every font x multiplier combo (width multiplier = height or one less, for a
# slightly condensed option), biggest first.
STYLES = sorted(
    [(f, xm, ym) for f in FONTS for ym in range(1, 5) for xm in (ym - 1, ym) if xm >= 1],
    key=lambda s: (-FONTS[s[0]][1] * s[2], -FONTS[s[0]][0] * s[1]),
)


def size_of(style, text):
    f, xm, ym = style
    return len(text) * FONTS[f][0] * xm, FONTS[f][1] * ym


def pick(text, max_w, max_h):
    """Biggest built-in style that fits text inside max_w x max_h dots."""
    for s in STYLES:
        w, h = size_of(s, text)
        if w <= max_w and h <= max_h:
            return s
    return ("2", 1, 1)


# ================================================================ layout =====
# A label is a list of items: (x, y, style, text), all in dots.

def dots(mm):
    return round(mm * DPMM)


def put(items, text, x, y, max_w, max_h, centre=False, style=None):
    style = style or pick(text, max_w, max_h)
    w, h = size_of(style, text)
    items.append((x + (max_w - w) // 2 if centre else x, y, style, text))
    return h


def carton(brand, article, colour, sizes, qty):
    """sizes: list of (size, pairs) tuples."""
    W = dots(CARTON_W)
    left = 24
    width = W - 2 * left
    items = []

    put(items, brand, left, 16, width, 96, centre=True)
    put(items, f"ART NO:{article}", left, 130, width, 64)
    put(items, f"COLOUR:{colour}", left, 210, width, 64)

    # SIZE: followed by a grid, sizes on top and pairs below
    y = 296
    label = "SIZE: "
    lab_style = pick(label, width, 64)
    put(items, label, left, y + 28, width, 64, style=lab_style)
    grid_x = left + size_of(lab_style, label)[0]
    if sizes:
        cols = [max(len(sz), len(str(p))) for sz, p in sizes]
        line = " ".join("8" * c for c in cols)           # widest the grid can be
        st = pick(line, W - left - grid_x, 52)
        cw, ch = FONTS[st[0]][0] * st[1], FONTS[st[0]][1] * st[2]
        x = grid_x
        for (sz, p), c in zip(sizes, cols):
            put(items, sz, x, y, c * cw, ch, centre=True, style=st)
            put(items, str(p), x, y + ch + 8, c * cw, ch, centre=True, style=st)
            x += (c + 1) * cw

    put(items, f"QTY: {qty} PRS", left, 450, width, 100)
    return items


def box(article, colour, size):
    """One label's items, positioned at x=0."""
    W, H = dots(BOX_W), dots(BOX_H)
    pad = 6
    row = (H - 2 * pad) // 3
    items = []
    for i, text in enumerate((article, colour, f"SIZE:{size}")):
        put(items, text, pad, pad + i * row, W - 2 * pad, row - 4, centre=True)
    return items


def box_row(article, colour, size):
    one = box(article, colour, size)
    return [(x + dots(BOX_SIDE_MARGIN + i * (BOX_W + BOX_COL_GAP)), y, st, t)
            for i in range(BOX_ACROSS) for x, y, st, t in one]


# ================================================================== TSPL =====

def tspl(items, w_mm, h_mm, gap_mm, copies):
    cmds = [
        f"SIZE {w_mm} mm,{h_mm} mm",
        f"GAP {gap_mm} mm,0",
        f"DIRECTION {DIRECTION}",
        "REFERENCE 0,0",
        f"DENSITY {DENSITY}",
        f"SPEED {SPEED}",
        "CLS",
    ]
    for x, y, (f, xm, ym), text in items:
        text = text.replace('"', "'")
        cmds.append(f'TEXT {x + X_SHIFT},{y},"{f}",0,{xm},{ym},"{text}"')
    cmds.append(f"PRINT 1,{copies}")
    return ("\r\n".join(cmds) + "\r\n").encode("ascii", "replace")


# ============================================================== printers =====

LABEL_HINTS = ("tsc", "tspl", "xprinter", "xp-", "gprinter", "gp-", "label",
               "ttp", "te2", "te3", "tdp", "hprt", "idprt", "rongta", "deli")


def list_printers():
    if platform.system() == "Windows":
        import win32print
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        names = [p[2] for p in win32print.EnumPrinters(flags, None, 1)]
    else:
        out = subprocess.run(["lpstat", "-e"], capture_output=True, text=True).stdout
        names = [n.strip() for n in out.splitlines() if n.strip()]
    # likely label printers first
    return sorted(names, key=lambda n: (not any(h in n.lower() for h in LABEL_HINTS), n.lower()))


def send_raw(printer, data):
    if platform.system() == "Windows":
        import win32print
        h = win32print.OpenPrinter(printer)
        try:
            win32print.StartDocPrinter(h, 1, ("Sticker", None, "RAW"))
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, data)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
    else:
        r = subprocess.run(["lp", "-d", printer, "-o", "raw"], input=data, capture_output=True)
        if r.returncode:
            raise RuntimeError(r.stderr.decode() or "lp failed")


# ==================================================================== UI =====

def parse_sizes(text):
    """'36:300, 37:300' or '36=300 37=300' -> [('36', 300), ('37', 300)]"""
    out = []
    for part in text.replace(",", " ").split():
        if ":" in part or "=" in part:
            sz, _, p = part.replace("=", ":").partition(":")
            out.append((sz.strip(), int(p) if p.strip().isdigit() else 0))
    return out


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sticker Printer")
        self.settings = self.load_settings()

        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        form = ttk.Frame(root)
        form.grid(row=0, column=0, sticky="nw")
        self.preview = tk.Canvas(root, width=380, height=290, bg="white",
                                 highlightthickness=1, highlightbackground="gray")
        self.preview.grid(row=0, column=1, sticky="n", padx=(20, 0))

        # printer
        ttk.Label(form, text="Printer").grid(row=0, column=0, sticky="w")
        self.printer = ttk.Combobox(form, state="readonly", width=34)
        self.printer.grid(row=0, column=1, sticky="we", pady=4)
        ttk.Button(form, text="↻", width=3, command=self.refresh_printers).grid(row=0, column=2, padx=4)

        # type
        ttk.Label(form, text="Sticker").grid(row=1, column=0, sticky="w")
        self.kind = tk.StringVar(value=self.settings.get("kind", "carton"))
        kinds = ttk.Frame(form)
        kinds.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Radiobutton(kinds, text=f"Carton {CARTON_W}×{CARTON_H}", value="carton",
                        variable=self.kind, command=self.switch).pack(side="left")
        ttk.Radiobutton(kinds, text=f"Box {BOX_W}×{BOX_H} ({BOX_ACROSS}-up)", value="box",
                        variable=self.kind, command=self.switch).pack(side="left", padx=12)

        self.fields = ttk.Frame(form)
        self.fields.grid(row=2, column=0, columnspan=3, sticky="we", pady=(8, 0))
        self.vars = {k: tk.StringVar() for k in
                     ("brand", "article", "colour", "sizes", "qty", "size", "copies")}
        self.vars["brand"].set(self.settings.get("brand", DEFAULT_BRAND))
        self.vars["copies"].set("1")
        for v in self.vars.values():
            v.trace_add("write", lambda *_: self.redraw())
        self.vars["sizes"].trace_add("write", lambda *_: self.auto_qty())

        ttk.Button(form, text="PRINT", command=self.do_print).grid(
            row=3, column=0, columnspan=3, sticky="we", pady=(16, 0), ipady=10)
        self.status = ttk.Label(form, text="", foreground="gray")
        self.status.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

        self.refresh_printers()
        self.switch()

    # ---------------------------------------------------------- settings --
    def load_settings(self):
        try:
            with open(SETTINGS) as f:
                return json.load(f)
        except Exception:
            return {}

    def save_settings(self):
        try:
            with open(SETTINGS, "w") as f:
                json.dump({"printer": self.printer.get(), "kind": self.kind.get(),
                           "brand": self.vars["brand"].get()}, f)
        except Exception:
            pass

    # ---------------------------------------------------------- printers --
    def refresh_printers(self):
        try:
            names = list_printers()
        except Exception as e:
            names = []
            self.status.config(text=f"Could not list printers: {e}")
        self.printer["values"] = names
        last = self.settings.get("printer")
        if last in names:
            self.printer.set(last)
        elif names:
            self.printer.current(0)
        else:
            self.printer.set("")

    # ------------------------------------------------------------ fields --
    def switch(self):
        for w in self.fields.winfo_children():
            w.destroy()
        if self.kind.get() == "carton":
            rows = [("Brand", "brand", ""), ("Article", "article", ""), ("Colour", "colour", ""),
                    ("Sizes", "sizes", "e.g. 36:300 37:300"), ("Qty (pairs)", "qty", "auto from sizes"),
                    ("Stickers", "copies", "")]
        else:
            rows = [("Article", "article", ""), ("Colour", "colour", ""), ("Size", "size", ""),
                    ("Stickers", "copies", f"rounded up to a multiple of {BOX_ACROSS}")]
        for i, (label, key, hint) in enumerate(rows):
            ttk.Label(self.fields, text=label).grid(row=i, column=0, sticky="w", pady=3)
            e = ttk.Entry(self.fields, textvariable=self.vars[key], width=30)
            e.grid(row=i, column=1, sticky="we", pady=3, padx=(12, 0))
            if hint:
                ttk.Label(self.fields, text=hint, foreground="gray").grid(row=i, column=2, sticky="w", padx=8)
            if i == (0 if self.kind.get() == "box" else 1):
                e.focus_set()
        self.redraw()

    def auto_qty(self):
        total = sum(p for _, p in parse_sizes(self.vars["sizes"].get()))
        if total:
            self.vars["qty"].set(str(total))

    # ------------------------------------------------------------ layout --
    def layout(self):
        """(items to print, (w, h, gap) mm, items to preview, preview size mm)"""
        v = {k: var.get().strip().upper() for k, var in self.vars.items()}
        if self.kind.get() == "carton":
            items = carton(self.vars["brand"].get().strip(), v["article"], v["colour"],
                           parse_sizes(v["sizes"]), v["qty"])
            return items, (CARTON_W, CARTON_H, CARTON_GAP), items, (CARTON_W, CARTON_H)
        return (box_row(v["article"], v["colour"], v["size"]), (BOX_ROLL_W, BOX_H, BOX_GAP),
                box(v["article"], v["colour"], v["size"]), (BOX_W, BOX_H))

    def redraw(self):
        """Rough preview: each built-in font drawn as Courier at the same height."""
        _, _, items, (w_mm, h_mm) = self.layout()
        scale = 360 / dots(w_mm)
        c = self.preview
        c.delete("all")
        c.config(width=dots(w_mm) * scale + 20, height=dots(h_mm) * scale + 20)
        c.create_rectangle(10, 10, 10 + dots(w_mm) * scale, 10 + dots(h_mm) * scale, outline="#bbb")
        for x, y, style, text in items:
            h = size_of(style, text)[1] * scale
            c.create_text(10 + x * scale, 10 + y * scale, text=text, anchor="nw",
                          font=("Courier", -max(6, int(h)), "bold"))

    # ------------------------------------------------------------- print --
    def do_print(self):
        printer = self.printer.get()
        if not printer:
            messagebox.showerror("Sticker Printer", "No printer selected.")
            return
        copies = int(self.vars["copies"].get()) if self.vars["copies"].get().isdigit() else 0
        if copies <= 0:
            messagebox.showerror("Sticker Printer", "Enter how many stickers to print.")
            return
        if not self.vars["article"].get().strip():
            messagebox.showerror("Sticker Printer", "Enter the article number.")
            return

        items, (w, h, gap), _, _ = self.layout()
        rows = copies if self.kind.get() == "carton" else math.ceil(copies / BOX_ACROSS)
        try:
            send_raw(printer, tspl(items, w, h, gap, rows))
        except Exception as e:
            messagebox.showerror("Sticker Printer", f"Print failed:\n{e}")
            return
        printed = rows if self.kind.get() == "carton" else rows * BOX_ACROSS
        self.status.config(text=f"Sent {printed} sticker(s) to {printer}")
        self.save_settings()


if __name__ == "__main__":
    App().mainloop()
