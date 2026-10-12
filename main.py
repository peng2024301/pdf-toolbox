# -*- coding: utf-8 -*-
"""入口：分发到 CLI / GUI / 开发者模式。模式由 modes/ 自动发现。"""
import sys
import json
import importlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

def discover_modes():
    """扫描 modes/ 自动注册，加模式 = 加文件，不改本文件。
    打包版没有 .py 文件，靠 build.bat 的 --collect-submodules 把模块编译进去，
    这里按文件名兜底。"""
    modes = {}
    files = sorted((PROJECT_ROOT / "modes").glob("mode_*.py"))
    names = [f.stem for f in files]
    if not names and getattr(sys, "frozen", False):
        names = ["mode_rebuild"]
    for stem in names:
        try:
            mod = importlib.import_module(f"modes.{stem}")
        except Exception as e:
            try:
                from pathlib import Path as _P
                import sys as _s
                base = _P(getattr(_s, "executable", __file__)).parent
                with open(base / "模式加载日志.txt", "w", encoding="utf-8") as _f:
                    _f.write(f"{stem}: {e}")
            except Exception:
                pass
            continue
        if hasattr(mod, "run"):
            modes[stem.replace("mode_", "")] = mod
    return modes
def dev_mode():
    """开发者模式：打印当前约定摘要，防止遗忘。"""
    try:
        cfg = json.load(open(PROJECT_ROOT / "config.json", encoding="utf-8"))
    except Exception as e:
        print(f"[致命] 读不了 config.json：{e}")
        print("请检查项目根目录下是否存在 config.json，且 JSON 语法正确。")
        return
    modes = discover_modes()
    print("=" * 50)
    print("【开发者模式】当前约定摘要")
    print(f"  脚本版本: {cfg['version']}  manifest版本: {cfg['manifest_schema_version']}")
    print(f"  渲染 DPI: {cfg['render_dpi']}（坐标统一 PDF 点）")
    print(f"  字体: {cfg['font_path'] or '内置 ' + cfg['font_fallback']}")
    print(f"  输出三分: 最终文件 / 工作文件 / 日志")
    print(f"  已注册模式: {', '.join(modes) or '无'}")
    print(f"  原则: 原文件只读 | 异常分级 | 永不默认覆盖")
    print(f"  详细约定见 docs/ 约定总纲.txt")
    print("=" * 50)

def main():
    args = sys.argv[1:]
    if "--dev" in args:
        dev_mode()
        if len(args) == 1:
            return
        args.remove("--dev")

    modes = discover_modes()
    if "--cli" in args:
        i = args.index("--cli")
        input_file = args[i + 1] if len(args) > i + 1 else None
        if not input_file:
            print("用法: python main.py --cli 输入文件.pdf [输出目录]")
            return
        out = args[i + 2] if len(args) > i + 2 else None
        modes["rebuild"].run({"input_file": input_file, "output_dir": out})
    else:
        from gui import run_gui
        run_gui(modes)

if __name__ == "__main__":
    main()