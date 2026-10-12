# -*- coding: utf-8 -*-
"""页面拖拽排序：缩略图网格，拖动换位、单击选中、删页/变空白，实时写回 order.csv。
缩略图直接用 工作文件 里拆页生成的 PNG（不重复渲染）。
"""

import tkinter as tk
import ttkbootstrap as ttk
from PIL import Image, ImageTk

CELL_W, CELL_H = 132, 186
TH_W = 116


class PageDragWindow:
    def __init__(self, app):
        self.app = app
        self.work_dir = app.work_dir
        # 从 order_body 读当前页序（内容跟随：有替就用替的图）
        self.pages = []
        for r in app.order_body:
            try:
                old = int(r[1])
                rf = (r[2].strip() if len(r) > 2 else "")
            except (ValueError, IndexError):
                continue
            self.pages.append({"old": old, "rf": rf})

        self.sel = None      # 选中的位置（0 基）
        self.press = None    # (位置, x, y)
        self.drag_i = None
        self.photos = []     # 兼容旧引用，不再用于防回收
        self._cache = {}     # 缩略图缓存：路径 -> PhotoImage / "missing"
        self._cfg_job = None # Configure 防抖句柄
        self.win = tk.Toplevel(app.win)
        self.win.title("页面拖拽排序（拖动换位，改动实时保存）")
        self.win.geometry("1020x720")

        bar = ttk.Frame(self.win)
        bar.pack(fill="x", padx=8, pady=6)
        ttk.Button(bar, text="删除选中页", bootstyle="danger outline",
                   command=self.del_sel).pack(side="left", padx=3)
        ttk.Button(bar, text="选中页变空白", bootstyle="secondary outline",
                   command=self.blank_sel).pack(side="left", padx=3)
        ttk.Button(bar, text="关 闭", bootstyle="primary",
                   command=self.close).pack(side="right", padx=3)
        ttk.Label(bar, text="拖动缩略图换位置；单击选中（红框）；改动实时写回 order.csv"
                  ).pack(side="left", padx=12)

        self.canvas = tk.Canvas(self.win, bg="#f2f2f2", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Configure>", self._on_resize)        
        self.canvas.bind_all("<MouseWheel>", self.on_wheel)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.redraw()

    # ---------- 布局换算 ----------
    def _on_resize(self, e=None):
        """Configure 防抖：150ms 内的连续触发合并成一次重绘。"""
        if self._cfg_job:
            return
        self._cfg_job = self.win.after(150, self._do_redraw)

    def _do_redraw(self):
        self._cfg_job = None
        try:
            self.redraw()
        except tk.TclError:
            pass          # 窗口已关，忽略
        
    def _cols(self):
        w = max(self.canvas.winfo_width(), 1)
        return max(1, w // CELL_W)

    def _pos(self, i):
        cols = self._cols()
        return (i % cols) * CELL_W + 6, (i // cols) * CELL_H + 6

    def _index_at(self, x, y):
        cols = self._cols()
        i = (y // CELL_H) * cols + (x // CELL_W)
        return i if 0 <= i < len(self.pages) else None

    def _target(self, x, y):
        """落点 = 插到哪一格的前面/后面（按指针在该格左半还是右半）。"""
        cols = self._cols()
        col, row = x // CELL_W, y // CELL_H
        t = row * cols + col + (1 if (x % CELL_W) > CELL_W // 2 else 0)
        return max(0, min(t, len(self.pages)))

    def _thumb(self, src):
        """src=0 是空白页；文件缺失返回 'missing'。结果进 _cache。"""
        if src in (0, "0"):
            return None
        p = self.work_dir / f"{int(src):03d}.png"
        if not p.exists():
            return "missing"
        key = str(p)
        if key in self._cache:
            return self._cache[key]
        img = Image.open(p)
        k = TH_W / img.width
        img = img.resize((TH_W, max(1, int(img.height * k))))
        ph = ImageTk.PhotoImage(img)
        self._cache[key] = ph
        return ph
    
    # ---------- 绘制 ----------
    def redraw(self):
        self.canvas.delete("all")
        for i, p in enumerate(self.pages):
            x, y = self._pos(i)
            ph = self._thumb(p["rf"] if p["rf"] else p["old"])
            if ph is None:
                self.canvas.create_rectangle(x, y, x + TH_W, y + 150,
                                             fill="#d9d9d9", outline="#aaaaaa")
                self.canvas.create_text(x + TH_W // 2, y + 75, text="空白页",
                                        fill="#888888")
            elif ph == "missing":
                self.canvas.create_rectangle(x, y, x + TH_W, y + 150,
                                             fill="#f5d7d7", outline="#cc8888")
                self.canvas.create_text(x + TH_W // 2, y + 75,
                                        text=f"缺图(原{p['old']}页)",
                                        fill="#aa3333", font=("", 8))
            else:
                self.canvas.create_image(x, y, anchor="nw", image=ph)
            outline = "#e53935" if self.sel == i else "#bbbbbb"
            self.canvas.create_rectangle(x, y, x + TH_W, y + 152,
                                         outline=outline, width=2)
            mark = f" ←原{p['rf']}页" if p["rf"] else ""
            self.canvas.create_text(x + 2, y + 155, anchor="nw",
                                    text=f"第{i+1}位 ← 原{p['old']}页{mark}",
                                    font=("Microsoft YaHei UI", 8))
        cols = self._cols()
        rows = (len(self.pages) + cols - 1) // cols + 1
        self.canvas.configure(scrollregion=(0, 0, cols * CELL_W, rows * CELL_H))

    # ---------- 拖拽 ----------
    def on_press(self, e):
        self.press = (self._index_at(e.x, e.y), e.x, e.y)
        self.drag_i = None
        self.copying = bool(e.state & 0x0004)   # Ctrl 按住 = 复制模式

    def on_motion(self, e):
        if self.press is None:
            return
        i0, x0, y0 = self.press
        if abs(e.x - x0) + abs(e.y - y0) < 8:
            return
        self.drag_i = i0
        self.canvas.delete("ind")
        t = self._target(e.x, e.y)
        px, py = (self._pos(len(self.pages) - 1)[0] + CELL_W - 8,
                  self._pos(len(self.pages) - 1)[1]) if t >= len(self.pages) \
                 else self._pos(t)
        self.canvas.create_line(px, py + 4, px, py + CELL_H - 8,
                                fill="#e53935", width=3, tags="ind")

    def on_release(self, e):
        self.canvas.delete("ind")
        i0 = self.press[0] if self.press else None
        self.press = None
        if self.drag_i is not None:
            if self.copying:
                tgt = self._index_at(e.x, e.y)
                self.drag_i = None
                if tgt is not None and tgt != i0:
                    src = self.pages[i0]
                    content = src["rf"] if src["rf"] else src["old"]
                    if content in (0, "0"):
                        self.app.log_print("[拖拽排序] 空白页没法复制")
                    else:
                        self.pages[tgt]["rf"] = str(content)
                        self.sel = None
                        self.save(f"第{tgt+1}位已复制原第{content}页（原内容被覆盖）")
                        self.redraw()
                return
            t = self._target(e.x, e.y)
            if t > i0:
                t -= 1
            if t != i0:
                self.pages.insert(t, self.pages.pop(i0))
                self.sel = None
                self.save("页序已调整")
            self.drag_i = None
            self.redraw()
            return
        if i0 is not None:
            self.sel = None if self.sel == i0 else i0
            self.redraw()
            
    def on_wheel(self, e):
        self.canvas.yview_scroll(-int(e.delta / 120), "units")

    # ---------- 删页 / 空白 ----------
    def del_sel(self):
        if self.sel is None:
            return
        del self.pages[self.sel]
        self.sel = None
        self.save("已删除 1 页")
        self.redraw()

    def blank_sel(self):
        if self.sel is None:
            return
        self.pages[self.sel]["old"] = 0
        self.pages[self.sel]["rf"] = ""
        self.save("已改为空白页")
        self.redraw()

    # ---------- 保存：写回 order.csv（new_no 自动 1..N 连续） ----------
    def save(self, msg):
        import order_editor
        body = [[f"{i:03d}", str(p["old"]), p["rf"]]
                for i, p in enumerate(self.pages, 1)]
        self.app.order_body[:] = body
        order_editor.save_table(self.work_dir / "order.csv",
                                self.app.order_header, self.app.order_body)
        self.app.load_order()
        self.app.log_print(f"[拖拽排序] {msg}（现在共 {len(body)} 位）")

    def close(self):
        # 把全局滚轮还回主窗口
        try:
            c = getattr(self.app.sf, "canvas", None)
            if c is not None:
                c.bind_all("<MouseWheel>",
                           lambda e: c.yview_scroll(-int(e.delta / 120), "units"))
        except Exception:
            pass
        self.win.destroy()


def open_window(app):
    PageDragWindow(app)
