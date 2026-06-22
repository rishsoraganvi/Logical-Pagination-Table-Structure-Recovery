#!/usr/bin/env bash
set -euo pipefail

echo "=== Pulling Ollama models ==="
docker exec ollama ollama pull llama3.2:3b
docker exec ollama ollama pull qwen2-vl:7b

echo "=== Pre-downloading TATR model ==="
docker exec tatr-worker python -c "
from transformers import AutoModelForObjectDetection, AutoFeatureExtractor
import os
cache = os.environ.get('TATR_MODEL_CACHE', '/models/tatr')
AutoFeatureExtractor.from_pretrained('microsoft/table-transformer-structure-recognition', cache_dir=cache)
AutoModelForObjectDetection.from_pretrained('microsoft/table-transformer-structure-recognition', cache_dir=cache)
print('TATR model ready.')
"

echo "=== All models ready ==="