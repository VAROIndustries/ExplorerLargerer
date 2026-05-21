"""
ExplorerLargerer — Photo browser with HUGE thumbnails
Usage: python explorer_largerer.py [optional_folder_path]
"""

import tkinter as tk
from tkinter import ttk, filedialog
import os
import sys
import threading
from pathlib import Path
from PIL import Image, ImageTk

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
              '.tiff', '.tif', '.heif', '.heic', '.avif'}

# ── Colors ───────────────────────────────────────────────────────────────────
BG        = '#141414'
CARD_BG   = '#222222'
CARD_HOV  = '#2e2e2e'
BAR_BG    = '#1c1c1c'
SEP_COLOR = '#2a2a2a'
ACCENT    = '#4a90e2'
ACCENT_H  = '#357abd'
BTN_OFF   = '#2a2a2a'
TEXT_DIM  = '#666666'
TEXT_MED  = '#999999'
TEXT_LT   = '#dddddd'
THUMB_BG  = (34, 34, 34)    # RGB — matches CARD_BG for letterboxing

GAP = 6   # px gap between cells

# ── Sort options: (label, key_func, reverse) ─────────────────────────────────
SORT_OPTIONS = [
    ('Name A→Z',    lambda p: p.name.lower(),    False),
    ('Name Z→A',    lambda p: p.name.lower(),    True),
    ('Modified ↓',  lambda p: p.stat().st_mtime, True),
    ('Modified ↑',  lambda p: p.stat().st_mtime, False),
    ('Created ↓',   lambda p: p.stat().st_ctime, True),
    ('Created ↑',   lambda p: p.stat().st_ctime, False),
    ('File Size ↓', lambda p: p.stat().st_size,  True),
    ('File Size ↑', lambda p: p.stat().st_size,  False),
]


def letterbox(img: Image.Image, size: int) -> Image.Image:
    """Resize image to fit within size×size, centered on a solid background.
    Returns a new PIL image that is exactly size×size — guaranteeing uniform cells."""
    img = img.copy()
    img.thumbnail((size, size), Image.LANCZOS)
    bg = Image.new('RGB', (size, size), THUMB_BG)
    x = (size - img.width)  // 2
    y = (size - img.height) // 2
    if img.mode in ('RGBA', 'LA', 'PA'):
        bg.paste(img.convert('RGBA'), (x, y), img.convert('RGBA'))
    else:
        bg.paste(img.convert('RGB'), (x, y))
    return bg


