# -*- coding: utf-8 -*-
"""order.csv：自由重排 + 替换。内容跟随来源页，位置跟随 new_no。"""
import csv
from .common import FatalError

def _read_dicts(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def load_order(work_dir, total, logger):
    """返回 {新页码: 内容页码}。无表 = 原序 1:1。"""
    path = work_dir / "order.csv"
    if not path.exists():
        logger.info("未找到 order.csv，按原页序重建")
        return {i: i for i in range(1, total + 1)}

    mapping = {}
    old_nos = []
    for r in _read_dicts(path):
        try:
            new_no = int((r.get("new_no") or "").strip())
            old_no = int((r.get("old_no") or "").strip())
        except ValueError:
            raise FatalError(f"order.csv 中页码不是数字: {dict(r)}")
        if old_no != 0:
            old_nos.append(old_no)
        rf = (r.get("replace_from") or "").strip()
        content = int(rf) if rf else old_no
        # 位置号必须在 1..total；内容号 0 = 空白页，合法
        if not 1 <= new_no <= total:
            raise FatalError(f"order.csv 里 new_no={new_no} 超出范围（共 {total} 页）")
        if rf and not 1 <= int(rf) <= total:
            raise FatalError(f"order.csv 里 replace_from={rf} 超出范围（共 {total} 页）")
        if content != 0 and not 1 <= content <= total:
            raise FatalError(f"order.csv 里 old_no={old_no} 超出范围（共 {total} 页）")
        if new_no in mapping:
            raise FatalError(f"order.csv 中 new_no={new_no} 重复，每行只许出现一次")
        mapping[new_no] = content
    # 位置号必须从 1 开始连续（删页后行数变少也必须是 1..M）
    if sorted(mapping) != list(range(1, len(mapping) + 1)):
        raise FatalError("order.csv 的 new_no 必须从 1 开始连续编号（不许跳号、不许重复）")
    # old_no 除 0（空白）外不许重复；replace_from 产生的
    # 同内容多引用（复制）是允许的，不在此列
    if len(old_nos) != len(set(old_nos)):
        raise FatalError("order.csv 的 old_no 有重复（除空白页外，每页内容只能用一个位置）")
    for new_no, content in mapping.items():
        if content != new_no:
            logger.info(f"页位 {new_no} ← 内容来自原第 {content} 页" if content
                        else f"页位 {new_no} ← 空白页")
    return mapping