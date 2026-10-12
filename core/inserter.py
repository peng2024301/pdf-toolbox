# -*- coding: utf-8 -*-
"""按编号插入文字。只填 no,text 时用默认规则；高级用户可填坐标和样式。"""
import csv
import fitz
from pathlib import Path
from .common import load_config

def load_text_csv(work_dir):
    rows = []
    path = work_dir / "text.csv"
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    nos = [r["no"] for r in rows]
    if len(nos) != len(set(nos)):
        raise ValueError("text.csv 中 no 列有重复，请修正后再运行")
    return rows

def get_font():
    """优先 config 指定字体文件，否则用内置中文字体。"""
    cfg = load_config()
    fp = cfg.get("font_path", "")
    if fp:
        from pathlib import Path as P
        if P(fp).exists():
            return "custom", fp
    return "builtin", cfg.get("font_fallback", "china-s")

def insert_text(input_pdf, output_pdf, work_dir, logger):
    rows = load_text_csv(work_dir)
    font_kind, font_val = get_font()
    doc = fitz.open(input_pdf)
    inserted, missing = 0, []

    for r in rows:
        text = (r.get("text") or "").strip()
        if not text:
            if r.get("status") in ("待审核", "缺失"):
                missing.append({"no": r["no"], "reason": "缺文字",
                                "note": "text 为空"})
            continue
        try:
            page = doc[int(r["no"]) - 1]  # 编号即页序
            x = float(r["x"]) if r.get("x") else 72
            y = float(r["y"]) if r.get("y") else 72
            size = float(r["size"]) if r.get("size") else 12
            if font_kind == "custom":
                page.insert_font(fontname="userfont", fontfile=font_val)
                fname = "userfont"
            else:
                fname = font_val
            page.insert_text((x, y), text, fontname=fname, fontsize=size)
            r["status"] = "已确认"
            inserted += 1
            logger.info(f"页 {r['no']} 插字: {text[:20]}")
        except Exception as e:
            missing.append({"no": r["no"], "reason": "坐标无效或页面损坏",
                            "note": str(e)})
            logger.warn(f"页 {r['no']} 插字失败: {e}")

    doc.save(str(output_pdf), deflate=True)
    doc.close()

    if missing:
        with open(work_dir / "missing.csv", "w", encoding="utf-8-sig",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=["no", "reason", "note"])
            w.writeheader()
            w.writerows(missing)
        logger.warn(f"有 {len(missing)} 条缺失，见 missing.csv")
    logger.info(f"插字完成，共插入 {inserted} 条")
    return missing