class App(tk.Tk):
    def __init__(self, start_folder=None):
        super().__init__()
        self.title('ExplorerLargerer')
        self.geometry('1400x900')
        self.configure(bg=BG)
        self.minsize(500, 400)

        self._paths      : list  = []   # sorted list of Path objects
        self._thumb_size = tk.IntVar(value=400)
        self._fixed_cols : int | None = None   # None = auto
        self._sort_idx   = 0
        self._gen        = 0    # incremented on every redraw — invalidates stale threads
        self._photo_refs : list  = []
        self._pending    = None  # pending after() handle for debounce
        self._col_btns   : list  = []

        self._build_ui()
        self.update_idletasks()

        if start_folder and Path(start_folder).is_dir():
            self.after(100, lambda: self._load_folder(start_folder))

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_toolbar()
        self._build_canvas()

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=BAR_BG)
        bar.pack(fill='x', side='top')

        # ── Row 1: Open + Size slider + Status ───────────────────────────────
        r1 = tk.Frame(bar, bg=BAR_BG, pady=8)
        r1.pack(fill='x')

        tk.Button(r1, text='Open Folder', command=self.open_folder,
                  bg=ACCENT, fg='white',
                  activebackground=ACCENT_H, activeforeground='white',
                  relief='flat', padx=14, pady=5,
                  font=('Segoe UI', 10, 'bold'), cursor='hand2', bd=0,
                  ).pack(side='left', padx=(12, 0))

        tk.Label(r1, text='Size:', bg=BAR_BG, fg=TEXT_DIM,
                 font=('Segoe UI', 9)).pack(side='left', padx=(22, 6))

        self._slider = ttk.Scale(r1, from_=60, to=1000, variable=self._thumb_size,
                                 orient='horizontal', length=200,
                                 command=self._on_slider_move)
        self._slider.pack(side='left')

        self._size_lbl = tk.Label(r1, text='400 px', bg=BAR_BG, fg=TEXT_LT,
                                  font=('Segoe UI Mono', 9), width=7)
        self._size_lbl.pack(side='left', padx=5)

        self._status = tk.Label(r1, text='No folder open', bg=BAR_BG, fg=TEXT_DIM,
                                font=('Segoe UI', 9))
        self._status.pack(side='right', padx=14)

        # ── Separator ────────────────────────────────────────────────────────
        tk.Frame(bar, bg=SEP_COLOR, height=1).pack(fill='x')

        # ── Row 2: Column buttons + Sort ─────────────────────────────────────
        r2 = tk.Frame(bar, bg=BAR_BG, pady=6)
        r2.pack(fill='x')

        tk.Label(r2, text='Columns:', bg=BAR_BG, fg=TEXT_DIM,
                 font=('Segoe UI', 9)).pack(side='left', padx=(12, 6))

        self._col_btns = []
        for n in range(1, 7):
            btn = tk.Button(r2, text=str(n), width=3,
                            bg=BTN_OFF, fg=TEXT_MED,
                            activebackground=ACCENT_H, activeforeground='white',
                            relief='flat', bd=0, padx=4, pady=2,
                            font=('Segoe UI', 9, 'bold'), cursor='hand2',
                            command=lambda c=n: self._set_fixed_cols(c))
            btn.pack(side='left', padx=2)
            self._col_btns.append(btn)

        self._auto_btn = tk.Button(r2, text='Auto', width=5,
                                   bg=ACCENT, fg='white',
                                   activebackground=ACCENT_H, activeforeground='white',
                                   relief='flat', bd=0, padx=4, pady=2,
                                   font=('Segoe UI', 9, 'bold'), cursor='hand2',
                                   command=self._set_auto_cols)
        self._auto_btn.pack(side='left', padx=(2, 24))

        tk.Label(r2, text='Sort:', bg=BAR_BG, fg=TEXT_DIM,
                 font=('Segoe UI', 9)).pack(side='left', padx=(0, 6))

        self._sort_var = tk.StringVar(value=SORT_OPTIONS[0][0])
        cb = ttk.Combobox(r2, textvariable=self._sort_var, state='readonly',
                          values=[s[0] for s in SORT_OPTIONS],
                          width=14, font=('Segoe UI', 9))
        cb.pack(side='left')
        cb.bind('<<ComboboxSelected>>', self._on_sort_change)

        self.bind('<Control-o>', lambda _: self.open_folder())
        self.bind('<plus>',  lambda _: self._nudge_size(+50))
        self.bind('<minus>', lambda _: self._nudge_size(-50))
        self.bind('<equal>', lambda _: self._nudge_size(+50))

    def _build_canvas(self):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill='both', expand=True)

        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient='vertical', command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self._canvas.pack(side='left', fill='both', expand=True)

        self._grid = tk.Frame(self._canvas, bg=BG)
        self._cwin = self._canvas.create_window((0, 0), window=self._grid, anchor='nw')

        self._grid.bind('<Configure>',
                        lambda _: self._canvas.configure(
                            scrollregion=self._canvas.bbox('all')))
        self._canvas.bind('<Configure>', self._on_canvas_resize)
        for w in (self._canvas, self._grid):
            w.bind('<MouseWheel>', self._on_mousewheel)

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * event.delta / 120), 'units')

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._cwin, width=event.width)
        self._schedule_redraw()

    def _on_slider_move(self, val):
        v = int(float(val))
        self._thumb_size.set(v)
        self._size_lbl.config(text=f'{v} px')
        self._fixed_cols = None
        self._update_col_btn_ui()
        self._schedule_redraw()

    def _on_sort_change(self, _=None):
        name = self._sort_var.get()
        self._sort_idx = next(i for i, s in enumerate(SORT_OPTIONS) if s[0] == name)
        self._apply_sort()
        self._schedule_redraw()

    def _nudge_size(self, delta):
        v = max(60, min(1000, self._thumb_size.get() + delta))
        self._thumb_size.set(v)
        self._slider.set(v)
        self._size_lbl.config(text=f'{v} px')
        self._fixed_cols = None
        self._update_col_btn_ui()
        self._schedule_redraw()

    def _set_fixed_cols(self, n: int):
        self._fixed_cols = n
        self._update_col_btn_ui()
        self._apply_size_for_cols(n)
        self._schedule_redraw()

    def _set_auto_cols(self):
        self._fixed_cols = None
        self._update_col_btn_ui()
        self._schedule_redraw()

    def _apply_size_for_cols(self, cols: int):
        """Compute and set thumb_size so `cols` columns fill the canvas width."""
        w = self._canvas.winfo_width() or (self.winfo_width() - 20)
        size = max(60, (w - (cols + 1) * GAP) // cols)
        self._thumb_size.set(size)
        self._slider.set(size)
        self._size_lbl.config(text=f'{size} px')

    def _update_col_btn_ui(self):
        """Highlight the active column button, dim the rest."""
        for i, btn in enumerate(self._col_btns):
            if self._fixed_cols == i + 1:
                btn.config(bg=ACCENT, fg='white')
            else:
                btn.config(bg=BTN_OFF, fg=TEXT_MED)
        if self._fixed_cols is None:
            self._auto_btn.config(bg=ACCENT, fg='white')
        else:
            self._auto_btn.config(bg=BTN_OFF, fg=TEXT_MED)

    def _schedule_redraw(self):
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(160, self._redraw_grid)

    # ── Folder & Sort ─────────────────────────────────────────────────────────

    def open_folder(self):
        folder = filedialog.askdirectory(title='Select Photo Folder')
        if folder:
            self._load_folder(folder)

    def _load_folder(self, folder: str):
        raw = [p for p in Path(folder).iterdir()
               if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        self._paths = raw
        self._apply_sort()
        n = len(self._paths)
        base = os.path.basename(folder)
        self._status.config(text=f'{n} image{"s" if n != 1 else ""}  —  {base}')
        self.title(f'ExplorerLargerer  —  {base}')
        self._redraw_grid()

    def _apply_sort(self):
        _, key_fn, reverse = SORT_OPTIONS[self._sort_idx]
        try:
            self._paths.sort(key=key_fn, reverse=reverse)
        except Exception:
            pass

    # ── Grid ──────────────────────────────────────────────────────────────────

    def _redraw_grid(self):
        self._pending = None

        # Bump generation — any running thread will see the new value and abort
        self._gen += 1
        gen = self._gen

        # If in fixed-col mode, recompute size for current window width
        if self._fixed_cols is not None:
            self._apply_size_for_cols(self._fixed_cols)

        thumb_size = self._thumb_size.get()
        canvas_w   = self._canvas.winfo_width() or (self.winfo_width() - 20)

        cols = (self._fixed_cols if self._fixed_cols is not None
                else max(1, canvas_w // (thumb_size + GAP * 2)))

        # Wipe existing grid widgets and photo refs
        for w in self._grid.winfo_children():
            w.destroy()
        self._photo_refs.clear()

        if not self._paths:
            tk.Label(self._grid, text='Open a folder  (Ctrl+O)',
                     bg=BG, fg='#333333', font=('Segoe UI', 14)).pack(pady=140)
            self._canvas.configure(scrollregion=self._canvas.bbox('all'))
            return

        # Update status
        title_base = self.title().split('  —  ', 1)[-1]
        self._status.config(
            text=f'{len(self._paths)} images  —  {title_base}  '
                 f'({thumb_size}px · {cols} col{"s" if cols != 1 else ""})'
        )

        # Kick off background thumbnail loader
        threading.Thread(
            target=self._worker,
            args=(list(self._paths), thumb_size, cols, gen),
            daemon=True
        ).start()

    def _worker(self, paths, thumb_size, cols, gen):
        """Background: load + letterbox each image, then hand off to main thread."""
        frames = []
        for path in paths:
            if self._gen != gen:
                return   # generation changed — discard work
            try:
                with Image.open(path) as img:
                    thumb = letterbox(img, thumb_size)
                photo = ImageTk.PhotoImage(thumb)
                frames.append((photo, path.name, path))
            except Exception:
                pass

        if self._gen == gen:
            self.after(0, self._place_grid, frames, cols, gen)

    def _place_grid(self, frames, cols, gen):
        """Main thread: place PhotoImage widgets into the grid."""
        if self._gen != gen:
            return   # stale — a newer redraw already owns the grid

        thumb_size = self._thumb_size.get()

        for i, (photo, name, path) in enumerate(frames):
            row, col = divmod(i, cols)

            cell = tk.Frame(self._grid, bg=CARD_BG, cursor='hand2',
                            padx=0, pady=0)
            cell.grid(row=row, column=col, padx=GAP, pady=GAP, sticky='nw')

            img_lbl = tk.Label(cell, image=photo, bg=CARD_BG,
                               cursor='hand2', bd=0, highlightthickness=0)
            img_lbl.pack()
            img_lbl.photo = photo          # prevent GC
            self._photo_refs.append(photo)

            short = name if len(name) <= 34 else name[:31] + '…'
            name_lbl = tk.Label(cell, text=short, bg=CARD_BG, fg=TEXT_DIM,
                                font=('Segoe UI', 8), wraplength=thumb_size,
                                pady=4)
            name_lbl.pack()

            all_w = [cell, img_lbl, name_lbl]

            def _enter(_, ws=all_w):
                for w in ws:
                    try: w.configure(bg=CARD_HOV)
                    except Exception: pass

            def _leave(_, ws=all_w):
                for w in ws:
                    try: w.configure(bg=CARD_BG)
                    except Exception: pass

            for w in all_w:
                w.bind('<Enter>',      _enter)
                w.bind('<Leave>',      _leave)
                w.bind('<Button-1>',   lambda _, p=path: os.startfile(str(p)))
                w.bind('<MouseWheel>', self._on_mousewheel)

        self._canvas.configure(scrollregion=self._canvas.bbox('all'))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    App(start_folder=sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
