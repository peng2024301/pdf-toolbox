# -*- coding: utf-8 -*-
"""打包入口：启动失败时把错误写到 exe 旁的 崩溃日志.txt，方便远程排障。"""
import sys, traceback
from pathlib import Path

def _crash_log():
    try:
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) \
            else Path(__file__).parent
        with open(base / "崩溃日志.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
    except Exception:
        pass

try:
    from main import discover_modes
except Exception:
    def discover_modes():
        import modes.mode_rebuild as m
        return {"rebuild": m}

try:
    import gui
    gui.run_gui(discover_modes())
except Exception:
    _crash_log()
    raise
