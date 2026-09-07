#!/bin/sh
# AI Workbench 环境入口的薄壳：只负责在新机器上找到 python3 并转发参数。
# 默认只读（plan）。--apply / --check 切动词，其余参数原样传给 env.py。
#
#   sh tools/environment/bootstrap.sh --profile work-mac            # 预览
#   sh tools/environment/bootstrap.sh --profile work-mac --apply    # 应用
#   sh tools/environment/bootstrap.sh --profile work-mac --check    # 检查
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PY=""
for candidate in python3 /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY=$candidate
    break
  fi
done
if [ -z "$PY" ]; then
  echo "找不到 python3（env.py 只依赖标准库，Python 3.9 即可）" >&2
  exit 1
fi

VERB=plan
ARGS=""
for arg in "$@"; do
  case "$arg" in
    --apply) VERB=apply ;;
    --check) VERB=check ;;
    # lazy: 参数原样拼接后交给 shell 拆词，够用 —— profile 名与组件 id 都不含空格。
    *) ARGS="$ARGS $arg" ;;
  esac
done

# shellcheck disable=SC2086
exec "$PY" "$HERE/env.py" "$VERB" $ARGS
