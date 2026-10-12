# -*- coding: utf-8 -*-
"""表格体检：双击运行，按总纲规则检查 text.csv 和 order.csv，有问题说人话。
v0.2：总页数以 manifest.json 为准（不再拿 text.csv 行数推）；
      text.csv 允许同页多行（格子填字一页多格），no 只校验范围。
v0.3：manifest 读取提前到函数开头，与 text.csv 是否存在解耦；
      修掉"text.csv 缺失/为空时误报'没有 manifest.json'"的文案谎言。
"""
import csv
import json
import sys
from pathlib import Path

def read_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.reader(f))

def _page_total(work_dir):
    """总页数以 manifest.json 为准，不再用 text.csv 行数推。"""
    try:
        data = json.load(open(work_dir / "manifest.json", encoding="utf-8"))
        pages = data.get("pages", data)
        return len(pages)
    except Exception:
        return None

def check(work_dir, errors, warns):
    # 总页数提前读，与 text.csv 是否存在无关
    total = _page_total(work_dir)
    if total is None:
        errors.append("找不到/读不了 manifest.json，页数校验跳过——先重新跑第一步拆页")

    # ---- 检查 text.csv ----
    tpath = work_dir / "text.csv"
    if not tpath.exists():
        errors.append(f"找不到 {tpath}，先跑第一步拆页")
    else:
        rows = read_rows(tpath)
        if not rows:
            errors.append("text.csv 是空的，重新跑第一步拆页")
        else:
            header, body = rows[0], rows[1:]
            if len(header) != 8:
                errors.append(f"text.csv 表头应是 8 格，现在 {len(header)} 格：{header}")
            for i, r in enumerate(body, start=2):
                if len(r) != 8:
                    errors.append(f"text.csv 第 {i} 行格子数是 {len(r)}，应是 8 格（英文逗号分隔）")
                    continue
                no = r[0].strip()
                if not no:
                    errors.append(f"text.csv 第 {i} 行 no 列是空的")
                    continue
                if not no.isdigit():
                    errors.append(f"text.csv 第 {i} 行 no 不是数字：{no}")
                    continue
                if total and not 1 <= int(no) <= total:
                    errors.append(f"text.csv 第 {i} 行 no={no} 超出页数范围（共 {total} 页）")
            warns.append(f"text.csv 共 {len(body)} 行（同页可多行），"
                         f"填了字的 {sum(1 for r in body if len(r)>1 and r[1].strip())} 行")

    # ---- 检查 order.csv ----
    opath = work_dir / "order.csv"
    if not opath.exists():
        errors.append(f"找不到 {opath}，先跑第一步拆页")
    else:
        rows = read_rows(opath)
        if not rows:
            errors.append("order.csv 是空的，重新跑第一步拆页")
        else:
            header, body = rows[0], rows[1:]
            if header[:3] != ["new_no", "old_no", "replace_from"]:
                errors.append(f"order.csv 表头应是 new_no,old_no,replace_from，现在是：{header}")
            news, olds = [], []
            for i, r in enumerate(body, start=2):
                try:
                    new_no = int((r[0] if len(r) > 0 else "").strip())
                    old_no = int((r[1] if len(r) > 1 else "").strip())
                except ValueError:
                    errors.append(f"order.csv 第 {i} 行页码不是数字：{r[:2]}")
                    continue
                news.append(new_no)
                olds.append(old_no)
                if len(r) > 2 and r[2].strip():
                    try:
                        rf = int(r[2].strip())
                        if total and not 1 <= rf <= total:
                            errors.append(f"order.csv 第 {i} 行 replace_from={rf} 超出范围（共 {total} 页）")
                    except ValueError:
                        errors.append(f"order.csv 第 {i} 行 replace_from 不是数字：{r[2]}")
            dup = {n for n in news if news.count(n) > 1}
            if dup:
                errors.append(f"order.csv 的 new_no 有重复：{sorted(dup)}——不许加行删行")
            m_rows = len(body)
            if total:
                miss = [n for n in range(1, m_rows + 1) if n not in news]
                if miss:
                    errors.append(f"order.csv 缺了这些 new_no：{miss}——位置号必须从1连续")
                if m_rows > total:
                    errors.append(f"order.csv 有 {m_rows} 行，比总页数 {total} 还多——删页用口令，别手工加行")
            blanks = 0
            for i, n in enumerate(olds, start=2):
                if n == 0:
                    blanks += 1
                    continue
                if total and not 1 <= n <= total:
                    errors.append(f"order.csv 第 {i} 行 old_no={n} 超出范围（共 {total} 页）")
            d2 = {n for n in olds if n != 0 and olds.count(n) > 1}
            if d2:
                errors.append(f"order.csv 的 old_no 有重复：{sorted(d2)}——每页内容只能被用一个位置（0=空白页不算）")
            if blanks:
                warns.append(f"order.csv 有 {blanks} 张空白页")

            moved = sum(1 for r in body if len(r) > 1 and r[0].strip() != r[1].strip())
            warns.append(f"order.csv 换了 {moved} 页位置，强行换图 {sum(1 for r in body if len(r)>2 and r[2].strip())} 页")

def main():
    root = Path(__file__).resolve().parent
    errors, warns = [], []

    # 找所有工作文件目录（输出目录结构里带"工作文件"的都查一遍）
    work_dirs = [p.parent for p in root.rglob("工作文件") if p.is_dir()]
    if not work_dirs:
        print("没找到任何 工作文件/ 目录——先跑第一步拆页。")
        input("按回车关闭……")
        return

    for wd in work_dirs:
        print(f"\n===== 检查：{wd} =====")
        e2, w2 = [], []
        check(wd, e2, w2)
        for w in w2:
            print(f"  [提示] {w}")
        for e in e2:
            print(f"  [致命] {e}")
        if not e2 and not w2:
            print("  （空目录，跳过）")
        elif not e2:
            print("  ✔ 这张表没问题，可以点一键运行了")
        errors += e2

    print("\n" + "=" * 40)
    if errors:
        print(f"共 {len(errors)} 个问题，改完表再跑程序。")
        print("改表要点：英文逗号分格、不加行不删行、old_no 每页恰好用一次。")
    else:
        print("全部通过 ✔ → 回程序点一键运行即可。")
    input("按回车关闭……")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[致命] 体检脚本自己出错了：{e}")
        input("按回车关闭……")