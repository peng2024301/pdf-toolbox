# -*- coding: utf-8 -*-
"""共用底层：配置加载、输出目录、日志、异常分级。"""
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class FatalError(Exception):
    """致命错误：输出目录不可写、输入损坏、依赖缺失——立即停止。"""
    pass

def load_config():
    with open(PROJECT_ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def ensure_output_dir(user_dir=None, source_file=None, task_name="任务"):
    """输出目录三分：最终文件 / 工作文件 / 日志。返回三个 Path。"""
    if user_dir:
        root = Path(user_dir)
    else:
        cfg = load_config()
        if cfg["output_policy"] == "source_dir" and source_file:
            date = datetime.now().strftime("%Y%m%d")
            root = Path(source_file).parent / f"输出_{date}" / task_name
        else:
            root = PROJECT_ROOT / "输出" / task_name

    # 按源 PDF 隔离：每个输入文件有独立的工作/最终/日志目录，杜绝混用
    if source_file:
        root = root / Path(source_file).stem

    try:
        root.mkdir(parents=True, exist_ok=True)
        test = root / ".write_test"
        test.touch(); test.unlink()
    except OSError as e:
        raise FatalError(f"输出目录不可写: {root} ({e})")

    final_dir = root / "最终文件"
    work_dir  = root / "工作文件"
    log_dir   = root / "日志"
    for d in (final_dir, work_dir, log_dir):
        d.mkdir(exist_ok=True)
    return final_dir, work_dir, log_dir

def unique_path(path):
    """冲突策略：自动加序号，永不覆盖。"""
    path = Path(path)
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1

class Logger:
    """每步一行、带时间戳。日志是记事本环境下唯一的调试手段。"""
    def __init__(self, log_dir, name="run"):
        self.path = log_dir / f"{name}.log"
        self._write("=== 运行开始 ===")

    def _write(self, msg):
        line = f"[{now_str()}] {msg}"
        print(line)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def info(self, msg):  self._write(msg)
    def warn(self, msg):  self._write(f"[警告] {msg}")
    def error(self, msg): self._write(f"[错误] {msg}")
