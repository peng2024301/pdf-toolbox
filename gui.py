# -*- coding: utf-8 -*-
"""GUI 外壳：选文件、模式、输出、运行、Help、换页、插字、指令队列（攒完逐条执行出成品）。

v0.7.4（在 v0.7.3 基础上：修复借图查重误报）：
v0.7.3（在 v0.7.2 换皮版基础上）：
  1. 补回【点图定位置】预览窗（同样主题化，跟随明暗主题）；
  2. 标题栏版本号更新。
（v0.7.2：ttkbootstrap 2.x 换皮，逻辑零改动；
  v0.7：busy 锁补全、队列增量执行、Help 指向《使用说明.txt》、
  线程安全、CSV 容错、跨平台打开、fitz 降级、颜色 hex 提取等，全保留。）
"""
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess, threading, json, contextlib, io, csv, os, re
from pathlib import Path
import sys

try:
    import ttkbootstrap as ttkb          # pip install ttkbootstrap（2.x）
except ImportError:
    raise SystemExit("缺少 ttkbootstrap，请先运行：pip install ttkbootstrap")

class ScrollFrame(ttkb.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        canvas = tk.Canvas(self, highlightthickness=0)
        self.canvas = canvas
        vsb = ttkb.Scrollbar(self, orient="vertical", command=canvas.yview)
        hsb = ttkb.Scrollbar(self, orient="horizontal", command=canvas.xview)
        self.inner = ttkb.Frame(canvas)
        self._inner_job = None
        self._canvas_job = None

        def _do_scrollregion():
            self._inner_job = None
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except tk.TclError:
                pass

        def _on_inner_configure(e):
            if self._inner_job:
                canvas.after_cancel(self._inner_job)
            self._inner_job = canvas.after(80, _do_scrollregion)

        self.inner.bind("<Configure>", _on_inner_configure)
        self._win = canvas.create_window((0, 0), window=self.inner, anchor="nw")

        def _do_resize():
            self._canvas_job = None
            try:
                canvas.itemconfigure(self._win, width=max(canvas.winfo_width(), 900))
            except tk.TclError:
                pass

        def _on_resize(e):
            if self._canvas_job:
                canvas.after_cancel(self._canvas_job)
            self._canvas_job = canvas.after(80, _do_resize)

        canvas.bind("<Configure>", _on_resize)
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        _wheel_state = {"acc": 0, "job": None}
        
        def _on_wheel(e):
            if isinstance(e.widget, (tk.Listbox, tk.Text)):
                return
            _wheel_state["acc"] += e.delta
            if _wheel_state["job"]:
                return
            ...
        def _on_wheel(e):
            _wheel_state["acc"] += e.delta
            if _wheel_state["job"]:
                return
            def _flush():
                _wheel_state["job"] = None
                d = _wheel_state["acc"]
                _wheel_state["acc"] = 0
                canvas.yview_scroll(-int(d / 120), "units")
            _wheel_state["job"] = canvas.after(30, _flush)

        canvas.bind_all("<MouseWheel>", _on_wheel)
        
    def _on_resize(self, e):
        e.widget.itemconfigure(self._win, width=max(e.width, 900))

try:
    import fitz          # PyMuPDF，只用于最后数页数；没装也能跑，只是不校验页数
except ImportError:
    fitz = None

PROJECT_ROOT = Path(__file__).resolve().parent

from core.common import ensure_output_dir, unique_path, Logger, FatalError
from core.splitter import split_pdf
from core.rebuilder import rebuild
import order_editor
from check_tables import check
import slot_scanner

TASK = "重建插字"
TEXT_HEADER = ["no", "text", "x", "y", "size", "color", "align", "status"]

SIZES = ["8", "9", "10", "10.5", "11", "12", "14", "16", "18", "22", "24", "36", "48"]
COLORS = ["黑 #000000", "红 #ff0000", "蓝 #0000ff", "绿 #008000",
          "灰 #808080", "白 #ffffff", "黄 #ffff00", "棕 #8b4513"]

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}")

# 主题：flatly 在 2.x 属旧名，可用但会有一行无害警告；
# 想彻底没警告可换 "bootstrap-light"（默认）或 "minty-light"；
# 想要深色界面换 "bootstrap-dark"。
THEME = "bootstrap-light"
FONT = ("Microsoft YaHei UI", 10)

VERSION = "v0.7.4"

