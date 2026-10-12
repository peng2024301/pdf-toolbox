# -*- coding: utf-8 -*-
"""slot_scanner.py —— 表格空位扫描器 v0.3

两套扫描，各走各的入口：
  scan_pdf       文字/矢量找表（拆页默认用，快）
  scan_pdf_image 图片找线（纯照片扫描件专用，独立按钮触发，不自动跑）
结果统一存 slots.json，编码格式一致（P页R行C列）。
"""
import json
from pathlib import Path

try:
    import pymupdf as fitz      # 新版
except ImportError:
    import fitz                 # 老版兜底

# ── 字号匹配（文字页专用）──────────────────────────────────
def _页内字号分布(page):
    """统计一页里每个字号出现了多少字，返回 [(字号, 字数), ...] 从多到少。"""
    计数 = {}
    d = page.get_text("dict")
    for block in d["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                txt = span["text"].strip()
                if txt:
                    n = 计数.get(round(span["size"], 1), 0) + len(txt)
                    计数[round(span["size"], 1)] = n
    return sorted(计数.items(), key=lambda x: -x[1])

def _找同行字号(page, cell_rect):
    """找空位同一水平线上、位于它左侧最近的文字的字号。
    找不到返回 None，让调用方用本页最常用字号兜底。"""
    d = page.get_text("dict")
    候选 = []   # (左边距离, 字号)
    for block in d["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                txt = span["text"].strip()
                if not txt:
                    continue
                r = fitz.Rect(span["bbox"])
                if r.y0 < cell_rect.y1 and r.y1 > cell_rect.y0 \
                        and r.x1 <= cell_rect.x0 + 2:
                    候选.append((cell_rect.x0 - r.x1, span["size"]))
    if 候选:
        候选.sort()
        return round(候选[0][1], 1)
    return None

# ── 第一段：文字/矢量找表 ─────────────────────────────────
def scan_page(page, 页号):
    """扫一页（文字/矢量方式），返回空位清单。没有表格返回空列表。"""
    try:
        tables = page.find_tables().tables
    except Exception:
        return []
    常用字号 = _页内字号分布(page)
    兜底字号 = 常用字号[0][0] if 常用字号 else 12.0
    slots = []
    for t in tables:
        data = t.extract()
        for ri, row in enumerate(t.rows, 1):
            for ci, cell_rect in enumerate(row.cells, 1):
                if cell_rect is None:
                    continue
                if ri > len(data) or ci > len(data[ri - 1]):
                    continue
                内容 = (data[ri - 1][ci - 1] or "").strip()
                if 内容:
                    continue
                rect = fitz.Rect(cell_rect)
                字号 = _找同行字号(page, rect) or 兜底字号
                内缩 = fitz.Rect(rect.x0 + 2, rect.y0 + 2,
                                 rect.x1 - 2, rect.y1 - 2)
                slots.append({
                    "编码": f"P{页号}R{ri}C{ci}",
                    "页": 页号, "行": ri, "列": ci,
                    "矩形": [round(v, 1) for v in 内缩],
                    "字号": 字号,
                })
    return slots

# ── 第二段：图片找线（纯照片件专用，独立入口）───────────────
_暗阈值 = 128          # 灰度低于此算"墨"
_最小格高px = 10       # 比这还矮的格子不认（防噪点）
_最小格宽px = 24

def _渲染灰度(page, dpi):
    """渲染成灰度图。返回 (宽, 高, 像素bytes, 缩放系数)。"""
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                          colorspace=fitz.csGRAY)
    return pix.width, pix.height, pix.samples, zoom

def _runs(mask):
    """一维 bool 数组里的连续段，返回 [(起点, 终点), ...]。numpy 向量化。"""
    import numpy as np
    padded = np.concatenate(([0], mask.astype(np.int8), [0]))
    d = np.diff(padded)
    return list(zip(np.flatnonzero(d == 1).tolist(),
                    np.flatnonzero(d == -1).tolist()))

def _聚合成线(段, 容差=3):
    """段=[(主坐标, 起点, 终点)]。主坐标接近的段并成一条线，
    返回 [(主坐标均值, 最小起点, 最大终点), ...]。"""
    if not 段:
        return []
    段 = sorted(段)
    线, cur = [], [段[0]]
    for s in 段[1:]:
        if s[0] - cur[-1][0] <= 容差:
            cur.append(s)
        else:
            线.append((round(sum(c[0] for c in cur) / len(cur), 1),
                       min(c[1] for c in cur), max(c[2] for c in cur)))
            cur = [s]
    线.append((round(sum(c[0] for c in cur) / len(cur), 1),
               min(c[1] for c in cur), max(c[2] for c in cur)))
    return 线

def scan_page_image(page, 页号, dpi=110):
    """图片方式扫一页：找横竖框线 → 交叉成格 → 内部无墨的算空位。
    优先 numpy（快）；没装则走慢速兜底（先 pip install numpy 更好）。"""
    try:
        import numpy as np
    except ImportError:
        return _scan_page_image_slow(page, 页号, dpi=80)

    w, h, samples, zoom = _渲染灰度(page, dpi)
    dark = (np.frombuffer(samples, dtype=np.uint8)
            .reshape(h, w) < _暗阈值)
    最小横 = max(30, int(w * 0.10))   # 横线至少占页宽 10%
    最小纵 = max(30, int(h * 0.05))   # 竖线至少占页高 5%

    hseg, vseg = [], []
    for y in range(h):
        row = dark[y]
        if row.sum() < 最小横:
            continue
        for x0, x1 in _runs(row):
            if x1 - x0 >= 最小横:
                hseg.append((y, x0, x1))
    for x in range(w):
        col = dark[:, x]
        if col.sum() < 最小纵:
            continue
        for y0, y1 in _runs(col):
            if y1 - y0 >= 最小纵:
                vseg.append((x, y0, y1))

    h线 = _聚合成线(hseg)
    v线 = _聚合成线(vseg)
    if len(h线) < 2 or len(v线) < 2:
        return []

    # 用最长横线定表格左右界，只留横跨/纵贯表格区 60% 以上的线
    最长 = max(h线, key=lambda L: L[2] - L[1])
    X0, X1 = 最长[1], 最长[2]
    Y0, Y1 = min(L[0] for L in h线), max(L[0] for L in h线)
    h线 = [L for L in h线 if min(L[2], X1) - max(L[1], X0) >= 0.6 * (X1 - X0)]
    v线 = [L for L in v线 if min(L[2], Y1) - max(L[1], Y0) >= 0.6 * (Y1 - Y0)]
    if len(h线) < 2 or len(v线) < 2:
        return []

    ys = sorted(set(L[0] for L in h线))
    xs = sorted(set(L[0] for L in v线))

    slots = []
    for ri in range(len(ys) - 1):
        for ci in range(len(xs) - 1):
            py0, py1, px0, px1 = ys[ri], ys[ri + 1], xs[ci], xs[ci + 1]
            if py1 - py0 < _最小格高px or px1 - px0 < _最小格宽px:
                continue
            inner = dark[int(py0) + 2:int(py1) - 2, int(px0) + 2:int(px1) - 2]
            if inner.size and inner.mean() >= 0.02:
                continue                    # 内部有墨 = 有字，不是空位
            字号 = max(9.0, min(14.0, round((py1 - py0) / zoom * 0.55, 1)))
            slots.append({
                "编码": f"P{页号}R{ri + 1}C{ci + 1}",
                "页": 页号, "行": ri + 1, "列": ci + 1,
                "矩形": [round(px0 / zoom, 1), round(py0 / zoom, 1),
                         round(px1 / zoom, 1), round(py1 / zoom, 1)],
                "字号": 字号,
            })
    return slots

def _scan_page_image_slow(page, 页号, dpi=80):
    """没装 numpy 的兜底：纯 Python 逐像素，慢（约 10 秒/页），结果一致。"""
    w, h, data, zoom = _渲染灰度(page, dpi)
    最小横 = max(30, int(w * 0.10))
    最小纵 = max(30, int(h * 0.05))

    def 横段():
        out = []
        for y in range(h):
            base = y * w; x = 0
            while x < w:
                if data[base + x] < _暗阈值:
                    x0 = x
                    while x < w and data[base + x] < _暗阈值: x += 1
                    if x - x0 >= 最小横: out.append((y, x0, x))
                else:
                    x += 1
        return out

    def 竖段():
        out = []
        for x in range(w):
            y = 0
            while y < h:
                if data[y * w + x] < _暗阈值:
                    y0 = y
                    while y < h and data[y * w + x] < _暗阈值: y += 1
                    if y - y0 >= 最小纵: out.append((x, y0, y))
                else:
                    y += 1
        return out

    def 内部墨占比(y0, y1, x0, x1):
        总 = 暗 = 0
        for yy in range(int(y0) + 2, int(y1) - 2):
            base = yy * w
            for xx in range(int(x0) + 2, int(x1) - 2):
                总 += 1
                if data[base + xx] < _暗阈值: 暗 += 1
        return (暗 / 总) if 总 else 1.0

    h线 = _聚合成线(横段()); v线 = _聚合成线(竖段())
    if len(h线) < 2 or len(v线) < 2:
        return []
    最长 = max(h线, key=lambda L: L[2] - L[1])
    X0, X1 = 最长[1], 最长[2]
    Y0, Y1 = min(L[0] for L in h线), max(L[0] for L in h线)
    h线 = [L for L in h线 if min(L[2], X1) - max(L[1], X0) >= 0.6 * (X1 - X0)]
    v线 = [L for L in v线 if min(L[2], Y1) - max(L[1], Y0) >= 0.6 * (Y1 - Y0)]
    if len(h线) < 2 or len(v线) < 2:
        return []
    ys = sorted(set(L[0] for L in h线)); xs = sorted(set(L[0] for L in v线))
    slots = []
    for ri in range(len(ys) - 1):
        for ci in range(len(xs) - 1):
            py0, py1, px0, px1 = ys[ri], ys[ri + 1], xs[ci], xs[ci + 1]
            if py1 - py0 < _最小格高px or px1 - px0 < _最小格宽px:
                continue
            if 内部墨占比(py0, py1, px0, px1) >= 0.02:
                continue
            字号 = max(9.0, min(14.0, round((py1 - py0) / zoom * 0.55, 1)))
            slots.append({
                "编码": f"P{页号}R{ri + 1}C{ci + 1}",
                "页": 页号, "行": ri + 1, "列": ci + 1,
                "矩形": [round(px0 / zoom, 1), round(py0 / zoom, 1),
                         round(px1 / zoom, 1), round(py1 / zoom, 1)],
                "字号": 字号,
            })
    return slots

def scan_pdf_image(pdf路径, json路径=None, 报告=print):
    """【独立入口】图片找线扫整个 PDF，结果并进 slots.json。
    界限：某页已有空位（文字版扫出来的）→ 跳过不覆盖；
    只往没货的页里填图片扫出的空位。返回 {页号: 空位数}。"""
    pdf路径 = Path(pdf路径)
    json路径 = Path(json路径) if json路径 else pdf路径.with_suffix(".slots.json")
    旧 = {}
    if json路径.exists():
        try:
            旧 = json.load(open(json路径, encoding="utf-8"))
        except Exception:
            旧 = {}
    doc = fitz.open(pdf路径)
    新增 = {}
    for pno in range(1, doc.page_count + 1):
        if 旧.get(str(pno)):
            报告(f"页 {pno}：已有空位（文字版扫的），跳过不覆盖")
            continue
        slots = scan_page_image(doc[pno - 1], pno)
        if slots:
            旧[str(pno)] = slots
            新增[pno] = len(slots)
            报告(f"页 {pno}：图片找线扫出 {len(slots)} 个空位")
        else:
            报告(f"页 {pno}：没找到带框线的表格（无框线排版扫不出，用点图定位置）")
    doc.close()
    with open(json路径, "w", encoding="utf-8") as f:
        json.dump(旧, f, ensure_ascii=False, indent=1)
    return 新增

# ── 文字/矢量扫描整个 PDF + 存 json ───────────────────────
def scan_pdf(pdf路径, json路径=None, 覆盖=False):
    """扫一个 PDF 的所有页，返回 {页号: [空位...]}，并存 json。
    覆盖=False（默认）：已有 slots.json 时不覆盖。"""
    pdf路径 = Path(pdf路径)
    if json路径 is None:
        json路径 = pdf路径.with_suffix(".slots.json")
    json路径 = Path(json路径)
    if json路径.exists() and not 覆盖:
        print(f"[slot_scanner] {json路径.name} 已存在，不覆盖（要重扫就传 覆盖=True）")
        with open(json路径, "r", encoding="utf-8") as f:
            return json.load(f)

    doc = fitz.open(pdf路径)
    全部 = {}
    for pno in range(1, doc.page_count + 1):
        page = doc[pno - 1]
        slots = scan_page(page, pno)
        if slots:
            全部[str(pno)] = slots
    doc.close()
    with open(json路径, "w", encoding="utf-8") as f:
        json.dump(全部, f, ensure_ascii=False, indent=1)
    return 全部

# ── 命令行自测 ────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法：python slot_scanner.py 某文件.pdf [--image]")
        sys.exit(1)
    if "--image" in sys.argv:
        新增 = scan_pdf_image(sys.argv[1], 报告=print)
        print(f"\n图片找线完成，新增空位的页：{新增}")
    else:
        结果 = scan_pdf(sys.argv[1], 覆盖=True)
        总数 = 0
        for 页, slots in 结果.items():
            print(f"\n第 {页} 页：{len(slots)} 个空位")
            for s in slots:
                print(f"  {s['编码']} 字号={s['字号']} 位置={s['矩形']}")
            总数 += 1
        print(f"\n合计 {总数} 个空位")
