#!/usr/bin/env bash
# 统一入口：bash <skill 目录>/run.sh <folder|extract|check|build|pages> 参数...
# 自动挑 Python：用 install.sh 装过的 ~/.nianbao/venv 优先，没有就用系统的 python3。
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HOME/.nianbao/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
cmd="${1:-}"
if [ -z "$cmd" ] || [ ! -f "$DIR/scripts/$cmd.py" ]; then
  echo "用法：bash $DIR/run.sh <folder|extract|check|build|pages> 参数..."; exit 1
fi
shift
exec "$PY" "$DIR/scripts/$cmd.py" "$@"
