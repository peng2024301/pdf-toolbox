# -*- coding: utf-8 -*-
"""换页助手：用户说口令（2换3 / 2替3），程序直接改 order.csv，不碰记事本。"""
import sys
import re
import csv
import json
from pathlib import Path

from core.common import ensure_output_dir, unique_path, Logger, FatalError
from core.splitter import split_pdf
from core.rebuilder import rebuild
from check_tables import check

TASK = "重建插字"

# ---------- 读写 order.csv ----------

def load_table(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]          # 表头，数据行

def save_table(path, header, body):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(body)

def find_row(body, new_no):
    for r in body:
        try:
            if int(r[0]) == new_no:
                return r
        except (ValueError, IndexError):
            continue
    return None

# ---------- 显示 ----------

def show(body):
    total = len(body)
    print("\n   当前页序：")
    for r in body:
        new_no, old_no, rf = int(r[0]), int(r[1]), r[2].strip()
        mark = f"  ←← 图用的是原第 {rf} 页" if rf else ""
        moved = "" if new_no == old_no and not rf else "  [改过]"
        print(f"   第 {new_no} 位 ← 原第 {old_no} 页{mark}{moved}")
    print()

# ---------- 口令解析与执行 ----------

def do_swap(body, a, b):
    """a换b：两个位置的页对调。"""
    ra, rb = find_row(body, a), find_row(body, b)
    if ra is None or rb is None:
        print(f"  [没这页] 总共 {len(body)} 页，{a} 或 {b} 超范围了")
        return False
    ra[1], rb[1] = rb[1], ra[1]
    ra[2], rb[2] = rb[2], ra[2]
    print(f"  ✔ 完成：第 {a} 位和第 {b} 位的页已对调")
    return True

def do_replace(body, a, b):
    """a替b：第 a 位的图换成原第 b 页的图（字也跟着）。"""
    total = len(body)
    ra = find_row(body, a)
    if ra is None or not 1 <= b <= total:
        print(f"  [没这页] 总共 {total} 页，{a} 或 {b} 超范围了")
        return False
    ra[2] = str(b)
    print(f"  ✔ 完成：第 {a} 位的图已换成原第 {b} 页的（字也用 {b} 页的）")
    return True

def do_cancel(body, a):
    """取消某位的强行换图。"""
    ra = find_row(body, a)
    if ra is None:
        print(f"  [没这页] {a} 超范围了")
        return False
    ra[2] = ""
    print(f"  ✔ 完成：第 {a} 位的换图已取消，恢复用自己原页的图")
    return True

def do_reset(body):
    for r in body:
        r[1], r[2] = r[0], ""
    print("  ✔ 完成：全部恢复原始页序，换图清空")
    return True
def do_delete(body, a, b=None):
    """删a / 删a-b：删掉位置，后面的页依次顶上来。"""
    nos = set()
    for r in body:
        try:
            nos.add(int(r[0]))
        except ValueError:
            pass
    if b is None:
        targets = [a] if a in nos else []
    else:
        lo, hi = min(a, b), max(a, b)
        targets = [n for n in range(lo, hi + 1) if n in nos]
    if not targets:
        print(f" [没这页] 要删的页不在当前页序里：{a}" if b is None else f" [没这页] {a}-{b} 里没有可删的页")
        return False
    tset = set(targets)
    body[:] = [r for r in body if int(r[0]) not in tset]
    for i, r in enumerate(body, 1):
        r[0] = f"{i:03d}"
    if b is None:
        print(f" ✔ 已删除第 {a} 位，共 {len(body)} 页（后面依次顶上来）")
    else:
        print(f" ✔ 已删除 {len(targets)} 位（{targets[0]}-{targets[-1]}），共 {len(body)} 页")
    return True

def do_blank(body, a):
    """空a：第 a 位原地变空白页（页数不变，old_no 记 0）。"""
    ra = find_row(body, a)
    if ra is None:
        print(f" [没这页] {a} 超范围了")
        return False
    ra[1] = "0"
    ra[2] = ""
    print(f" ✔ 第 {a} 位已改为空白页（页数不变）")
    return True

def do_restore(body, work_dir):
    """恢复：优先从 origin.csv 快照还原（删掉的页也回来）；没快照退回旧逻辑。"""
    if work_dir is not None:
        o = Path(work_dir) / "origin.csv"
        if o.exists():
            _, body0 = load_table(o)
            body[:] = body0
            print(" ✔ 已恢复到原始页序（删除过的页也回来了）")
            return True
        print(" [提示] 没找到快照 origin.csv，只还原页序，删掉的页找不回来")
    return do_reset(body)

