#!/usr/bin/env bash
# nianbao 一键安装：Claude Code 和 Codex 通用。
#   - 装了 Claude Code（有 ~/.claude）→ 装到 ~/.claude/skills/nianbao
#   - 装了 Codex（有 $CODEX_HOME，默认 ~/.codex）→ 装到 $CODEX_HOME/skills/nianbao
#   - Python 依赖（PyMuPDF、Playwright + Chromium）装进单独的环境 ~/.nianbao/venv，不动系统的 Python
# 已经装过的，再跑一次就是更新。
set -euo pipefail

REPO="${NIANBAO_REPO:-https://github.com/siqiy438-source/nianbao-skill.git}"
NAME="nianbao"
VENV="$HOME/.nianbao/venv"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"

say() { printf '%s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { say "✗ 缺少 $1：$2"; exit 1; }; }
need git "先安装 git（macOS 上运行 xcode-select --install）"
need python3 "先安装 Python 3（macOS 上运行 xcode-select --install，或 brew install python）"

targets=()
[ -d "$HOME/.claude" ] && targets+=("$HOME/.claude/skills/$NAME")
[ -d "$CODEX_DIR" ] && targets+=("$CODEX_DIR/skills/$NAME")
if [ ${#targets[@]} -eq 0 ]; then
  say "没找到 Claude Code（~/.claude）或 Codex（$CODEX_DIR），先装到 ~/.claude/skills/$NAME"
  targets+=("$HOME/.claude/skills/$NAME")
fi

for t in "${targets[@]}"; do
  if [ -d "$t/.git" ]; then
    say "→ 更新 $t"
    git -C "$t" pull --ff-only --quiet
  elif [ -e "$t" ]; then
    say "⚠ $t 已经存在、但不是从这个仓库装的，没有动它。想重装就先把它挪走。"
  else
    say "→ 安装到 $t"
    mkdir -p "$(dirname "$t")"
    git clone --quiet --depth 1 "$REPO" "$t"
  fi
done

say "→ 准备 Python 环境 $VENV（第一次要下载几分钟）"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet --upgrade pymupdf playwright
"$VENV/bin/python" -m playwright install chromium >/dev/null

say "→ 试排一份范例报告"
first="${targets[0]}"
tmp="$(mktemp -d)"
out="$(bash "$first/run.sh" build "$first/references/示例-美的2024.json" "$tmp/nianbao测试.pdf" 2>&1 || true)"
rm -rf "$tmp"
if printf '%s' "$out" | grep -q "✓ 已生成"; then
  say "  ✓ 范例报告排出来了"
else
  say "✗ 范例报告没排出来，下面是报错："; printf '%s\n' "$out" | tail -20; exit 1
fi

say ""
say "✓ 装好了：${targets[*]}"
say "用法：新开一个对话，然后"
say "  Claude Code：输入 /nianbao，再把年报 PDF 拖进来"
say "  Codex：说「用 nianbao 读这份年报」，再给出年报 PDF 的路径"
say "年报全文去巨潮资讯网 cninfo.com.cn 下载（要全文，不要摘要）。"
