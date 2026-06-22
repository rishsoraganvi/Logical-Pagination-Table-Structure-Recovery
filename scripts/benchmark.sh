#!/usr/bin/env bash
set -euo pipefail

PDF="${1:-docs/../doc_000.pdf}"
OUTPUT_FILE="${2:-benchmark.json}"
BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "=== Benchmarking pipeline performance ==="
START_TIME=$(date +%s.%N)

# Submit job
RESPONSE=$(curl -sf -X POST "$BASE_URL/pipeline/run" -F "file=@$PDF")
JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "Job ID: $JOB_ID"

# Poll until completion
while true; do
  STATUS=$(curl -sf "$BASE_URL/pipeline/status/$JOB_ID")
  STAGE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['stage'])")
  if [[ "$STAGE" == "done" || "$STAGE" == "failed" ]]; then
    break
  fi
  sleep 2
done

END_TIME=$(date +%s.%N)
WALL_TIME=$(echo "$END_TIME - $START_TIME" | bc)

# Get results
RESULT=$(curl -sf "$BASE_URL/pipeline/result/$JOB_ID")
DOC_COUNT=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(len(r['documents']))")
TABLE_COUNT=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(len(r['tables']))")

# Create benchmark output
cat > "$OUTPUT_FILE" << EOF
{
  "job_id": "$JOB_ID",
  "wall_clock_seconds": $WALL_TIME,
  "documents_recovered": $DOC_COUNT,
  "tables_recovered": $TABLE_COUNT,
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "pdf_file": "$PDF"
}
EOF

echo "Benchmark complete. Results saved to $OUTPUT_FILE"
cat "$OUTPUT_FILE" | python3 -m json.tool