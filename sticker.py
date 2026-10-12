# -*- coding: utf-8 -*-
"""贴图：把 PNG/JPG 盖到指定页上，位置大小用页面比例记录。
sticker.csv 列：页号, 图片路径, x, y, w（x/y=左上角比例，w=图宽占页宽比例）
"""

import csv
import tempfile
from pathlib import Path

import fitz

HDR = ["页号", "图片", "x", "y", "w"]


def load_stickers(work_dir: Path):
    p = work_dir / "sticker.csv"
    if not p.exists():
        return list(HDR), []
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], [r for r in rows[1:] if r and r[0].strip()]


def save_stickers(work_dir: Path, header, body):
    with open(work_dir / "sticker.csv", "w", encoding="utf-8-sig",
              newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(body)


def add_sticker(work_dir: Path, pno: int, img: str):
    """新增一张贴图：默认居中、宽 30%。返回新行。"""
    header, body = load_stickers(work_dir)    
    row = [str(pno), str(img), "0.35", "0.35", "0.3"]
    body.append(row)
    save_stickers(work_dir, header, body)
    return row


def paste_on_page(page, rows):
    """rebuilder 调用：把某页的所有贴图盖到 PDF 页上。"""
    pw, ph = page.rect.width, page.rect.height
    for r in rows:
        try:
            img, x, y, w = r[1], float(r[2]), float(r[3]), float(r[4])
        except (ValueError, IndexError):
            continue
        if not (0 <= x < 1 and 0 <= y < 1 and 0.02 <= w <= 2):
            continue
        try:
            pix = fitz.Pixmap(img)
        except RuntimeError:
            continue  # 图片文件没了/坏了，跳过不炸
        aspect = pix.height / pix.width
        rect = fitz.Rect(x * pw, y * ph,
                         x * pw + w * pw, y * ph + w * pw * aspect)
        page.insert_image(rect, filename=img)


# ---------- 调整窗口 ----------

def open_editor(app, pno: int):
    StickerEditor(app, pno)


class StickerEditor:
    """单页贴图调整：拖动=挪位置，滚轮=缩放选中项，松手即存。"""

    def __init__(self, app, pno):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.app = app
        self.pno = pno
        self.work = app.work_dir
        self.png = self.work / f"{pno:03d}.png"
        if not self.png.exists():
            app.log_print(f"[贴图] 找不到第{pno}页的缩略图，先拆页")
            return
        self.header, self.rows = load_stickers(self.work)
        self.rows = [r for r in self.rows if r[0].lstrip("0") == str(pno)]

        self.win = tk.Toplevel()
        self.win.title(f"贴图调整 · 原第{pno}页（拖动挪位置，滚轮缩放）")
        self.scale = 1.0
        self.sel = None
        self.drag = None
        self._imgs = {}         
        self.zoom = 1.0          # 整页视图缩放
        self.offx = self.offy = 0  # 平移偏移
        self.pan = None          # 平移拖动中
        self._bg_img = None       # 整页大图缓存（只解码一次）
        self._thumb_cache = {}    # (图片路径, 宽度) -> PhotoImage

        self.canvas = tk.Canvas(self.win, bg="#2b2b2b",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

    # ---- 坐标换算：比例 ↔ 画布像素 ----
    def _page_rect(self):
        cw = max(self.canvas.winfo_width() - 20, 100)
        ch = max(self.canvas.winfo_height() - 20, 100)
        iw = self.tk_img.width()
        ih = self.tk_img.height()
        s = min(cw / iw, ch / ih, 1.0) * self.zoom
        w, h = iw * s, ih * s
        return 10 + self.offx, 10 + self.offy, w, h, s

    def redraw(self):
        self.canvas.delete("all")
        if self._bg_img is None:
            self._bg_img = self.tk.PhotoImage(file=str(self.png))
        self.tk_img = self._bg_img            # _page_rect 要读它的宽高
        x0, y0, w, h, s = self._page_rect()
        self.canvas.create_image(x0, y0, anchor="nw", image=self.tk_img)
        self._imgs.clear()
        for i, r in enumerate(self.rows):
            fx, fy, fw = float(r[2]), float(r[3]), float(r[4])
            ix, iy = x0 + fx * w, y0 + fy * h
            iw = fw * w
            key = (r[1], int(iw))
            img = self._thumb_cache.get(key)
            if img is None:
                img = self._thumb(r[1], int(iw))
                if img is not None:
                    self._thumb_cache[key] = img
            if img is None:
                self.canvas.create_rectangle(ix, iy, ix + iw, iy + 40,
                                             outline="red")
                continue
            self.canvas.create_image(ix, iy, anchor="nw", image=img)
            self._imgs[i] = img
            if i == self.sel:
                self.canvas.create_rectangle(ix - 2, iy - 2,
                                             ix + iw + 2, iy + img.height() + 2,
                                             outline="#e33", width=2)
        self._geo = (x0, y0, w, h)
                
    def _thumb(self, path, width):
        """把任意图片转成 PNG 临时文件再上画布（PhotoImage 不认 JPG）。"""
        try:
            pix = fitz.Pixmap(path)
            if pix.alpha:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if width < 4:
                width = 4
            f = max(width / pix.width, 0.01)
            pix = fitz.Pixmap(pix, int(pix.width * f), int(pix.height * f))
            tmp = Path(tempfile.gettempdir()) / "stk_tmp.png"
            pix.save(tmp)
            return self.tk.PhotoImage(file=str(tmp))
        except RuntimeError:
            return None

    def _hit(self, mx, my):
        x0, y0, w, h = self._geo
        for i, r in enumerate(self.rows):
            fx, fy, fw = float(r[2]), float(r[3]), float(r[4])
            ix, iy = x0 + fx * w, y0 + fy * h
            img = self._imgs.get(i)
            ih = img.height() if img else 40
            if ix <= mx <= ix + fw * w and iy <= my <= iy + ih:
                return i
        return None

    def on_press(self, e):
        self.sel = self._hit(e.x, e.y)
        self.pan = None if self.sel is not None else (e.x, e.y)
        self.drag = (e.x, e.y)
        self.redraw()
        
    def on_motion(self, e):
        if self.pan is not None:                 # 空白处拖动 = 平移整页
            self.offx += e.x - self.pan[0]
            self.offy += e.y - self.pan[1]
            self.pan = (e.x, e.y)
            self.redraw()
            return
        if self.sel is None or self.drag is None:
            return
        x0, y0, w, h = self._geo
        dx = (e.x - self.drag[0]) / w
        dy = (e.y - self.drag[1]) / h
        r = self.rows[self.sel]
        r[2] = f"{min(max(float(r[2]) + dx, 0), 0.98):.4f}"
        r[3] = f"{min(max(float(r[3]) + dy, 0), 0.98):.4f}"
        self.drag = (e.x, e.y)
        self.redraw()
        
    def on_release(self, e):
        self.pan = None
        self.drag = None
        self.save()

    def on_wheel(self, e):
        if self.sel is None or (e.state & 0x0004):   # 没选中 或 Ctrl按住 = 缩放视图
            step = 1.1 if e.delta > 0 else 1 / 1.1
            self.zoom = min(max(self.zoom * step, 0.3), 5.0)
            self.redraw()
            return
        step = 0.03 if e.delta > 0 else -0.03        # 选中贴图 = 缩放贴图本身
        r = self.rows[self.sel]
        r[4] = f"{min(max(float(r[4]) + step, 0.05), 1.5):.4f}"
        self.redraw()
        self.save()
        
    def save(self):
        all_header, all_rows = load_stickers(self.work)
        keep = [r for r in all_rows if r[0].lstrip("0") != str(self.pno)]
        save_stickers(self.work, all_header, keep + self.rows)

    def close(self):
        self.save()
        self.win.destroy()
