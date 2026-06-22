#!/usr/bin/env bash
set -euo pipefail

PDF="${1:-docs/../doc_000.pdf}"
BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "=== Health check ==="
curl -sf "$BASE_URL/health" | python3 -m json.tool

echo ""
echo "=== Submitting $PDF ==="
RESPONSE=$(curl -sf -X POST "$BASE_URL/pipeline/run" -F "file=@$PDF")
echo "$RESPONSE" | python3 -m json.tool
JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

echo ""
echo "=== Polling status for job $JOB_ID ==="
while true; do
  STATUS=$(curl -sf "$BASE_URL/pipeline/status/$JOB_ID")
  STAGE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['stage'])")
  echo "Stage: $STAGE"
  if [[ "$STAGE" == "done" || "$STAGE" == "failed" ]]; then
    break
  fi
  sleep 3
done

echo ""
echo "=== Result summary ==="
RESULT=$(curl -sf "$BASE_URL/pipeline/result/$JOB_ID")
DOC_COUNT=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(len(r['documents']))")
TABLE_COUNT=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(len(r['tables']))")
WALL=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['metrics']['wall_clock_seconds'])")

echo "Documents recovered : $DOC_COUNT"
echo "Tables recovered    : $TABLE_COUNT"
echo "Wall clock (s)      : $WALL"