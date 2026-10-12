#!/usr/bin/env bash
# PDF 工具箱 - macOS / Linux 安装脚本
# 用法：chmod +x install.sh && ./install.sh

set -e

# 切到脚本所在目录，避免从别处调用时路径错
cd "$(dirname "$0")"

echo "===================================="
echo "  PDF 工具箱 - 安装程序"
echo "===================================="

# 1. 找 python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 没找到 python3"
    echo "  macOS：brew install python3   或到 https://www.python.org/downloads/ 下载"
    echo "  Ubuntu/Debian：sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora：sudo dnf install python3 python3-pip"
    exit 1
fi

# 2. 检查版本 >= 3.9
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "[错误] Python 版本太低，需要 3.9 及以上"
    python3 --version
    exit 1
fi

# 3. 建虚拟环境
if [ ! -d ".venv" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv .venv || {
        echo "[错误] 创建 venv 失败。"
        echo "  Ubuntu/Debian 可能需要先装：sudo apt install python3-venv"
        exit 1
    }
fi

# 4. 装依赖（优先清华源，失败回退官方源）
PY=".venv/bin/python"
echo "正在升级 pip..."
"$PY" -m pip install --upgrade pip >/dev/null

echo "正在安装依赖（首次可能需要几分钟）..."
if ! "$PY" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple; then
    echo "[提示] 清华源失败，改用官方源重试..."
    "$PY" -m pip install -r requirements.txt
fi

# 5. 生成启动器并加执行权限
cat > run.sh <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
.venv/bin/python gui.py
EOF
chmod +x run.sh

# 6. 尝试给个桌面快捷方式（Linux 用 .desktop；macOS 提示手动）
if [ "$(uname)" = "Linux" ]; then
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/pdf-toolbox.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PDF 工具箱
Exec=$(pwd)/run.sh
Path=$(pwd)
Terminal=false
Categories=Utility;
EOF
    chmod +x "$DESKTOP_DIR/pdf-toolbox.desktop"
    echo "已在应用菜单添加快捷方式（可能需要注销重登才显示）"
elif [ "$(uname)" = "Darwin" ]; then
    echo "[提示] macOS 请自行把 run.sh 拖到 Dock，或右键 → 制作替身"
fi

echo
echo "安装完成！"
echo "  启动方式：双击 run.sh，或终端执行 ./run.sh"