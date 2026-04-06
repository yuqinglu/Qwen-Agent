#!/usr/bin/env bash
# 阶段 2：不启动任何服务，仅检查 Gateway / 适配层 / ty-mem 是否可达。
# 用法（在仓库任意目录均可，建议）：
#   cd openclaw_adapter
#   GATEWAY_TOKEN=xxx ADAPTER_API_KEY=yyy GATEWAY_PORT=18789 ADAPTER_PORT=10083 TYMEM_PORT=10081 bash scripts/phase2_verify.sh

set -euo pipefail

GATEWAY_PORT="${GATEWAY_PORT:-18789}"
ADAPTER_PORT="${ADAPTER_PORT:-8090}"
TYMEM_PORT="${TYMEM_PORT:-10081}"

die() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "OK   $*"; }

[[ -n "${GATEWAY_TOKEN:-}" ]] || die "请设置环境变量 GATEWAY_TOKEN（与 ADAPTER_GATEWAY_HTTP_TOKEN / OpenClaw gateway.auth 一致）"
[[ -n "${ADAPTER_API_KEY:-}" ]] || die "请设置环境变量 ADAPTER_API_KEY（与 ADAPTER_API_KEY / ty-mem OPENCLAW_API_KEY 对齐适配层）"

echo "=== Phase2 verify (ports: gateway=${GATEWAY_PORT} adapter=${ADAPTER_PORT} ty-mem=${TYMEM_PORT}) ==="

# 1) Gateway: Tools Invoke — 开源默认为 tool=cron + action=list（非 cron.list）
resp="$(curl -sS -w "\n%{http_code}" "http://127.0.0.1:${GATEWAY_PORT}/tools/invoke" \
  -H "Authorization: Bearer ${GATEWAY_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"tool":"cron","action":"list"}')"
code="$(echo "$resp" | tail -n1)"
body="$(echo "$resp" | sed '$d')"
[[ "$code" == "200" ]] || die "Gateway /tools/invoke HTTP ${code} body=${body:0:200}"
echo "$body" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' || die "Gateway response ok!=true: ${body:0:300}"
ok "Gateway POST /tools/invoke (cron + action=list)"

# 2) Adapter health
OA_PREFIX="/openclaw-adapter"
code="$(curl -sS -o /tmp/oa_health.json -w "%{http_code}" "http://127.0.0.1:${ADAPTER_PORT}${OA_PREFIX}/health")"
[[ "$code" == "200" ]] || die "Adapter ${OA_PREFIX}/health HTTP ${code}"
grep -qi 'ok' /tmp/oa_health.json || die "Adapter ${OA_PREFIX}/health body unexpected: $(cat /tmp/oa_health.json)"
ok "Adapter GET ${OA_PREFIX}/health"

# 3) ty-mem health（仅校验 HTTP 200，正文格式因版本可能不同）
code="$(curl -sS -o /tmp/ty_health.txt -w "%{http_code}" "http://127.0.0.1:${TYMEM_PORT}/health")"
[[ "$code" == "200" ]] || die "ty-mem /health HTTP ${code} body=$(head -c 200 /tmp/ty_health.txt)"
ok "ty-mem GET /health"

echo "=== All checks passed ==="
