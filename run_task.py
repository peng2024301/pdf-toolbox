# -*- coding: utf-8 -*-
"""一键流程：执行总纲的每一步，并在每步之后自动体检，确认干成了没有。"""
import sys
import json
import fitz
from pathlib import Path

from core.common import ensure_output_dir, unique_path, Logger, FatalError
from core.splitter import split_pdf
from core.rebuilder import rebuild
from check_tables import check

TASK = "重建插字"

def report(work_dir, 标题):
    """体检并打印结果。有致命错误就停下，不让坏表流进下一步。"""
    errors, warns = [], []
    check(work_dir, errors, warns)
    print(f"\n----- 自动体检（{标题}）-----")
    for w in warns:
        print(f"  [提示] {w}")
    for e in errors:
        print(f"  [致命] {e}")
    if errors:
        raise FatalError(f"{标题}没通过体检（共 {len(errors)} 个问题），按上面提示改表")
    print("  ✔ 体检通过")

def verify_pdf(final_pdf, work_dir, 标题):
    """确认成品真的生成了、页数和页序表一致。"""
    # 正确页数以 order.csv 为准（删页/空白页后和原 PDF 页数不一样）
    order_csv = Path(work_dir) / "order.csv"
    expected = 0
    if order_csv.exists():
        with open(order_csv, encoding="utf-8-sig") as f:
            expected = max(0, sum(1 for _ in f) - 1)   # 减去表头
    if not final_pdf.exists():
        raise FatalError(f"{标题}：成品文件没找到：{final_pdf}")
    doc = fitz.open(final_pdf)
    n = doc.page_count
    doc.close()
    if n != expected:
        raise FatalError(f"{标题}：成品 {n} 页，页序表是 {expected} 页，页数对不上，检查……")
    print(f"  ✔ 成品验证通过：{n} 页，和页序表一致")

def pick_input():
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists() and p.suffix.lower() == ".pdf":
            return p
        print(f"[致命] 拖进来的不是有效的 PDF：{p}")
    print("把 PDF 文件拖到本窗口里，然后按回车（或直接输入 PDF 完整路径）：")
    p = Path(input("> ").strip().strip('"'))
    if not (p.exists() and p.suffix.lower() == ".pdf"):
        raise FatalError(f"输入文件不存在或不是 PDF：{p}")
    return p

def main():
    print("=" * 40)
    print("  PDF 工具箱 · 流程执行器（带自动体检）")
    print("=" * 40)
    pdf = pick_input()
    final_dir, work_dir, log_dir = ensure_output_dir(None, pdf, task_name=TASK)
    logger = Logger(log_dir, name="流程执行")
    logger.info(f"输入: {pdf}")
    print(f"\n工作文件在：{work_dir}")

    order_csv = work_dir / "order.csv"
    text_csv = work_dir / "text.csv"

    print("\n请选择要执行哪一步：")
    print("  1 = 第一步：拆页（生成/不覆盖两张表）")
    print("  2 = 第二步：按两张表重排 + 替换 + 插字，出成品")
    print("  3 = 完整跑一遍（拆页后直接出成品）")
    choice = input("输入 1 / 2 / 3 后回车：").strip()

    if choice == "1":
        split_pdf(pdf, work_dir, logger)
        logger.info("第一步拆页完成")
        report(work_dir, "拆页")          # ← 拆完自动查表
        print(f"\n✔ 第一步完成。两张表已生成（已有表不会被覆盖）：")
        print(f"    {text_csv}\n    {order_csv}")
        print("  改完保存，再运行本脚本选 2。")

    elif choice == "2":
        if not order_csv.exists() or not text_csv.exists():
            raise FatalError("两张表还没生成，先选 1 跑第一步拆页。")
        report(work_dir, "运行前")        # ← 跑之前先查表，坏表不出成品
        final = unique_path(final_dir / f"{pdf.stem}_完成.pdf")
        rebuild(work_dir, final, logger)
        logger.info("第二步重建完成")
        verify_pdf(final, work_dir, "第二步")  # ← 跑完验证成品
        print(f"\n✔ 第二步完成。成品在：\n  {final}")

    elif choice == "3":
        split_pdf(pdf, work_dir, logger)
        report(work_dir, "拆页")
        final = unique_path(final_dir / f"{pdf.stem}_完成.pdf")
        rebuild(work_dir, final, logger)
        verify_pdf(final, work_dir, "完整流程")
        print(f"\n✔ 完整流程完成。成品在：\n  {final}")

    else:
        print("没这个选项，重跑再选。")

    logger.info("=== 流程结束 ===")
    input("\n按回车关闭……")

if __name__ == "__main__":
    try:
        main()
    except FatalError as e:
        print(f"\n[致命] {e}")
        print("按提示改好后再来。")
        input("按回车关闭……")
    except Exception as e:
        print(f"\n[致命] 出错了：{e}")
        print("完整报错见 日志/流程执行.log，把上面这行抄下来求助。")
        input("按回车关闭……")
