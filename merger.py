# -*- coding: utf-8 -*-
"""并入另一个 PDF：渲染缩略图 + 扫空位 + 队尾追加 order.csv。
新页从现有最大页号之后续编，统一排在队尾（用拖拽排序调整位置）。
"""

import json
import tempfile
from pathlib import Path

import fitz

import order_editor
import slot_scanner


def merge_pdf(pdf_path: str, work_dir: Path, header, body):
    """把 pdf_path 的所有页并入工作区。body 原地修改并写回 order.csv。"""
    src = fitz.open(pdf_path)
    if len(src) == 0:
        raise ValueError("对方 PDF 一页都没有")

    # ① 续编页号：接在现有最大号后
    used = []
    for r in body:
        try:
            used.append(int(r[1]))
        except (ValueError, IndexError):
            pass
    nxt = (max(used) if used else 0) + 1

    # ② 渲染缩略图 PNG（和拆页同款：三位编号.png）
    from core.common import load_config
    dpi = load_config()["render_dpi"]
    for i, page in enumerate(src):
        pix = page.get_pixmap(dpi=dpi)
        pix.save(work_dir / f"{nxt + i:03d}.png")
        
    # ②.5 同步 manifest.json：体检靠它算总页数，重建靠它找页面
    # （独立成段，只追加一次；放进渲染循环会导致每渲染一页追加全部新页）
    manifest_path = work_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for i, page in enumerate(src):
        manifest["pages"].append({
            "no": f"{nxt + i:03d}",
            "source": str(pdf_path),
            "page": nxt + i,
            "type": "页面图像",
            "width_pt": round(page.rect.width, 2),
            "height_pt": round(page.rect.height, 2),
            "rotation": page.rotation,
            "dpi": dpi,
            "image": f"{nxt + i:03d}.png",
            "status": "已确认",
        })
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # ③ 扫新 PDF 的空位到临时文件，再并进 slots.json
    slots_path = work_dir / "slots.json"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "slots.json"
        slot_scanner.scan_pdf(pdf_path, tmp)
        new_slots = json.loads(tmp.read_text(encoding="utf-8"))
    old_slots = {}
    if slots_path.exists():
        old_slots = json.loads(slots_path.read_text(encoding="utf-8"))
    for i in range(len(src)):
        # 新页在 slots 里的键 = 它在对方 PDF 里的页号（1 起）
        page_slots = []
        for s in new_slots.get(str(i + 1), []):
            s = dict(s)                          # 别改原对象
            s["页"] = nxt + i                    # 页号改成新 PDF 的
            s["编码"] = f"P{nxt + i}R{s['行']}C{s['列']}"   # 编码同步
            page_slots.append(s)
        old_slots[str(nxt + i)] = page_slots
    slots_path.write_text(json.dumps(old_slots, ensure_ascii=False, indent=1),
                          encoding="utf-8")

    # ④ 队尾追加 order 行，写回 order.csv
    added = []
    for i in range(len(src)):
        row = [f"{nxt + i:03d}", str(nxt + i), ""]
        body.append(row)
        added.append(nxt + i)
    order_editor.save_table(work_dir / "order.csv", header, body)
    return added