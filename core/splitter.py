# -*- coding: utf-8 -*-
"""拆页编号：输入只读，渲染成单页 PNG，生成 manifest.json、text.csv、order.csv。"""
import fitz  # PyMuPDF
import csv
import json
from pathlib import Path
from .common import file_hash, load_config, now_str, FatalError

def split_pdf(input_path, work_dir, logger):

    cfg = load_config()
    dpi = cfg["render_dpi"]
    zoom = dpi / 72.0  # PDF 点 -> 像素
    doc = fitz.open(input_path)  # 只读打开，从不写回

    pages = []
    for i, page in enumerate(doc):
        no = f"{i+1:03d}"  # 编号靠页序，不靠 AI 猜
        img_name = f"{no}.png"
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            pix.save(work_dir / img_name)
            pages.append({
                "no": no,
                "source": str(input_path),
                "page": i + 1,
                "type": "页面图像",
                "width_pt": round(page.rect.width, 2),   # 坐标统一用 PDF 点
                "height_pt": round(page.rect.height, 2),
                "rotation": page.rotation,
                "dpi": dpi,
                "image": img_name,
                "status": "已确认",
            })
            logger.info(f"页 {no} 拆出: {pix.width}x{pix.height}px")
        except Exception as e:
            # 单页失败：跳过并记录，不停机
            pages.append({"no": no, "page": i + 1, "status": "缺失",
                          "reason": f"页面损坏: {e}", "image": img_name})
            logger.warn(f"页 {no} 拆页失败，已记入缺失: {e}")
    doc.close()

    manifest = {
        "schema_version": load_config()["manifest_schema_version"],
        "script_version": load_config()["version"],
        "input_file": str(input_path),
        "input_sha256": file_hash(input_path),
        "created": now_str(),
        "params": {"dpi": dpi},
        "pages": pages,
    }
    with open(work_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # text.csv：UTF-8-SIG，用户只需填 no 和 text；已存在则不覆盖，保住用户填写的内容
    csv_path = work_dir / "text.csv"
    if not csv_path.exists():
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["no", "text", "x", "y", "size", "color", "align", "status"])
            for p in pages:
                if p.get("status") != "缺失":
                    w.writerow([p["no"], "", "", "", "", "", "", "待审核"])

    # order.csv：默认 1→1 原序；已存在则不覆盖，保住用户改过的页序
    order_path = work_dir / "order.csv"
    if not order_path.exists():
        with open(order_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["new_no", "old_no", "replace_from"])
            for p in pages:
                w.writerow([f"{p['page']:03d}", f"{p['page']:03d}", ""])

    # 原始快照：恢复口令的依据（拆页时的最原始页序，之后永不改动）
    # 注意：与 order.csv 是否存在解耦——只要 origin.csv 缺，就按本次拆页
    # 重建（用于补建老任务缺失的 origin.csv）
    origin_path = work_dir / "origin.csv"
    if not origin_path.exists():
        with open(origin_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["new_no", "old_no", "replace_from"])
            for p in pages:
                w.writerow([f"{p['page']:03d}", f"{p['page']:03d}", ""])
                
    logger.info(f"拆页完成，共 {len(pages)} 页，已生成 manifest.json / text.csv / order.csv / origin.csv")
