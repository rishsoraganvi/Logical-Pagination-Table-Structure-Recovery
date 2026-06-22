# EnvSetup.md — Environment Setup

**Project:** Loan Document IDP Pipeline

Two environments: **local dev** (Dell Precision 5550, Quadro T1000, 4GB VRAM, Windows +
WSL2 or Ubuntu) and **production/demo** (Vultr A16, 16GB VRAM, Ubuntu 22.04).

---

## 1. `.env` File

Copy `.env.example` to `.env` and fill in all values before running.

```bash
# .env

# --- Job storage ---
DATA_DIR=/data/jobs                        # Inside Docker; maps to ./data/jobs on host
MAX_UPLOAD_MB=500

# --- OCR worker ---
OCR_WORKER_URL=http://ocr-worker:8001
OCR_BATCH_SIZE=16
OCR_TIMEOUT_SECONDS=60

# --- TATR worker ---
TATR_WORKER_URL=http://tatr-worker:8002
TATR_TIMEOUT_SECONDS=30

# --- Ollama (LLM) ---
OLLAMA_BASE_URL=http://ollama:11434
LLM_MODEL=llama3.2:3b
VLM_MODEL=qwen2-vl:7b
LLM_TIMEOUT_SECONDS=60
VLM_ESCALATION_CAP=20                      # Rule R-24

# --- Fingerprinting ---
HEADER_ZONE_FRACTION=0.15
FOOTER_ZONE_FRACTION=0.15
NEAR_BLANK_INK_THRESHOLD=0.05              # Rule R-10
NATIVE_TEXT_CHAR_THRESHOLD=30             # Rule R-01

# --- Boundary detection ---
PELT_PENALTY=3.0                           # Rule R-12, tunable
SAME_TYPE_EMBED_SIMILARITY=0.90           # Threshold for same-type run grouping
BOUNDARY_SIMILARITY_THRESHOLD=0.45        # Minimum sim for non-boundary (below = boundary)

# --- Confidence ---
LOW_CONFIDENCE_THRESHOLD=0.70              # Rule R-40

# --- Redis ---
REDIS_URL=redis://redis:6379/0
JOB_TTL_SECONDS=86400                     # 24h before Redis key expires

# --- Rasterization ---
OCR_DPI=150                               # Rule R-02

# --- Sentence transformer ---
EMBED_MODEL=all-MiniLM-L6-v2
EMBED_MODEL_CACHE=/models/all-MiniLM-L6-v2

# --- TATR ---
TATR_MODEL=microsoft/table-transformer-structure-recognition
TATR_MODEL_CACHE=/models/tatr
```

---

## 2. `docker-compose.yml`

```yaml
version: "3.9"

networks:
  loan-net:
    driver: bridge

volumes:
  data:
    driver: local
  models:
    driver: local
  ollama-data:
    driver: local

services:

  redis:
    image: redis:7-alpine
    container_name: redis
    networks: [loan-net]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  ocr-worker:
    build:
      context: ./services/ocr-worker
      dockerfile: Dockerfile
    container_name: ocr-worker
    networks: [loan-net]
    volumes:
      - data:/data
    env_file: .env
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  tatr-worker:
    build:
      context: ./services/tatr-worker
      dockerfile: Dockerfile
    container_name: tatr-worker
    networks: [loan-net]
    volumes:
      - data:/data
      - models:/models:ro
    env_file: .env
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 60s       # TATR model load takes ~30s

  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    networks: [loan-net]
    volumes:
      - ollama-data:/root/.ollama
    env_file: .env
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 120s      # Model load time

  api:
    build:
      context: ./services/api
      dockerfile: Dockerfile
    container_name: api
    networks: [loan-net]
    ports:
      - "8000:8000"
    volumes:
      - data:/data
      - models:/models:ro
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy
      ocr-worker:
        condition: service_healthy
      tatr-worker:
        condition: service_healthy
      ollama:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5
```

---

## 3. `docker-compose.override.yml` (local dev only, gitignored)

```yaml
# Mounts source code directories for hot reload during development.
# On the Vultr box, do NOT use this file — run docker compose without override.

version: "3.9"

services:
  api:
    volumes:
      - ./services/api:/app:ro   # Mount source over container code
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

  ocr-worker:
    volumes:
      - ./services/ocr-worker:/app:ro
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

  tatr-worker:
    volumes:
      - ./services/tatr-worker:/app:ro
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
```

---

## 4. Dockerfiles

### `services/api/Dockerfile`