class App:
    def __init__(self, modes):
        self.modes = modes
        self.win = ttkb.Window(title=f"PDF 工具箱 {VERSION}", themename=THEME)
        self.win.geometry("1180x1020")
        self.win.minsize(760, 640)
        self.style = self.win.style
        try:                                # 全局默认字体（中文更清爽）
            self.style.configure(".", font=FONT)
        except Exception:
            pass
        self.win.option_add("*Font", FONT)  # 经典 tk 控件的默认字体
        self.order_header = None
        self.order_body = None
        self.text_rows = []
        self.work_dir = None
        self.final_dir = None
        self.log_dir = None
        self.page_wh = (0, 0)
        self.cur_text_i = None
        self.queue = []              # 指令队列：[{"kind":..., "payload":...}]，与 lb_queue 一一对应
        self.busy = False            # 任务执行中标记，执行期间冻结一切写操作
        self.sf = ScrollFrame(self.win)
        self.sf.pack(fill="both", expand=True)
        self._build(self.sf.inner)
    # ---------- 主题化小组件 ----------

    def _listbox(self, parent, **kw):
        """Listbox 是经典 tk 控件（ttkbootstrap 2.x 不提供主题版），
        从当前主题取色手工上色，观感与其他控件统一。"""
        c = self.style.colors
        kw.setdefault("relief", "flat")
        kw.setdefault("borderwidth", 0)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("activestyle", "none")
        kw.setdefault("font", FONT)
        try:
            kw.setdefault("bg", c.inputbg)
            kw.setdefault("fg", c.inputfg)
            kw.setdefault("selectbackground", c.primary)
            kw.setdefault("selectforeground", c.selectfg)
            kw.setdefault("highlightbackground", c.border)
            kw.setdefault("highlightcolor", c.primary)
        except Exception:
            pass
        return tk.Listbox(parent, **kw)

    def _scrolled_text(self, parent, **kw):
        """主题化 Text + 竖滚动条组合（同上，经典 tk 控件手工上色），
        返回 (外框, 文本框)。"""
        c = self.style.colors
        frame = ttkb.Frame(parent)
        kw.setdefault("font", FONT)
        kw.setdefault("relief", "flat")
        kw.setdefault("borderwidth", 0)
        kw.setdefault("highlightthickness", 1)
        try:
            kw.setdefault("bg", c.inputbg)
            kw.setdefault("fg", c.inputfg)
            kw.setdefault("insertbackground", c.inputfg)   # 光标颜色
            kw.setdefault("selectbackground", c.primary)
            kw.setdefault("selectforeground", c.selectfg)
            kw.setdefault("highlightbackground", c.border)
            kw.setdefault("highlightcolor", c.primary)
        except Exception:
            pass
        txt = tk.Text(frame, **kw)
        sb = tk.Scrollbar(frame, command=txt.yview, orient="vertical")
        try:
            sb.config(troughcolor=c.bg, background=c.border,
                      activebackground=c.secondary)
        except tk.TclError:
            pass
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        return frame, txt
    
    def _build(self, parent=None):
        if parent is None:
            parent = self
        # ===== 顶部标题 =====
        head = ttkb.Frame(parent); head.pack(fill="x", padx=12, pady=(10, 0))
        ttkb.Label(head, text="PDF 工具箱",
                    font=("Microsoft YaHei UI", 15, "bold"),
                    bootstyle="primary").pack(side="left")
        ttkb.Label(head, text=f"{VERSION} · {TASK}",
                    bootstyle="secondary").pack(side="left", padx=8, pady=3)
        ttkb.Separator(parent).pack(fill="x", padx=12, pady=5)

        f1 = ttkb.Frame(parent); f1.pack(fill="x", padx=10, pady=5)
        ttkb.Label(f1, text="输入文件:").pack(side="left")
        self.e_in = ttkb.Entry(f1); self.e_in.pack(side="left", fill="x", expand=True, padx=5)
        ttkb.Button(f1, text="选择文件", bootstyle="secondary outline",
                    command=self.pick_file).pack(side="left")

        f2 = ttkb.Frame(parent); f2.pack(fill="x", padx=10, pady=5)
        ttkb.Label(f2, text="模式:").pack(side="left", padx=(0, 8))
        self.mode_var = tk.StringVar(value=next(iter(self.modes), ""))
        for name in self.modes:
            ttkb.Radiobutton(f2, text=name, variable=self.mode_var,
                                value=name,
                                bootstyle="primary toolbutton").pack(side="left", padx=2)

        f3 = ttkb.Frame(parent); f3.pack(fill="x", padx=10, pady=5)
        ttkb.Label(f3, text="输出目录:").pack(side="left")
        self.e_out = ttkb.Entry(f3); self.e_out.pack(side="left", fill="x", expand=True, padx=5)
        ttkb.Button(f3, text="选择目录", bootstyle="secondary outline",
                    command=self.pick_dir).pack(side="left")

        f4 = ttkb.Frame(parent); f4.pack(fill="x", padx=10, pady=(5, 2))
        self.b_run = ttkb.Button(f4, text="一键运行", bootstyle="primary", command=self.run)
        self.b_run.pack(side="left")
        ttkb.Button(f4, text="打开输出目录", bootstyle="secondary outline",
                    command=self.open_dir).pack(side="left", padx=5)
        ttkb.Button(f4, text="Help", bootstyle="info outline", command=self.help).pack(side="left")

        # ===== 换页区 =====
        f5 = ttkb.Labelframe(parent, bootstyle="info",
                                text=" 换页（口令可立即执行，也可加入队列攒着） ")
        f5.pack(fill="x", padx=10, pady=5)
        self.lb_order = self._listbox(f5, height=4)
        self.lb_order.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        f5r = ttkb.Frame(f5); f5r.pack(side="right", fill="y", padx=5, pady=5)
        ttkb.Label(f5r, text="口令:").pack(anchor="w")
        self.e_cmd = ttkb.Entry(f5r, width=14)
        self.e_cmd.pack(anchor="w")
        self.e_cmd.bind("<Return>", lambda e: self.exec_cmd())
        rowc = ttkb.Frame(f5r); rowc.pack(anchor="w", pady=2)
        ttkb.Button(rowc, text="立即执行", bootstyle="success",
                    command=self.exec_cmd).pack(side="left")
        ttkb.Button(f5r, text="加入队列", bootstyle="secondary outline",
                    command=self.queue_cmd).pack(anchor="w", pady=2)
        ttkb.Button(f5r, text="全部倒序→队列", bootstyle="secondary outline",
                    command=self.queue_reverse).pack(anchor="w", pady=2)
        ttkb.Button(f5r, text="批量加入队列", bootstyle="info outline",
                    command=self.queue_batch_cmd).pack(fill="both", expand=True)
        ttkb.Button(f5r, text="拆页出表", bootstyle="info outline",
                    command=self.do_split).pack(anchor="w", pady=2)
        ttkb.Button(f5r, text="拖拽排序", bootstyle="info outline",
                   command=self.open_page_drag).pack(anchor="w", pady=2)
        ttkb.Button(f5r, text="并入PDF", bootstyle="info outline",
                    command=self.do_merge).pack(anchor="w", pady=2)
        ttkb.Button(f5r, text="贴图", bootstyle="info outline",
                    command=self.do_sticker).pack(anchor="w", pady=2)
        ttkb.Button(f5r, text="扫图片格子", bootstyle="info outline",
                    command=self.do_scan_image).pack(anchor="w", pady=2)
        ttkb.Button(f5r, text="打开工作文件", bootstyle="secondary outline",
                    command=self.open_work).pack(anchor="w", pady=2)

        f5b = ttkb.Frame(f5); f5b.pack(side="bottom", fill="x", padx=5, pady=3)
        ttkb.Label(f5b, text="批量口令（每行一条，如 1换2）：").pack(anchor="w")
        row = ttkb.Frame(f5b); row.pack(fill="x")
        frame_cmd, self.t_cmd = self._scrolled_text(row, height=3)
        frame_cmd.pack(side="left", fill="both", expand=True)
        btns = ttkb.Frame(row); btns.pack(side="left", fill="y", padx=(5, 0))
        ttkb.Button(btns, text="批量\n立即执行", bootstyle="success",
                    command=self.exec_batch_cmd).pack(fill="both", expand=True)
        ttkb.Button(btns, text="批量\n加入队列", bootstyle="secondary outline",
                    command=self.queue_batch_cmd).pack(fill="both", expand=True)

        # ===== 插字区 =====
        f6 = ttkb.Labelframe(parent, bootstyle="primary",
                                text=" 插字（左边选页 → 右边填 → 切页自动保存；批量填字可入队列） ")
        f6.pack(fill="x", padx=10, pady=5)
        self.lb_text = self._listbox(f6, height=4, width=24)
        self.lb_text.pack(side="left", fill="y", padx=5, pady=5)
        self.lb_text.bind("<<ListboxSelect>>", self.on_pick_page)

        f6r = ttkb.Frame(f6); f6r.pack(side="left", fill="both", expand=True, padx=5, pady=2)
        r1 = ttkb.Frame(f6r); r1.pack(fill="x", pady=2)
        ttkb.Label(r1, text="文字:").pack(side="left")
        self.e_text = ttkb.Entry(r1); self.e_text.pack(side="left", fill="x", expand=True, padx=5)

        r2 = ttkb.Frame(f6r); r2.pack(fill="x", pady=2)
        ttkb.Label(r2, text="x:").pack(side="left")
        self.e_x = ttkb.Entry(r2, width=8); self.e_x.pack(side="left")
        ttkb.Label(r2, text="y:").pack(side="left", padx=(8, 0))
        self.e_y = ttkb.Entry(r2, width=8); self.e_y.pack(side="left")
        ttkb.Label(r2, text="字号:").pack(side="left", padx=(8, 0))
        self.cb_size = ttkb.Combobox(r2, width=6, values=SIZES)
        self.cb_size.pack(side="left")
        self.lbl_wh = ttkb.Label(r2, text="", bootstyle="secondary")
        self.lbl_wh.pack(side="left", padx=10)

        r3 = ttkb.Frame(f6r); r3.pack(fill="x", pady=2)
        ttkb.Label(r3, text="颜色:").pack(side="left")
        self.cb_color = ttkb.Combobox(r3, width=14, values=COLORS)
        self.cb_color.pack(side="left")
        self.cb_color.set(COLORS[0])
        ttkb.Label(r3, text="对齐:").pack(side="left", padx=(8, 0))
        self.align_var = tk.StringVar(value="left")
        ttkb.Combobox(r3, textvariable=self.align_var, width=8,
                        values=("left", "center", "right"),
                        state="readonly").pack(side="left")
        ttkb.Label(r3, text="状态:").pack(side="left", padx=(8, 0))
        self.status_var = tk.StringVar(value="已确认")
        ttkb.Combobox(r3, textvariable=self.status_var, width=8,
                        values=("已确认", "待审核"),
                        state="readonly").pack(side="left")

        r4 = ttkb.Frame(f6r); r4.pack(fill="x", pady=2)
        ttkb.Button(r4, text="保存此页", bootstyle="success",
                    command=self.save_page).pack(side="left")
        ttkb.Button(r4, text="清空此页", bootstyle="secondary outline",
                    command=self.clear_page).pack(side="left", padx=5)
        ttkb.Button(r4, text="看这页的图", bootstyle="info outline",
                    command=self.view_page_img).pack(side="left")
        ttkb.Button(r4, text="点图定位置", bootstyle="info outline",
                    command=self.preview_page).pack(side="left", padx=5)

        f6b = ttkb.Frame(f6); f6b.pack(side="bottom", fill="x", padx=5, pady=3)
        ttkb.Label(f6b, text="批量填字：（页号）文字，如 （1）封面标题（2）第一章").pack(anchor="w")
        row2 = ttkb.Frame(f6b); row2.pack(fill="x")
        frame_batch, self.t_batch = self._scrolled_text(row2, height=3)
        frame_batch.pack(side="left", fill="both", expand=True)
        btns2 = ttkb.Frame(row2); btns2.pack(side="left", fill="y", padx=(5, 0))
        ttkb.Button(btns2, text="批量\n立即填", bootstyle="success",
                    command=self.apply_batch_text_now).pack(fill="both", expand=True)
        ttkb.Button(btns2, text="批量\n加入队列", bootstyle="primary outline",
                    command=self.queue_batch_text).pack(fill="both", expand=True)

        # ===== 指令队列区 =====
        f7 = ttkb.Labelframe(parent, bootstyle="warning",
                                text=" 指令队列（攒着不动；执行时成功一条删一条，失败即停，重跑只跑剩余的） ")
        f7.pack(fill="both", padx=10, pady=5)
        self.lb_queue = self._listbox(f7, height=5)
        self.lb_queue.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        f7r = ttkb.Frame(f7); f7r.pack(side="right", fill="y", padx=5, pady=5)
        ttkb.Button(f7r, text="删除选中", bootstyle="secondary outline",
                    command=self.queue_del).pack(anchor="w", pady=2)
        ttkb.Button(f7r, text="清空队列", bootstyle="danger outline",
                    command=self.queue_clear).pack(anchor="w", pady=2)
        self.b_exec_queue = ttkb.Button(f7r, text="逐条执行\n并出成品",
                                        bootstyle="warning", command=self.run_queue)
        self.b_exec_queue.pack(anchor="w", pady=6)

        frame_log, self.log = self._scrolled_text(parent, height=7, wrap="word")
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)


     # ---------- 线程调度 / 基础 ----------

    def _ui(self, fn, *args, **kwargs):
        """把 fn 异步调度到主线程执行（不等待）。"""
        try:
            self.win.after(0, lambda: fn(*args, **kwargs))
        except tk.TclError:
            pass  # 窗口已关闭

    def _ui_sync(self, fn, *args, **kwargs):
        """把 fn 调度到主线程执行并等待结果（后台线程专用）。"""
        if threading.current_thread() is threading.main_thread():
            return fn(*args, **kwargs)
        done = threading.Event()
        box = {}

        def _run():
            try:
                box["ret"] = fn(*args, **kwargs)
            except BaseException as e:
                box["err"] = e
            finally:
                done.set()

        try:
            self.win.after(0, _run)
        except tk.TclError:
            raise RuntimeError("窗口已关闭")
        done.wait()
        if "err" in box:
            raise box["err"]
        return box.get("ret")

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.b_run.config(state=state)
        self.b_exec_queue.config(state=state)

    def _check_busy(self):
        if self.busy:
            self.log_print("[提示] 正在执行任务，请等它跑完再操作")
            return True
        return False

    def _open_path(self, target):
        """跨平台打开文件/目录。"""
        target = str(target)
        try:
            if sys.platform == "win32":
                os.startfile(target)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as e:
            self.log_print(f"[提示] 打不开：{target}（{e}）")

    def pick_file(self):
        if self._check_busy():
            return
        p = filedialog.askopenfilename(
            filetypes=[("PDF/图片", "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff")])
        if p:
            self.e_in.delete(0, "end"); self.e_in.insert(0, p)
            self.try_load_tables()

    def pick_dir(self):
        if self._check_busy():
            return
        p = filedialog.askdirectory()
        if p: self.e_out.delete(0, "end"); self.e_out.insert(0, p)

    def log_print(self, msg):
        """线程安全的日志输出：后台线程里调用会自动转回主线程。"""
        if threading.current_thread() is not threading.main_thread():
            self._ui(self.log_print, msg)
            return
        self.log.insert("end", str(msg) + "\n")
        self.log.see("end")

    def input_path(self):
        inp = self.e_in.get().strip()
        if not inp:
            messagebox.showwarning("提示", "请先选择输入文件")
            return None
        return Path(inp)

    def ensure_dirs(self, pdf):
        self.final_dir, self.work_dir, self.log_dir = ensure_output_dir(
            self.e_out.get().strip() or None, pdf, task_name=TASK)
        if not (self.work_dir / "order.csv").exists():
            self.log_print("还没拆过页，先自动拆一次……")
            split_pdf(pdf, self.work_dir, Logger(self.log_dir, name="GUI"))

    def try_load_tables(self):
        if self._check_busy():          # ★ 执行中禁止换文件，防 work_dir 串门
            return
        pdf = self.input_path()
        if not pdf or not pdf.exists():
            return
        # 先建目录、拿到三个目录路径（不拆页）
        try:
            self.final_dir, self.work_dir, self.log_dir = ensure_output_dir(
                self.e_out.get().strip() or None, pdf, task_name=TASK)
        except Exception as e:
            self.log_print(f"[致命] {e}")
            return

        # 首次选这个文件：后台拆页，不冻主界面
        if not (self.work_dir / "order.csv").exists():
            self._set_busy(True)
            self.log_print("首次选这个文件，正在后台拆页"
                           "（逐页渲染 PNG，可能要等几秒）……")

            def worker():
                try:
                    split_pdf(pdf, self.work_dir,
                              Logger(self.log_dir, name="GUI"))
                    self._ui_sync(self.load_order)
                    self._ui_sync(self.load_text)
                    self.log_print("✔ 拆页完成，可以开始操作了")
                except Exception as e:
                    self.log_print(f"[致命] {e}")
                finally:
                    self._ui(self._set_busy, False)

            threading.Thread(target=worker, daemon=True).start()
            return

        # 表已存在：直接读，瞬间完成
        self.load_order()
        self.load_text()
        
    # ---------- 队列管理 ----------

    def queue_add(self, kind, payload, label):
        if self._check_busy():
            return
        if kind in ("cmd", "text") and self.order_body is None:
            self.log_print("先拆页出表，再攒指令")
            return
        if kind == "text" and not self.text_rows:
            self.log_print("text.csv 还没就绪，先拆页出表")
            return
        self.queue.append({"kind": kind, "payload": payload})
        self.lb_queue.insert("end", label)
        self.log_print(f"已加入队列（共 {len(self.queue)} 条）：{label}")

    def queue_cmd(self):
        cmd = self.e_cmd.get().strip()
        if not cmd:
            return
        self.queue_add("cmd", cmd, f"[口令] {cmd}")
        self.e_cmd.delete(0, "end")

    def queue_batch_cmd(self):
        if self._check_busy():
            return
        lines = [l.strip() for l in self.t_cmd.get("1.0", "end").splitlines() if l.strip()]
        if not lines:
            self.log_print("批量口令框是空的")
            return
        for l in lines:
            self.queue.append({"kind": "cmd", "payload": l})
            self.lb_queue.insert("end", f"[口令] {l}")
        self.log_print(f"已加入队列 {len(lines)} 条口令（共 {len(self.queue)} 条）")
        self.t_cmd.delete("1.0", "end")

    def queue_reverse(self):
        self.queue_add("reverse", None, "[倒序] 整本倒序")

    def queue_batch_text(self):
        if self._check_busy():
            return
        raw = self.t_batch.get("1.0", "end").strip()
        if not raw:
            self.log_print("批量填字框是空的")
            return
        one = raw.replace("\n", " ")
        self.queue_add("text", one, f"[填字] {one[:40]}{'…' if len(one) > 40 else ''}")
        self.t_batch.delete("1.0", "end")

    def queue_del(self):
        if self._check_busy():
            return
        sel = self.lb_queue.curselection()
        if not sel:
            return
        i = sel[0]
        self.lb_queue.delete(i)
        del self.queue[i]

    def queue_clear(self):
        if self._check_busy():  
            return             
        self.queue.clear()
        self.lb_queue.delete(0, "end")
        self.log_print("队列已清空")

    def _queue_pop_head(self):
        """主线程调用：移除队首一条（成功的那条），列表同步。"""
        if self.queue:
            self.queue.pop(0)
            self.lb_queue.delete(0)

    def run_queue(self):
        """逐条执行队列：成功一条删一条，失败/体检不过即停 → 重跑只跑剩余的。
        全部执行完且体检通过才出成品。"""
        if self._check_busy():
            return
        pdf = self.input_path()
        if not pdf:
            return
        if not self.queue:
            messagebox.showwarning("提示", "队列是空的，先加几条指令")
            return
        if self.order_body is None:
            self.log_print("先拆页出表")
            return
        self._set_busy(True)
        total = len(self.queue)

        def worker():
            try:
                self.log_print(f"===== 开始逐条执行（共 {total} 条，成功一条删一条）=====")
                # 先把正在编辑、还没落盘的页收进去（批量指令在其后，同页以批量为准）
                self._ui_sync(self._collect_current)
                done, skip = 0, 0
                for i in range(1, total + 1):
                    item = self.queue[0]          # 永远取队首，成功即移除
                    kind, payload = item["kind"], item["payload"]
                    self.log_print(f"--- 第 {i}/{total} 条 ---")
                    if kind == "cmd":
                        buf = io.StringIO()
                        with contextlib.redirect_stdout(buf):
                            changed = order_editor.execute(self.order_body, payload, self.work_dir)
                        out = buf.getvalue().strip()
                        if out:
                            self.log_print("   " + out.replace("\n", "\n   "))
                        if not changed:
                            skip += 1
                            self.log_print("   [没生效] 此条被跳过并移出队列")
                            self._ui_sync(self._queue_pop_head)
                            order_editor.save_table(self.work_dir / "order.csv",
                                                    self.order_header, self.order_body)
                            continue
                        done += 1
                    elif kind == "text":
                        n = self._apply_any_payload(payload)
                        self._ui_sync(self.refresh_text_list)
                        if n:
                            self.log_print(f"   ✔ 批量填字生效 {n} 处")
                            done += 1
                        else:
                            skip += 1
                            self.log_print("   [没生效] 此条被跳过并移出队列")

                    elif kind == "reverse":
                        self._do_reverse_on_body()
                        self.log_print("   ✔ 整本倒序完成")
                        done += 1
                    # ★ 成功一条立即从队列移除——中途停下，剩下的天然是"没执行的"
                    self._ui_sync(self._queue_pop_head)
                    # 每条执行完立即存盘，中途断了也不丢
                    order_editor.save_table(self.work_dir / "order.csv",
                                            self.order_header, self.order_body)
                    self.write_text_csv()
                self._ui_sync(self.load_order)
                self._ui_sync(self.refresh_text_list)
                self.log_print(f"===== 执行完毕：{done} 条生效，{skip} 条没生效并移除 =====")
                
                # 体检
                errors, warns = [], []
                check(self.work_dir, errors, warns)
                for w in warns:
                    self.log_print(f"[提示] {w}")
                if errors:
                    for e in errors:
                        self.log_print(f"[致命] {e}")
                    self.log_print("表没通过体检，不出成品；修好后重新点执行即可（不会重复已执行的指令）")
                    def _pop():
                        messagebox.showerror(
                            "表格体检没通过",
                            "\n".join(errors[:5]) + ("\n……" if len(errors) > 5 else "")
                            + "\n\n修好两张表后重新点执行即可。")
                    try:
                        self._ui_sync(_pop)
                    except Exception:
                        pass
                    return
                self.log_print("✔ 表格体检通过，开始出成品……")
                final = unique_path(self.final_dir / f"{pdf.stem}_完成.pdf")
                rebuild(self.work_dir, final, Logger(self.log_dir, name="GUI"))
                if fitz is not None:
                    doc = fitz.open(final); n = doc.page_count; doc.close()
                    self.log_print(f"✔ 成品已生成（{n} 页）：{final}")
                else:
                    self.log_print(f"✔ 成品已生成：{final}（未装 PyMuPDF，跳过页数校验）")
                self.log_print("队列已全部执行完毕并出成品")
            except Exception as e:
                self.log_print(f"[致命] {e}")
                self.log_print("已停下；队列里剩的是没执行的条目，修好后重新点执行即可")
            finally:
                self._ui(self._set_busy, False)
        threading.Thread(target=worker, daemon=True).start()

    # ---------- 换页 ----------

    def load_order(self):
        opath = self.work_dir / "order.csv"
        if not opath.exists():
            return
        self.order_header, self.order_body = order_editor.load_table(opath)
        self.lb_order.delete(0, "end")
        for r in self.order_body:
            try:
                new_no, old_no, rf = int(r[0]), int(r[1]), r[2].strip()
            except (ValueError, IndexError):
                continue   # 手工改坏了的行，跳过显示，不让整个列表崩掉
            mark = f"  ←← 图用原第 {rf} 页" if rf else ""
            moved = "  [改过]" if (new_no != old_no or rf) else ""
            self.lb_order.insert("end", f"第 {new_no} 位 ← 原第 {old_no} 页{mark}{moved}")

    def exec_cmd(self):
        if self._check_busy():
            return
        cmd = self.e_cmd.get().strip()
        if not cmd:
            return
        if self.order_body is None:
            self.log_print("先拆页出表，再输口令")
            return
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            changed = order_editor.execute(self.order_body, cmd, self.work_dir)
        text = buf.getvalue().strip()
        if text:
            self.log_print(text)
        if changed:
            order_editor.save_table(self.work_dir / "order.csv",
                                    self.order_header, self.order_body)
            self.load_order()
        self.e_cmd.delete(0, "end")

    def exec_batch_cmd(self):
        if self._check_busy():
            return
        if self.order_body is None:
            self.log_print("先拆页出表")
            return
        lines = [l.strip() for l in self.t_cmd.get("1.0", "end").splitlines() if l.strip()]
        if not lines:
            self.log_print("批量口令框是空的")
            return
        ok, bad = 0, 0
        for line in lines:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                changed = order_editor.execute(self.order_body, line, self.work_dir)
            out = buf.getvalue().strip()
            self.log_print(f"【{line}】")
            if out:
                self.log_print("   " + out.replace("\n", "\n   "))
            ok += 1 if changed else 0
            bad += 0 if changed else 1
        if ok:
            order_editor.save_table(self.work_dir / "order.csv",
                                    self.order_header, self.order_body)
            self.load_order()
        self.log_print(f"✔ 批量执行完：{ok} 条成功，{bad} 条没生效")
        self.t_cmd.delete("1.0", "end")
                
    def _do_reverse_on_body(self):
        """在内存 order_body 上整本倒序（不弹窗不存盘，供队列和按钮共用）。"""
        n = len(self.order_body)
        old = [r[1] for r in self.order_body]
        for i, r in enumerate(self.order_body):
            r[1] = old[n - 1 - i]
            r[2] = ""

    # ---------- 插字 ----------

    @staticmethod
    def _norm_row(r):
        """把一行补齐/截断到 TEXT_HEADER 的列数，手工改表缺列也不崩。"""
        r = ["" if c is None else str(c) for c in (r or [])]
        if len(r) < len(TEXT_HEADER):
            r += [""] * (len(TEXT_HEADER) - len(r))
        return r[:len(TEXT_HEADER)]

    def load_text(self):
        tpath = self.work_dir / "text.csv"
        if not tpath.exists():
            self.log_print("text.csv 还没有，先拆页出表")
            return
        with open(tpath, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        self.text_rows = [self._norm_row(r) for r in rows[1:] if r and str(r[0]).strip()]
        self.cur_text_i = None
        self.refresh_text_list()
        try:
            m = json.load(open(self.work_dir / "manifest.json", encoding="utf-8"))
            p0 = next(p for p in m["pages"] if p.get("status") == "已确认")
            self.page_wh = (p0["width_pt"], p0["height_pt"])
            self.lbl_wh.config(text=f"页面约 {self.page_wh[0]:.0f}×{self.page_wh[1]:.0f} 点")
        except Exception:
            self.page_wh = (0, 0)

    def refresh_text_list(self):
        self.lb_text.delete(0, "end")
        for r in self.text_rows:
            preview = (r[1][:12] + "…") if len(r[1]) > 12 else r[1]
            mark = " ✔" if r[1].strip() else ""
            self.lb_text.insert("end", f"第 {r[0]} 页{mark} {preview}")

    def _collect_current(self):
        if self.cur_text_i is None or self.cur_text_i >= len(self.text_rows):
            return False
        r = self.text_rows[self.cur_text_i]
        r[1] = self.e_text.get()
        try:
            r[2] = str(float(self.e_x.get()))
            r[3] = str(float(self.e_y.get()))
        except ValueError:
            pass
        try:
            r[4] = str(float(self.cb_size.get() or 12))
        except ValueError:
            r[4] = r[4] or "12"
        c = self.cb_color.get().strip()
        if c:
            m = HEX_RE.search(c)
            r[5] = m.group(0) if m else (r[5] or "#000000")
        else:
            r[5] = r[5] or "#000000"
        r[6] = self.align_var.get()
        r[7] = self.status_var.get()
        return True

    def on_pick_page(self, _=None):
        sel = self.lb_text.curselection()
        if not sel:
            return
        if self._check_busy():          # ★ 执行中禁止切页，防并发写 text.csv
            return
        new_i = sel[0]
        if self.cur_text_i is not None and self.cur_text_i != new_i:
            if self._collect_current():
                self.write_text_csv()
                self.refresh_text_list()
        self.cur_text_i = new_i
        r = self.text_rows[new_i]
        self.e_text.delete(0, "end"); self.e_text.insert(0, r[1])
        self.e_x.delete(0, "end"); self.e_x.insert(0, r[2])
        self.e_y.delete(0, "end"); self.e_y.insert(0, r[3])
        self.cb_size.set(r[4] or "12")
        disp = next((c for c in COLORS if c.endswith(r[5])), r[5] or "#000000")
        self.cb_color.set(disp)
        if r[6]: self.align_var.set(r[6])
        if r[7]: self.status_var.set(r[7])

    def save_page(self):
        if self._check_busy():
            return
        if self.cur_text_i is None:
            messagebox.showwarning("提示", "先在左边选一页")
            return
        try:
            x = float(self.e_x.get()); y = float(self.e_y.get())
        except ValueError:
            messagebox.showwarning("提示", "x、y 必须是数字")
            return
        if self.page_wh[0] and not (0 <= x <= self.page_wh[0] and 0 <= y <= self.page_wh[1]):
            if not messagebox.askyesno("确认",
                    f"x/y 超出页面范围（0~{self.page_wh[0]:.0f}, 0~{self.page_wh[1]:.0f}），仍要保存吗？"):
                return
        self._collect_current()
        self.write_text_csv()
        self.refresh_text_list()
        self.log_print(f"✔ 第 {self.text_rows[self.cur_text_i][0]} 页的字已保存")

    def clear_page(self):
        if self._check_busy():
            return
        if self.cur_text_i is None:
            return
        r = self.text_rows[self.cur_text_i]
        r[1], r[2], r[3], r[4], r[7] = "", "", "", "", "待审核"
        self.write_text_csv()
        self.refresh_text_list()
        self.on_pick_page()

    def _apply_text_payload(self, raw):
        """把 （1）xxx（2）xxx 应用到 text_rows，返回填了几页。"""
        raw = raw.replace("\n", " ")
        parts = re.split(r"[（(](\d+)[)）]", raw)
        if parts[0].strip():
            self.log_print(f"[提示] 开头没页号，忽略：「{parts[0].strip()[:20]}」")
        pairs = list(zip(parts[1::2], parts[2::2]))
        if not pairs:
            self.log_print("[没看懂] 格式示例：（1）封面标题（2）第一章")
            return 0
        filled = []
        for no_s, txt in pairs:
            pno = int(no_s)
            pos = self._where_is(pno)
            if pos and pos != pno:
                self.log_print(f"[提示]（{pno}）指原第{pno}页，"
                               f"它现在排在第 {pos} 位——字跟内容页走，不跟位置")
            # 优先该页空白行，其次该页任意行，最后才新增（页号照抄补零格式）
            r = next((r for r in self.text_rows
                      if r[0].strip().lstrip("0") == str(pno) and not r[1].strip()), None)
            if r is None:
                r = next((r for r in self.text_rows
                          if r[0].strip().lstrip("0") == str(pno)), None)
            if r is None:
                width = len(self.text_rows[0][0]) \
                    if self.text_rows and self.text_rows[0][0].strip().isdigit() else 0
                r = self._norm_row(list(self.text_rows[-1])) if self.text_rows \
                    else self._norm_row([])
                r[0] = str(pno).zfill(width) if width else str(pno)
                r[1] = ""
                r[2] = ""      # ← 补：清掉从上一行抄来的坐标
                r[3] = ""      # ← 补
                r[4] = ""      # ← 补，顺手
                r[5] = ""
                self.text_rows.append(r)
            # 纯照片 PDF 扫不出格子，没坐标就自动给默认位置：
            # 页面左下角（x=50，底边上方 36 点），插完可用点图定位置微调
            if not r[2].strip() or not r[3].strip():
                pw, ph = self._page_size(pno)
                if not r[2].strip():
                    r[2] = "50"
                if not r[3].strip():
                    r[3] = str(round(ph - 36, 1))
                self.log_print(f"[提示]（{pno}）没定坐标，按默认位置"
                               f"（左下角 x=50, y={r[3]}）插入；"
                               f"可用【点图定位置】微调")
            r[1] = txt.strip()
            if not r[4]: r[4] = "12"
            if not r[5]: r[5] = "#000000"
            if not r[6]: r[6] = "left"
            r[7] = "已确认"
            if pno not in filled:
                filled.append(pno)
        self.write_text_csv()
        filled_set = {str(n) for n in filled}
        missing = [r[0] for r in self.text_rows
                   if r[0].strip().lstrip("0") in filled_set and not r[2]]
        self.log_print(f"✔ 填字完成：{len(filled)} 页（{','.join(map(str, filled))}）")
        if missing:
            self.log_print(f"[待办] 这些页还没填坐标：{','.join(missing)}")
        return len(filled)
            
    def _where_is(self, pno):
        """原第 pno 页现在排在第几位（找不到返回 None）。"""
        for i, r in enumerate(self.order_body):
            try:
                content = r[2].strip() if len(r) > 2 and r[2].strip() \
                          else str(int(r[1]))
            except (ValueError, IndexError):
                continue
            if content.lstrip("0") == str(pno):
                return i + 1
        return None
    
    def _page_size(self, pno):
        """查原第 pno 页的宽高（点）。查不到就退回全局或 A4。"""
        try:
            m = json.load(open(self.work_dir / "manifest.json", encoding="utf-8"))
            p = next(p for p in m["pages"] if str(p.get("page")) == str(pno))
            return p["width_pt"], p["height_pt"]
        except Exception:
            return self.page_wh if self.page_wh[0] else (595.0, 842.0)

    def _apply_slot_payload(self, raw):
        """把 （3）R2C2=某某公司（3）R3C2=张三 填进格子，返回填了几格。
        同页多格 = 同页多行；同一格重复填 = 覆盖，不涨行；页号格式与表内一致。"""
        spath = self.work_dir / "slots.json"
        slots_map = {}
        if spath.exists():
            try:
                data = json.load(open(spath, encoding="utf-8"))
                for pno, lst in data.items():
                    for s in lst:
                        slots_map[(int(pno), s["行"], s["列"])] = s
            except Exception:
                pass
        if not slots_map:
            self.log_print("[没空位] slots.json 里没有空位数据"
                           "（文件在但为空 = 这个 PDF 没扫出表格，格子口令用不了）")
            return 0
        raw = raw.replace("\n", " ")
        parts = re.split(r"[（(](\d+)[)）]", raw)
        pairs = list(zip(parts[1::2], parts[2::2]))
        ok, bad = 0, 0
        for no_s, body in pairs:
            m = re.match(r"\s*R(\d+)C(\d+)\s*=\s*(.*)", body)
            if not m:
                self.log_print(f"[没看懂] （{no_s}）后面不是 R行C列=文字：「{body[:20]}」")
                bad += 1
                continue
            pno, ri, ci = int(no_s), int(m.group(1)), int(m.group(2))
            txt = m.group(3).strip()
            pos = self._where_is(pno)
            if pos and pos != pno:
                self.log_print(f"[提示]（{pno}）指原第{pno}页，"
                               f"它现在排在第 {pos} 位——字跟内容页走，不跟位置")
            s = slots_map.get((pno, ri, ci))
            if s is None:
                self.log_print(f"[没这格] P{pno}R{ri}C{ci} 不在空位表里，跳过")
                bad += 1
                continue
            x0, y0, x1, y1 = s["矩形"]
            size = s["字号"]
            y = round(y1 - size * 0.30, 1)
            # ① 先找"该页同一格"的行（页号+坐标都相同）→ 直接覆盖，防重复涨行
            def _near(v, target, tol=0.5):
                try:
                    return abs(float(v) - target) < tol
                except (TypeError, ValueError):
                    return False

            r = next((r for r in self.text_rows
                      if r[0].strip().lstrip("0") == str(pno)
                      and _near(r[2], x0) and _near(r[3], y)), None)
            if r is None:
                # ② 该格没填过：优先复用该页的空白行
                r = next((r for r in self.text_rows
                          if r[0].strip().lstrip("0") == str(pno)
                          and not r[1].strip()), None)
                # ③ 真没有才新增，页号照抄表内补零格式（001 而不是 1）
                if r is None:
                    width = len(self.text_rows[0][0]) \
                        if self.text_rows and self.text_rows[0][0].strip().isdigit() else 0
                    r = self._norm_row(list(self.text_rows[-1])) if self.text_rows \
                        else self._norm_row([])
                    r[0] = str(pno).zfill(width) if width else str(pno)
                    r[1] = ""
                    r[2] = ""
                    r[3] = ""
                    r[4] = ""
                    r[5] = ""
                    self.text_rows.append(r)           
            r[1], r[2], r[3], r[4] = txt, str(x0), str(y), str(size)
            r[5] = r[5] or "#000000"
            r[6] = "left"
            r[7] = "已确认"
            ok += 1
        self.write_text_csv()
        self.log_print(f"✔ 格子填字完成：{ok} 格生效，{bad} 格没生效")
        return ok

    def _apply_any_payload(self, raw):
        """自动识别：带 R行C列= 的走格子口令，否则走原来的整页填字。"""
        if re.search(r"[（(]\d+[)）]\s*R\d+C\d+\s*=", raw):
            return self._apply_slot_payload(raw)
        return self._apply_text_payload(raw)


    def apply_batch_text_now(self):
        if self._check_busy():
            return
        if not self.text_rows:
            self.log_print("先拆页出表")
            return
        raw = self.t_batch.get("1.0", "end").strip()
        if not raw:
            self.log_print("批量填字框是空的")
            return
        # 先把正在编辑的页收进去，批量内容在其后，同页以批量为准
        self._collect_current()
        self._apply_any_payload(raw)
        self.refresh_text_list()
        self.t_batch.delete("1.0", "end")

    def write_text_csv(self):
        if not self.work_dir:
            return
        with open(self.work_dir / "text.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(TEXT_HEADER)
            w.writerows(self.text_rows)

    def view_page_img(self):
        if self.cur_text_i is None or not self.work_dir:
            return
        img = self.work_dir / f"{self.text_rows[self.cur_text_i][0]}.png"
        if img.exists():
            self._open_path(img)
        else:
            self.log_print("这页的图缺失，看日志")

    def preview_page(self):
        """弹出这页的预览图：点哪里，x/y 就填哪；红点红字模拟插入效果。"""
        if self._check_busy():
            return
        if self.cur_text_i is None or not self.work_dir:
            messagebox.showwarning("提示", "先在左边选一页")
            return
        self._collect_current()          # 先收当前输入，预览才是最新的
        r = self.text_rows[self.cur_text_i]
        img_path = self.work_dir / f"{r[0]}.png"
        if not img_path.exists():
            self.log_print("这页的图缺失，先拆页出表")
            return
        try:
            from PIL import Image, ImageTk
        except ImportError:
            self.log_print("没装 Pillow，无法预览；pip install pillow")
            return

        c = self.style.colors
        img = Image.open(img_path)
        px_w, px_h = img.size
        pw, ph = self.page_wh
        if not pw:                       # manifest 没读到就粗略按 1px=1pt
            pw, ph = float(px_w), float(px_h)
        sx, sy = pw / px_w, ph / px_h    # 像素→PDF点 的换算比例

        max_w, max_h = 900, 960
        k = min(max_w / px_w, max_h / px_h, 1.0)
        dw, dh = int(px_w * k), int(px_h * k)
        disp = img.resize((dw, dh))

        win = ttkb.Toplevel(self.win)
        win.title(f"第 {r[0]} 页 — 点哪里，字落哪里")
        cv = tk.Canvas(win, width=dw, height=dh,
                       bg=c.inputbg, highlightthickness=1,
                       highlightbackground=c.border)
        cv.pack(padx=10, pady=10)
        cv.image = ImageTk.PhotoImage(disp)   # 持引用，防图片被回收
        cv.create_image(0, 0, anchor="nw", image=cv.image)
        cv.create_text(dw // 2, 16, text="单击图片任意位置 = 字插入那里；改完关窗，点【保存此页】",
                       fill=c.primary, font=FONT)
        # ── 画表格空位框（蓝虚线 + 编号角标）──
        def _load_slots(pno):
            path = self.work_dir / "slots.json"
            if not path.exists():
                return []
            try:
                data = json.load(open(path, encoding="utf-8"))
                return data.get(str(pno), [])
            except Exception:
                return []

        slots = _load_slots(int(r[0]) if str(r[0]).strip().isdigit() else -1)
        for s in slots:
            x0, y0, x1, y1 = (v / sx * k for v in s["矩形"])
            cv.create_rectangle(x0, y0, x1, y1,
                                outline="#1976d2", dash=(4, 3), width=1)
            cv.create_text(x0 + 2, y0 + 1, anchor="nw", text=s["编码"],
                           fill="#1976d2", font=("Microsoft YaHei UI", 7))
        if slots:
            cv.create_text(dw // 2, 34,
                           text=f"本页 {len(slots)} 个空位（蓝虚线框）；点框内=自动吸附",
                           fill="#1976d2", font=FONT)

        marker = []
        def redraw():
            nonlocal marker
            for it in marker:
                cv.delete(it)
            marker = []
            try:
                fx, fy = float(r[2]), float(r[3])
            except ValueError:
                return
            mx, my = fx / sx * k, fy / sy * k
            marker.append(cv.create_oval(mx - 4, my - 4, mx + 4, my + 4,
                                         outline="red", width=2))
            txt = r[1] or "（这里）"
            try:
                fsize = max(int(float(r[4] or 12) * k), 6)
            except ValueError:
                fsize = 10
            marker.append(cv.create_text(mx + 6, my, anchor="w", text=txt[:20],
                                         fill=r[5] or "#000000",
                                         font=("SimSun", fsize)))

        def on_click(e):
            x_pt = e.x / k * sx
            y_pt = e.y / k * sy
            # 先看是不是点在了某个空位框里 → 吸附
            for s in slots:
                bx0, by0, bx1, by1 = s["矩形"]
                if bx0 - 2 <= x_pt <= bx1 + 2 and by0 - 2 <= y_pt <= by1 + 2:
                    r[2] = str(round(bx0, 1))                 # 贴左边框内侧
                    r[3] = str(round(by1 - s["字号"] * 0.30, 1))  # 基线约在底边上方 0.3 字高
                    self.cb_size.set(str(s["字号"]))
                    break
            else:
                # 没点中空位，走原来的手点逻辑
                r[2] = str(round(x_pt, 1))
                r[3] = str(round(y_pt, 1))
            self.e_x.delete(0, "end"); self.e_x.insert(0, r[2])
            self.e_y.delete(0, "end"); self.e_y.insert(0, r[3])
            redraw()
        # ↓↓ 补这两行（注意缩进：8 个空格，和 def on_click 平级）↓↓
        redraw()
        cv.bind("<Button-1>", on_click)

    # ---------- 拆页 / 其他 ----------

    def do_split(self):
        if self._check_busy():
            return
        pdf = self.input_path()
        if not pdf:
            return
        self._set_busy(True)
           
        def worker():
            try:
                self.ensure_dirs(pdf)
                slot_scanner.scan_pdf(pdf, self.work_dir / "slots.json", 覆盖=True)
                self.log_print("✔ 表格空位已扫描 → slots.json")
                self._ui_sync(self.load_order)
                self._ui_sync(self.load_text)
                self.log_print("✔ 拆页完成，两张表已就绪（✔ 拆页完成，空位已重扫 → slots.json）")
            except Exception as e:
                self.log_print(f"[致命] {e}")
            finally:
                self._ui(self._set_busy, False)
        threading.Thread(target=worker, daemon=True).start()     
        
    def do_scan_image(self):
        """照片件专用：图片找线扫表格空位，只填没货的页，不动文字版结果。"""
        if self._check_busy():
            return
        pdf = self.input_path()
        if not pdf:
            return
        self._set_busy(True)

        def worker():
            try:
                self.log_print("===== 图片找线开始（只扫没空位的页）=====")
                新增 = slot_scanner.scan_pdf_image(
                    pdf, self.work_dir / "slots.json", 报告=self.log_print)
                if 新增:
                    self.log_print(f"✔ 完成，{len(新增)} 页新增空位"
                                   f"（{sum(新增.values())} 格）——格子口令现在可用了")
                else:
                    self.log_print("没扫出新的空位：表格可能没有框线，"
                                   "用【点图定位置】手点更靠谱")
            except Exception as e:
                self.log_print(f"[致命] {e}")
                self.log_print("提示：没装 numpy 的话会很慢，pip install numpy")
            finally:
                self._ui(self._set_busy, False)
        threading.Thread(target=worker, daemon=True).start()
        
    def open_page_drag(self):
        if self._check_busy():
            return
        if self.order_body is None:
            self.log_print("先拆页出表，再拖拽排序")
            return
        import page_drag
        page_drag.open_window(self)        
        
    def do_merge(self):
        if self._check_busy():
            return
        if self.order_body is None:
            self.log_print("先拆页出表，再并入其他 PDF")
            return
        from tkinter import filedialog
        pdf = filedialog.askopenfilename(
            title="选择要并入的 PDF",
            filetypes=[("PDF 文件", "*.pdf")])
        if not pdf:
            return
        self._set_busy(True)

        def worker(pdf):
            try:
                import merger
                added = merger.merge_pdf(pdf, self.work_dir,
                                         self.order_header, self.order_body)
                self._ui_sync(self.load_order)
                tail = "、".join(str(x) for x in added[:5])
                more = "…" if len(added) > 5 else ""
                self.log_print(f"✔ 已并入 {len(added)} 页（新页号：{tail}{more}），"
                               f"排在队尾——用拖拽排序挪到想要的位置")
            except Exception as e:
                self.log_print(f"[致命] {e}")
            finally:
                self._ui(self._set_busy, False)
        threading.Thread(target=worker, args=(pdf,), daemon=True).start()

    def do_sticker(self):
        if self._check_busy():
            return
        if self.order_body is None:
            self.log_print("先拆页出表，再贴图")
            return
        from tkinter import filedialog, simpledialog
        img = filedialog.askopenfilename(
            title="选择要贴的图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
        if not img:
            return
        s = simpledialog.askstring("贴图", "贴到原第几页？（敲页号，如 3）",
                                   parent=self.win)
        if not s or not s.strip().isdigit():
            return
        pno = int(s)
        if not (self.work_dir / f"{pno:03d}.png").exists():
            self.log_print(f"[贴图] 没有原第{pno}页（页号范围看表格面板）")
            return
        import sticker
        sticker.add_sticker(self.work_dir, pno, img)
        self.log_print(f"✔ 图片已贴到原第{pno}页（默认居中、30%宽）"
                       f"——弹出调整窗，拖动挪位置、滚轮缩放")
        sticker.open_editor(self, pno)
        
    def open_work(self):
        if self.work_dir and self.work_dir.exists():
            self._open_path(self.work_dir)
        else:
            self.log_print("还没有工作文件，先拆页出表")

    def run(self):
        if self._check_busy():
            return
        inp = self.e_in.get().strip()
        if not inp:
            messagebox.showwarning("提示", "请先选择输入文件"); return
        params = {"input_file": inp, "output_dir": self.e_out.get().strip() or None}
        mode = self.modes[self.mode_var.get()]
        self._set_busy(True)

        def worker():
            try:
                mode.run(params, log_print=self.log_print)
            except Exception as e:
                self.log_print(f"[致命] {e}")
            finally:
                self._ui(self._set_busy, False)
        threading.Thread(target=worker, daemon=True).start()

    def open_dir(self):
        out = self.e_out.get().strip()
        if out:
            self._open_path(out)
            return
        inp = self.e_in.get().strip()
        if inp:
            self._open_path(Path(inp).parent)
        else:
            self.log_print("还没选输出目录或输入文件")

    def help(self):
        # 优先用户说明书，缺了降级到开发约定；末尾附 AI 口令模板
        doc = PROJECT_ROOT / "docs" / "使用说明.txt"
        if not doc.exists():
            doc = PROJECT_ROOT / "docs" / "约定总纲.txt"
        try:
            txt = doc.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            txt = doc.read_text(encoding="gbk")
        except FileNotFoundError:
            txt = "帮助文档缺失（docs/使用说明.txt）"

        # 追加 AI 口令模板（叫法可能不同，按候选挨个找）
        模板 = None
        for name in ("AI口令模板.txt", "AI模板.txt", "口令模板.txt"):
            for 目录 in (PROJECT_ROOT / "docs", PROJECT_ROOT):
                p = 目录 / name
                if p.exists():
                    模板 = p
                    break
            if 模板:
                break
        if 模板:
            try:
                t_txt = 模板.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                t_txt = 模板.read_text(encoding="gbk")
            txt += "\n\n" + "━" * 28 + "\n  AI 口令模板（复制给 AI 用，也可单独取用）\n" \
                   + "━" * 28 + "\n" + t_txt

        win = ttkb.Toplevel(self.win)
        win.title("Help")
        win.geometry("680x540")
        frame, t = self._scrolled_text(win, wrap="word")
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        t.insert("end", txt)
        t.configure(state="disabled")   # 只读

    def run_gui(self):
        self.win.mainloop()

def run_gui(modes):
    App(modes).run_gui()
