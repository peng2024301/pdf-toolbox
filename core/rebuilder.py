# -*- coding: utf-8 -*-
"""按 order.csv 重排/替换页面，并按 text.csv 插字、sticker.csv 贴图，一步重建 PDF。"""
import fitz
import csv
import json
from pathlib import Path
from .common import FatalError
from .order import load_order

COLORS = {"black": (0, 0, 0), "red": (1, 0, 0), "blue": (0, 0, 1), 
          "green": (0, 0.5, 0), "gray": (0.5, 0.5, 0.5)}

def _parse_color(s):
    """认名字也认 hex（#ff0000 / #f00），认不出回退黑色。"""
    s = (s or "").strip().lower()
    if s in COLORS:
        return COLORS[s]
    if s.startswith("#"):
        h = s.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0, 0, 0)

def _read_dicts(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def _insert_text(page, row, logger):
    text = (row.get("text") or "").strip()
    if not text:
        return
    def num(key, default):
        v = (row.get(key) or "").strip()
        return float(v) if v else default
    size = num("size", 14)
    x, y = num("x", 50), num("y", 50)
    color = _parse_color(row.get("color"))    
    align = (row.get("align") or "").strip()
    if align in ("中", "居中", "center", "右", "右对齐", "right"):
        try:
            w = fitz.get_text_length(text, fontname="china-s", fontsize=size)
        except Exception:
            w = len(text) * size
        if align.startswith(("中", "居中", "c")):
            x = page.rect.width / 2 - w / 2
        else:
            x = page.rect.width - x - w
    page.insert_text((x, y), text, fontname="china-s", fontsize=size, color=color)

def _load_stickers(work_dir):
    """读 sticker.csv，返回 [(页号字符串, 行), ...]；没有文件返回空表。"""
    p = work_dir / "sticker.csv"
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        return [r for r in rows[1:] if r and r[0].strip()]
    except Exception:
        return []

def _paste_stickers(page, stk_rows, page_no, logger):
    """把属于页号 page_no 的贴图盖到该页上（文字之后调用）。"""
    mine = [r for r in stk_rows if r[0].lstrip("0") == str(page_no).lstrip("0")]
    if not mine:
        return
    try:
        try:
            from . import sticker
        except ImportError:
            import sticker
        sticker.paste_on_page(page, mine)
        logger.info(f"页 {page_no}: 已贴 {len(mine)} 张图")
    except Exception as e:
        logger.warn(f"页 {page_no}: 贴图失败，已跳过（{e}）")

def rebuild(work_dir, output_pdf, logger):
    with open(work_dir / "manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    pages = {p["page"]: p for p in manifest["pages"]}
    total = len(manifest["pages"])

    mapping = load_order(work_dir, total, logger)   # 新页码 -> 内容页码

    texts = {}
    tpath = work_dir / "text.csv"
    if tpath.exists():
        for r in _read_dicts(tpath):
            no = (r.get("no") or "").strip()
            if no:
                texts.setdefault(no, []).append(r)   # 同页多行都保留

    stk_rows = _load_stickers(work_dir)              # 贴图一次读入，循环里查

    # 空白页尺寸：跟随原 PDF（用第一张正常页的尺寸当参照）
    ref = next((p for p in manifest["pages"] if p.get("status") == "已确认"), None)
    blank_w = ref["width_pt"] if ref else 595
    blank_h = ref["height_pt"] if ref else 842

    doc = fitz.open()

    for new_no in sorted(mapping):
        if mapping[new_no] == 0:                          # 空白页
            doc.new_page(width=blank_w, height=blank_h)
            logger.info(f"新页 {new_no}: 空白页")
            continue
        src = pages[mapping[new_no]]

        if src.get("status") == "缺失":
            page = doc.new_page(width=blank_w, height=blank_h)
            page.insert_text((72, 100), f"[占位页 {new_no}]",
                             fontname="china-s", fontsize=14)
            logger.warn(f"新页 {new_no}（原页 {src['page']}）缺失，用占位页代替")
            continue
        page = doc.new_page(width=src["width_pt"], height=src["height_pt"])
        page.insert_image(page.rect, filename=str(work_dir / src["image"]))
        # 字跟随内容页：用内容页的 no 去 text.csv 里找（同页可有多行，逐行插入）
        for row in texts.get(src["no"], []):
            _insert_text(page, row, logger)
        # 贴图：必须盖在文字之后，否则图会压住字
        _paste_stickers(page, stk_rows, src["no"], logger)
    doc.save(str(output_pdf), deflate=True)
    doc.close()
    logger.info(f"重建完成（含重排/替换/插字/贴图）: {output_pdf}")