def _ensure_origin(work_dir):
    """第一次删/空前，把盘上的 order.csv 存成快照（老任务没有 origin.csv 的兜底）。"""
    if work_dir is None:
        return
    o = Path(work_dir) / "origin.csv"
    src = Path(work_dir) / "order.csv"
    if not o.exists() and src.exists():
        o.write_text(src.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")

def execute(body, cmd, work_dir=None):
    """解析一条口令。返回 True 表示表被改了。"""
    cmd = cmd.replace(" ", "").replace("，", "").replace(",", "")
    if not cmd:
        return False

    # 删a / 删a-b
    m = re.fullmatch(r"删(\d+)(?:-(\d+))?", cmd)
    if m:
        _ensure_origin(work_dir)
        if m.group(2):
            return do_delete(body, int(m.group(1)), int(m.group(2)))
        return do_delete(body, int(m.group(1)))

    # 空a
    m = re.fullmatch(r"空(\d+)", cmd)
    if m:
        _ensure_origin(work_dir)
        return do_blank(body, int(m.group(1)))

    # a复制b（与 a替b 同义）
    m = re.fullmatch(r"(\d+)复制(\d+)", cmd)
    if m:
        return do_replace(body, int(m.group(1)), int(m.group(2)))

    # a换b / a替b / 取消a
    for word, fn in (("换", do_swap), ("替", do_replace), ("取消", do_cancel)):
        if word == "取消":
            m = re.fullmatch(r"取消(\d+)", cmd)
            if m:
                return fn(body, int(m.group(1)))
        else:
            m = re.fullmatch(r"(\d+)" + word + r"(\d+)", cmd)
            if m:
                return fn(body, int(m.group(1)), int(m.group(2)))

    if cmd in ("恢复", "重置", "还原"):
        return do_restore(body, work_dir)
    if cmd in ("看", "显示", "查看"):
        show(body)
        return False

    print(" [没看懂] 口令写法示例：")
    print(" 2换3 → 第2、3位对调")
    print(" 2替5 → 第2位的图换成原第5页的")
    print(" 取消2 → 取消第2位的换图")
    print(" 删3 → 删掉第3位（后面顶上来，成品变薄）")
    print(" 删2-4 → 范围删除")
    print(" 空3 → 第3位变空白页（页数不变）")
    print(" 恢复 → 回到原始页序（删掉的页也回来）")
    print(" 看 → 看当前页序")
    return False

# ---------- 主流程 ----------

def main():
    print("=" * 40)
    print("  换页助手（说口令就行，不用碰表格）")
    print("=" * 40)

    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if not (p.exists() and p.suffix.lower() == ".pdf"):
            raise FatalError(f"不是有效的 PDF：{p}")
    else:
        print("把 PDF 拖到本窗口，回车：")
        p = Path(input("> ").strip().strip('"'))
        if not (p.exists() and p.suffix.lower() == ".pdf"):
            raise FatalError(f"输入文件不存在或不是 PDF：{p}")

    final_dir, work_dir, log_dir = ensure_output_dir(None, p, task_name=TASK)
    logger = Logger(log_dir, name="换页助手")

    # 没拆过页就先拆
    order_csv = work_dir / "order.csv"
    if not order_csv.exists():
        print("\n还没拆过页，先自动拆一次……")
        split_pdf(p, work_dir, logger)

    header, body = load_table(order_csv)
    show(body)

    changed = False
    print("输口令改页序（2换3 / 2替5 / 取消2 / 恢复 / 看），输 完成 收工：")
    while True:
        cmd = input("  > ").strip()
        if cmd in ("完成", "完", "退出", "q"):
            break
        if execute(body, cmd, work_dir):
            changed = True
            save_table(order_csv, header, body)   # 每次改动立即存盘
            show(body)

    if not changed:
        print("\n没做任何改动，收工。")
        input("按回车关闭……")
        return

    # 出成品前先体检
    errors, warns = [], []
    check(work_dir, errors, warns)
    if errors:
        for e in errors:
            print(f"  [致命] {e}")
        print("表没改好，这次不出成品，改完口令再来。")
        input("按回车关闭……")
        return
    print("  ✔ 表格体检通过")

    ans = input("\n现在就出成品 PDF 吗？（回车=出，输 n=先不出）：").strip().lower()
    if ans != "n":
        final = unique_path(final_dir / f"{p.stem}_完成.pdf")
        rebuild(work_dir, final, logger)
        print(f"\n✔ 成品在：\n  {final}")

    logger.info("=== 换页助手结束 ===")
    input("\n按回车关闭……")

if __name__ == "__main__":
    try:
        main()
    except FatalError as e:
        print(f"\n[致命] {e}")
        input("按回车关闭……")
    except Exception as e:
        print(f"\n[致命] 出错了：{e}")
        print("完整报错见 日志/换页助手.log，把上面这行抄下来求助。")
        input("按回车关闭……")