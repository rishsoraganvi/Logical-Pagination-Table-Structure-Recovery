#!/usr/bin/env bash
set -euo pipefail

echo "=== Cleaning up job data ==="
JOB_DATA_DIR="./data/jobs"

if [ -d "$JOB_DATA_DIR" ]; then
  echo "Removing contents of $JOB_DATA_DIR"
  rm -rf "$JOB_DATA_DIR"/*
  echo "Cleanup complete"
else
  echo "Directory $JOB_DATA_DIR does not exist - nothing to clean up"
fi

# Also cleanup Models directory if needed (commented out as models are precious)
# MODEL_DIR="./models"
# if [ -d "$MODEL_DIR" ]; then
#   echo "Contents of $MODEL_DIR:"
#   du -sh "$MODEL_DIR"
# fi