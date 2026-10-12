# -*- coding: utf-8 -*-
"""把项目里的代码/文档文件合并成一个 txt，方便整包发给别人看。
用法：双击运行，或 python 打包发我.py
生成：_打包.txt（在项目根目录）

v0.2：缩进/行尾规范化 + 缩进模式标注 + 混合缩进报警。
v0.3：.py 逐个 compile() 语法体检；顶部加阅读须知；
      .py 非 UTF-8 拒收。
v0.4：修正 v0.3 的过度承诺（阅读须知收窄、行号承诺删除、
      tab 只展开行首、detect_indent 识别行内混用）。
v0.5：compile() 除 SyntaxError 外，补捕获 ValueError
      （含 \\x00 的 .py 会抛它而非 SyntaxError，原先会让打包器自己崩），
      再加一层 Exception 兜底，保证单文件异常不带走整个打包。
v0.6：保留"不规则空格⚠"（不因误报就取消检测），
      改 PREAMBLE 明确它是"告警"而非"结论"，
      并把续行对齐列为最常见来源（附"结合语法✔ 判断"的方法）；
      detect_indent 改为只统计块缩进（前一行以 : 结尾），
      续行对齐不再拉低 gcd，误报大幅减少。
"""
from pathlib import Path
from math import gcd
from functools import reduce

INCLUDE = {".py", ".txt", ".csv", ".json", ".md"}
SKIP_DIRS = {"__pycache__", ".vscode", ".git", "venv", ".venv",
             "输出", "output", "build", "dist"}
MAX_KB = 200
TAB_WIDTH = 4

root = Path(__file__).resolve().parent
out_path = root / "_打包.txt"

PREAMBLE = (
    "━━━━ 阅读须知（发给 AI 分析时整段带上）━━━━\n"
    "1. 本打包内的 .py：行首 tab 已展开为 4 空格，行尾已统一为 \\n；\n"
    "   原生使用空格缩进的文件保持原样。每份文件的'缩进='标注\n"
    "   记录的是规范化之前的原始形态（tab / 4空格 / 混合⚠ 等）。\n"
    "2. 每份 .py 都通过了 compile() 检查，文件头标 '语法✔'。\n"
    "   这只证明不存在 IndentationError 级别的破碎，\n"
    "   不证明'某段缩进在语义上贴对了位置'——\n"
    "   语法合法但缩进贴错的代码（例如本该在循环体内的 if\n"
    "   被贴到了循环体外）compile() 照样通过。\n"
    "   凡涉及缩进语义的判断（'这段在不在某块肚子里'），\n"
    "   必须先向使用者确认原始 .py，不得仅凭本打包下结论。\n"
    "3. '缩进=不规则空格⚠' 是告警不是结论，常见来源是续行对齐：\n"
    "   函数调用/列表/字典跨行时，续行对齐到括号内某个位置，\n"
    "   宽度天然不是 4 的倍数（如 9、12、17），合法且常见；\n"
    "   也可能是真的缩进错乱。看这个 ⚠ 时结合第 2 条：\n"
    "   若同时标 '语法✔'，多半是续行对齐，不必惊慌；\n"
    "   真正错乱的缩进会导致 IndentationError，已被 compile()\n"
    "   拦下并标 '⚠语法错'。要确认真假，须看原始 .py。\n"
    "4. 若某 .py 的文件头标 '⚠文件有非法字符' 或 '⚠语法错'，\n"
    "   该文件本身可能已被破坏，请勿基于它下任何结论。\n"
    "5. 设计语义（某功能'该不该这样'）拿不准时，\n"
    "   先问使用者该功能是否存在、是否有意为之，勿直接判为 bug。\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
)