```dockerfile
FROM python:3.11-slim

# System deps for pdf2image (poppler) and OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download sentence-transformer model at build time
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### `services/ocr-worker/Dockerfile`

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# PaddleOCR GPU build — must match the CUDA version on the host (A16 = CUDA 12.x)
RUN pip install --no-cache-dir paddlepaddle-gpu==2.6.1 -f https://www.paddlepaddle.org.cn/whl/linux/mkl/avx/stable.html
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download PP-OCRv4 models at build time
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False)"

COPY . .

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
```

### `services/tatr-worker/Dockerfile`

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
```

---

## 5. `requirements.txt` Files

### `services/api/requirements.txt`

```
fastapi==0.111.1
uvicorn[standard]==0.30.1
pydantic==2.7.4
pydantic-settings==2.3.4
pypdf==4.2.0
pdfplumber==0.11.4
pdf2image==1.17.0
camelot-py[cv]==0.11.0
opencv-python-headless==4.9.0.80
sentence-transformers==3.0.1
numpy==1.26.4
scikit-learn==1.4.2
ruptures==1.1.9
httpx==0.27.0
redis==5.0.7
structlog==24.2.0
python-multipart==0.0.9
aiofiles==23.2.1
```

### `services/ocr-worker/requirements.txt`

```
fastapi==0.111.1
uvicorn[standard]==0.30.1
pydantic==2.7.4
paddleocr==2.7.3
opencv-python-headless==4.9.0.80
numpy==1.26.4
structlog==24.2.0
```

### `services/tatr-worker/requirements.txt`

```
fastapi==0.111.1
uvicorn[standard]==0.30.1
pydantic==2.7.4
transformers==4.41.2
torch==2.3.0
torchvision==0.18.0
Pillow==10.3.0
numpy==1.26.4
structlog==24.2.0
```

---

## 6. Model Pull Script

`scripts/pull_models.sh` — run once after `docker compose up -d` when deploying.

```bash
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
```

Make executable: `chmod +x scripts/pull_models.sh`

---

## 7. Local Dev Setup (Dell Precision 5550, Quadro T1000)

```bash
# 1. Install WSL2 Ubuntu 22.04 (if on Windows) or use native Ubuntu
# 2. Install Docker Desktop with WSL2 backend + NVIDIA GPU support
#    https://docs.docker.com/desktop/gpu/
# 3. Verify GPU passthrough
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi

# 4. Clone repo
git clone https://github.com/<you>/loan-doc-pipeline.git
cd loan-doc-pipeline

# 5. Set up environment
cp .env.example .env
# Edit .env — no changes needed for local dev; defaults work

# 6. Build and start (first build: ~10 min — downloads base images and pip installs)
docker compose build
docker compose up -d

# 7. Pull models (one-time, ~5GB total download)
bash scripts/pull_models.sh

# 8. Wait for all services to be healthy
docker compose ps    # all should show "healthy" after ~2 min

# 9. Smoke test
bash scripts/smoke_test.sh
```

**Local dev VRAM note:** The Quadro T1000 has only 4GB. PaddleOCR alone uses ~1.5GB.
The 3B Ollama model needs ~2GB. Running OCR and LLM simultaneously on the T1000 will
OOM. For local dev, run one service at a time by temporarily disabling GPU reservation
in `docker-compose.override.yml` for services not under test.

---

## 8. Vultr A16 Setup

Follow `vultr-deployment-runbook.md` for provisioning. After SSH into the instance:

```bash
# 1. Install Docker + NVIDIA Container Toolkit
curl -fsSL https://get.docker.com | sh
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | apt-key add -
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list \
  | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y nvidia-container-toolkit
systemctl restart docker

# 2. Verify GPU passthrough
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi

# 3. Clone repo
git clone https://github.com/<you>/loan-doc-pipeline.git /opt/app
cd /opt/app

# 4. Copy .env from local machine (do NOT commit secrets)
scp .env root@<instance-ip>:/opt/app/.env

# 5. Build (no override file on prod)
docker compose build
docker compose up -d

# 6. Pull models (~5GB — this takes a few minutes on Vultr; A16 instances have fast egress)
bash scripts/pull_models.sh

# 7. Verify health
docker compose ps
curl http://localhost:8000/health
# Expected: {"status": "ok", "gpu": true, "ollama": true}

# 8. SSH tunnel for demo access from local laptop
ssh -L 8000:localhost:8000 root@<instance-ip>
# Now http://localhost:8000 on your laptop hits the A16 box
```

---

## 9. Smoke Test Script

`scripts/smoke_test.sh`

```bash
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
```
