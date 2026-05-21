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

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.heif', '.heic', '.avif'}

DARK_BG     = '#141414'
CARD_BG     = '#242424'
CARD_HOVER  = '#303030'
TOOLBAR_BG  = '#1e1e1e'
ACCENT      = '#4a90e2'
TEXT_DIM    = '#888888'
TEXT_LIGHT  = '#cccccc'


class PhotoExplorer(tk.Tk):
    def __init__(self, start_folder=None):
        super().__init__()
        self.title('ExplorerLargerer')
        self.geometry('1400x900')
        self.configure(bg=DARK_BG)
        self.minsize(600, 400)

        self._thumb_size   = tk.IntVar(value=400)
        self._size_display = tk.StringVar(value='400 px')
        self._image_paths  = []
        self._photo_refs   = []   # prevent GC of PhotoImage objects
        self._cancel_flag  = threading.Event()
        self._load_thread  = None
        self._pending_redraw = None

        self._build_ui()
        self.update_idletasks()

        if start_folder and Path(start_folder).is_dir():
            self.after(100, lambda: self._load_folder(start_folder))

    # ------------------------------------------------------------------ UI build

    def _build_ui(self):
        self._build_toolbar()
        self._build_canvas()

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=TOOLBAR_BG, pady=8)
        bar.pack(fill='x', side='top')

        tk.Button(
            bar, text='Open Folder', command=self.open_folder,
            bg=ACCENT, fg='white', activebackground='#357abd', activeforeground='white',
            relief='flat', padx=14, pady=5, font=('Segoe UI', 10, 'bold'), cursor='hand2',
            bd=0
        ).pack(side='left', padx=(12, 0))

        tk.Label(bar, text='Size:', bg=TOOLBAR_BG, fg=TEXT_DIM,
                 font=('Segoe UI', 9)).pack(side='left', padx=(24, 6))

        style = ttk.Style()
        style.theme_use('default')
        style.configure('Dark.Horizontal.TScale', background=TOOLBAR_BG, troughcolor='#3a3a3a',
                        sliderlength=18, sliderrelief='flat')

        self._slider = ttk.Scale(
            bar, from_=80, to=1000, variable=self._thumb_size,
            orient='horizontal', length=220, style='Dark.Horizontal.TScale',
            command=self._on_slider_move
        )
        self._slider.pack(side='left')

        tk.Label(bar, textvariable=self._size_display, bg=TOOLBAR_BG, fg=TEXT_LIGHT,
                 font=('Segoe UI Mono', 9), width=7).pack(side='left', padx=6)

        self._status = tk.Label(bar, text='No folder open', bg=TOOLBAR_BG, fg=TEXT_DIM,
                                font=('Segoe UI', 9))
        self._status.pack(side='right', padx=14)

        self.bind('<Control-o>', lambda _: self.open_folder())
        self.bind('<plus>',      lambda _: self._nudge_size(+50))
        self.bind('<minus>',     lambda _: self._nudge_size(-50))
        self.bind('<equal>',     lambda _: self._nudge_size(+50))

    def _build_canvas(self):
        outer = tk.Frame(self, bg=DARK_BG)
        outer.pack(fill='both', expand=True)

        self._canvas = tk.Canvas(outer, bg=DARK_BG, highlightthickness=0)
        self._vscroll = ttk.Scrollbar(outer, orient='vertical', command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)

        self._vscroll.pack(side='right', fill='y')
        self._canvas.pack(side='left', fill='both', expand=True)

        self._grid_frame = tk.Frame(self._canvas, bg=DARK_BG)
        self._canvas_win = self._canvas.create_window((0, 0), window=self._grid_frame, anchor='nw')

        self._grid_frame.bind('<Configure>', self._sync_scrollregion)
        self._canvas.bind('<Configure>', self._on_canvas_resize)

        for w in (self._canvas, self._grid_frame):
            w.bind('<MouseWheel>', self._on_scroll)

    # ------------------------------------------------------------------ events

    def _sync_scrollregion(self, _=None):
        self._canvas.configure(scrollregion=self._canvas.bbox('all'))

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_win, width=event.width)
        self._schedule_redraw()

    def _on_scroll(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    def _on_slider_move(self, val):
        v = int(float(val))
        self._thumb_size.set(v)
        self._size_display.set(f'{v} px')
        self._schedule_redraw()

    def _nudge_size(self, delta):
        v = max(80, min(1000, self._thumb_size.get() + delta))
        self._thumb_size.set(v)
        self._slider.set(v)
        self._size_display.set(f'{v} px')
        self._schedule_redraw()

    def _schedule_redraw(self):
        """Debounce redraws so slider drag doesn't flood threads."""
        if self._pending_redraw:
            self.after_cancel(self._pending_redraw)
        self._pending_redraw = self.after(180, self._redraw_grid)

    # ------------------------------------------------------------------ folder

    def open_folder(self):
        folder = filedialog.askdirectory(title='Select Photo Folder')
        if folder:
            self._load_folder(folder)

    def _load_folder(self, folder):
        paths = sorted(
            p for p in Path(folder).iterdir()
            if p.suffix.lower() in IMAGE_EXTS
        )
        self._image_paths = paths
        n = len(paths)
        label = os.path.basename(folder)
        self._status.config(text=f'{n} image{"s" if n != 1 else ""}  —  {label}')
        self.title(f'ExplorerLargerer  —  {label}')
        self._redraw_grid()

    # ------------------------------------------------------------------ grid

    def _redraw_grid(self):
        self._pending_redraw = None

        # Stop any running load
        self._cancel_flag.set()
        if self._load_thread and self._load_thread.is_alive():
            self._load_thread.join(timeout=0.3)
        self._cancel_flag.clear()

        # Wipe current grid
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._photo_refs.clear()

        if not self._image_paths:
            self._show_empty()
            return

        thumb_size = self._thumb_size.get()
        canvas_w   = self._canvas.winfo_width() or (self.winfo_width() - 20)
        cell_size  = thumb_size + 20          # padding
        cols       = max(1, canvas_w // cell_size)

        self._status.config(text=self._status.cget('text').split('  —  ')[0] +
                            f'  —  {os.path.basename(str(self._image_paths[0].parent))}  '
                            f'({thumb_size}px · {cols} col{"s" if cols > 1 else ""})')

        self._load_thread = threading.Thread(
            target=self._worker,
            args=(list(self._image_paths), thumb_size, cols),
            daemon=True
        )
        self._load_thread.start()

    def _show_empty(self):
        tk.Label(
            self._grid_frame,
            text='Open a folder with  Ctrl+O  or click "Open Folder"',
            bg=DARK_BG, fg='#444444',
            font=('Segoe UI', 14)
        ).pack(expand=True, pady=120)
        self._sync_scrollregion()

    def _worker(self, paths, thumb_size, cols):
        """Background thread: load + resize thumbnails, then hand to main thread."""
        batch = []
        for path in paths:
            if self._cancel_flag.is_set():
                return
            try:
                with Image.open(path) as img:
                    img.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                batch.append((photo, path.name, path))
            except Exception:
                pass

        if not self._cancel_flag.is_set():
            self.after(0, self._place_grid, batch, thumb_size, cols)

    def _place_grid(self, frames, thumb_size, cols):
        if self._cancel_flag.is_set():
            return

        GAP = 10
        for i, (photo, name, path) in enumerate(frames):
            row, col = divmod(i, cols)

            cell = tk.Frame(self._grid_frame, bg=CARD_BG, padx=6, pady=6,
                            cursor='hand2')
            cell.grid(row=row, column=col, padx=GAP // 2, pady=GAP // 2, sticky='n')

            # Fixed-size image area so cells align even for portrait/landscape mix
            img_container = tk.Frame(cell, bg=CARD_BG,
                                     width=thumb_size, height=thumb_size)
            img_container.pack_propagate(False)
            img_container.pack()

            img_lbl = tk.Label(img_container, image=photo, bg=CARD_BG, cursor='hand2')
            img_lbl.place(relx=0.5, rely=0.5, anchor='center')
            img_lbl.photo = photo   # keep reference
            self._photo_refs.append(photo)

            short_name = name if len(name) <= 32 else name[:29] + '…'
            name_lbl = tk.Label(cell, text=short_name, bg=CARD_BG, fg=TEXT_DIM,
                                font=('Segoe UI', 8), wraplength=thumb_size)
            name_lbl.pack(pady=(4, 0))

            # Hover highlight
            all_widgets = [cell, img_container, img_lbl, name_lbl]

            def _enter(_, widgets=all_widgets):
                for w in widgets:
                    try:
                        w.configure(bg=CARD_HOVER)
                    except tk.TclError:
                        pass

            def _leave(_, widgets=all_widgets):
                for w in widgets:
                    try:
                        w.configure(bg=CARD_BG)
                    except tk.TclError:
                        pass

            for w in all_widgets:
                w.bind('<Enter>', _enter)
                w.bind('<Leave>', _leave)
                w.bind('<Button-1>', lambda _, p=path: self._open_image(p))
                w.bind('<MouseWheel>', self._on_scroll)

        self._sync_scrollregion()

    # ------------------------------------------------------------------ open

    def _open_image(self, path):
        try:
            os.startfile(str(path))
        except Exception as e:
            print(f'Could not open {path}: {e}')


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    app = PhotoExplorer(start_folder=folder)
    app.mainloop()