def detect_indent(text):
    """识别缩进模式。'不规则'只在块缩进里判，
    续行对齐（括号内跨行）不计入，避免误报。"""
    lines = text.split("\n")
    has_tab = has_space = False
    block_widths = []
    prev = ""
    for l in lines:
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        i = 0
        while i < len(l) and l[i] in (" ", "\t"):
            i += 1
        head = l[:i]
        if "\t" in head and " " in head:
            return "混合(同行tab+空格)⚠"
        if "\t" in head:
            has_tab = True
        elif i > 0:
            has_space = True
            # 只统计"块缩进"：上一行以 : 结尾（且不在括号里）
            if prev.rstrip().endswith(":") and i not in block_widths:
                block_widths.append(i)
        prev = l
    if has_tab and has_space:
        return "混合(tab行+空格行)⚠"
    if has_tab:
        return "tab"
    if has_space:
        if not block_widths:
            return "空格"
        unit = reduce(gcd, block_widths)
        if unit == 1:
            return "不规则空格⚠"
        return f"{unit}空格"
    return "无缩进"


def _expand_lead_tabs(line, w):
    """只展开行首连续的 tab；字符串字面量里的 tab 不动。"""
    i = 0
    while i < len(line) and line[i] == "\t":
        i += 1
    return " " * (i * w) + line[i:]


def normalize(text):
    """行尾统一 \\n；行首 tab 展开；去行尾空白（保留行首缩进）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_expand_lead_tabs(l, TAB_WIDTH).rstrip()
             for l in text.split("\n")]
    return "\n".join(lines)


parts, total, syn_bad = [], 0, 0
for f in sorted(root.rglob("*")):
    if not f.is_file():
        continue
    if any(part in SKIP_DIRS for part in f.relative_to(root).parts[:-1]):
        continue
    if f.suffix.lower() not in INCLUDE:
        continue
    if f == out_path:
        continue

    try:
        text = f.read_text(encoding="utf-8")
        enc = "utf-8"
    except UnicodeDecodeError:
        if f.suffix.lower() == ".py":
            print(f"拒收（.py 不是 UTF-8，防编码暗雷）：{f.relative_to(root)}")
            continue
        text = f.read_text(encoding="gbk", errors="replace")
        enc = "gbk(有损)"
    except Exception as e:
        print(f"跳过（读不了）：{f.relative_to(root)}  {e}")
        continue

    if len(text.encode("utf-8")) > MAX_KB * 1024:
        print(f"跳过（太大）：{f.relative_to(root)}")
        continue

    indent = detect_indent(text)
    text = normalize(text)

    syn = ""
    if f.suffix.lower() == ".py":
        try:
            compile(text, str(f), "exec")
            syn = ", 语法✔"
        except SyntaxError as e:
            syn = f", ⚠语法错：第{e.lineno}行 {e.msg}"
            syn_bad += 1
        except ValueError:
            # 典型：含 \x00（二进制污染 / 拷贝截断）
            syn = ", ⚠文件有非法字符（疑似二进制污染），拒发"
            syn_bad += 1
        except Exception as e:
            # 兜底：不让任何单文件异常把整个打包带走
            syn = f", ⚠compile 未知异常：{type(e).__name__}: {e}"
            syn_bad += 1

    n_lines = text.count("\n") + 1
    rel = f.relative_to(root)
    size = f.stat().st_size
    head = (f"\n{'='*60}\n"
            f"【文件】{rel}  ({size} 字节, {n_lines} 行, "
            f"编码={enc}, 缩进={indent}{syn})\n"
            f"来源: {f.resolve()}\n"
            f"{'='*60}\n")
    parts.append(head + text)
    total += 1
    print(f"已收录：{rel}")

out_path.write_text(PREAMBLE + "".join(parts), encoding="utf-8")
print(f"\n✔ 完成：共收录 {total} 个文件 → {out_path}")
if syn_bad:
    print(f"⚠ 其中 {syn_bad} 个 .py 有问题（语法错或非法字符），"
          f"先修好再发给 AI 分析，否则对方会对着坏代码白诊断。")
print("提示：语法✔ 仅表示缩进没有破成语法错；"
      "'这段缩进是不是作者想要的'仍须人工确认。")