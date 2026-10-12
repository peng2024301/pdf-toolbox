# -*- coding: utf-8 -*-
from pathlib import Path
path = Path(__file__).parent / "待办与坑.txt"
data = path.read_bytes()
print("前16字节(hex):", data[:16].hex())
print("-" * 50)

winner = None
for enc in ["utf-8-sig", "utf-8", "utf-16", "gb18030", "big5", "shift_jis"]:
    try:
        text = data.decode(enc)
        print(f"[{enc}] 前60字: {text[:60]!r}")
        if winner is None and enc not in ("utf-8",):
            winner = enc
    except Exception:
        print(f"[{enc}] 解码失败")

print("-" * 50)
if winner:
    out = path.parent / "待办与坑_utf8.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(data.decode(winner))
    print(f"已用 [{winner}] 解码并另存为: {out}")
else:
    print("所有编码都解不出，文件可能已被破坏，需重写")
