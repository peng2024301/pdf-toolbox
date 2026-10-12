# -*- coding: utf-8 -*-
"""模式：重建（重排 + 替换 + 插字）。守接口三规矩：参数进、规范出、写日志收尾。"""
from pathlib import Path
from core.common import ensure_output_dir, unique_path, Logger, FatalError
from core.splitter import split_pdf
from core.rebuilder import rebuild

def run(params, log_print=print):
    input_file = Path(params["input_file"])
    if not input_file.exists():
        raise FatalError(f"输入文件不存在: {input_file}")

    final_dir, work_dir, log_dir = ensure_output_dir(
        params.get("output_dir"), input_file, task_name="重建插字")
    logger = Logger(log_dir)
    logger.info(f"工作目录: {work_dir}")
    log_print(f"工作目录: {work_dir}")

    # 1. 拆页
    logger.info(f"输入: {input_file}")
    split_pdf(input_file, work_dir, logger)
    log_print("拆页完成，请审核 工作文件/text.csv（插字）和 order.csv（换页）后再运行。")

    # 2. 一步重建：重排 + 替换 + 插字
    final = unique_path(final_dir / f"{input_file.stem}_完成.pdf")
    rebuild(work_dir, final, logger)

    logger.info(f"=== 完成。最终文件: {final} ===")
    log_print(f"完成！输出目录: {final_dir}")
    return {"final": final, "work_dir": work_dir}
