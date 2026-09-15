#!/usr/bin/env bash
# 一键起本地开发环境：后端 8000 + 前端 5173
#
# 用法：bash infra/scripts/dev.sh
# 停止：Ctrl-C（脚本会一并停掉两个子进程）

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "⚠️  没有找到 .env，正在从 .env.example 复制..."
  cp .env.example .env
  echo "👉 请先在 .env 里填好 API Key，然后重新运行本脚本。"
  exit 1
fi

pids=()
cleanup() {
  echo ""
  echo "正在停止开发服务..."
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> 同步后端依赖"
uv sync --all-extras

echo "==> 启动后端 (http://127.0.0.1:8000)"
(cd apps/backend && uv run uvicorn zhixun.main:app --reload --port 8000) &
pids+=($!)

echo "==> 启动前端 (http://localhost:5173)"
(cd apps/frontend && pnpm dev) &
pids+=($!)

echo ""
echo "✅ 已启动。API 文档：http://127.0.0.1:8000/docs"
echo "按 Ctrl-C 停止。"
wait
