# Runbook: Deploying the Pipeline to Vultr (NVIDIA A16)

**Companion to:** `prd.md`
**Goal:** take the Docker-Compose stack Claude Code finishes building on your local
machine and get it running on a Vultr Cloud GPU (A16) instance for the live demo / full
2,000-page run.

This assumes the local build already produces: a `docker-compose.yml` with the
GPU-bound services (OCR, TATR, LLM/VLM) separated from the CPU-bound services
(fingerprinting, stitching, validation, FastAPI app) — same split as SENTINEL v2-HX.

---

## 0. Before you provision anything

- [ ] Vultr account with billing enabled and a payment method on file (GPU plans aren't
      always available on a brand-new/unverified account — if you've never spun up a GPU
      instance on Vultr before, check this a day or two before the demo, not the night
      before).
- [ ] An SSH key added to your Vultr account (Account → SSH Keys), so it can be injected
      at instance creation instead of emailing you a root password.
- [ ] Local repo pushed to GitHub (private repo is fine) — this is the simplest way to
      get code onto the instance.
- [ ] `docker-compose.yml` already tested locally — even on the Quadro T1000, a CPU-only
      or reduced-batch run is enough to confirm the containers build and start cleanly
      before you pay for GPU time to debug Docker issues.

---

## 1. Provision the A16 instance

**Option A — Console (fastest for a one-off hackathon box):**
1. Vultr Console → Products → Compute → Deploy Instance.
2. Choose **Cloud GPU**, then select **NVIDIA A16** as the GPU type.
3. Pick a plan sized to one GPU slice (16GB VRAM) — that's enough for this pipeline; you
   don't need multiple slices.
4. Pick a region close to you for lower upload/SSH latency (closest options to
   Bengaluru are typically the Mumbai or Singapore regions — check availability, A16
   capacity is regional and not guaranteed everywhere).
5. Under "Configure Software," choose an **Operating System** image with GPU drivers
   pre-installed (Vultr's GPU-enabled OS images ship with NVIDIA drivers already on
   them) — Ubuntu 22.04 is the safest choice for Docker + NVIDIA Container Toolkit
   compatibility.
6. Attach your SSH key, set a label/hostname, deploy.

**Option B — API/CLI (if you want it scriptable/reproducible):**
```bash
export VULTR_API_KEY="your_api_key"

# Find the right region, plan, and OS IDs first
curl "https://api.vultr.com/v2/regions" -H "Authorization: Bearer ${VULTR_API_KEY}"
curl "https://api.vultr.com/v2/plans-gpu" -H "Authorization: Bearer ${VULTR_API_KEY}"
curl "https://api.vultr.com/v2/os" -H "Authorization: Bearer ${VULTR_API_KEY}"

# Create the instance
curl "https://api.vultr.com/v2/instances" \
  -X POST \
  -H "Authorization: Bearer ${VULTR_API_KEY}" \
  -H "Content-Type: application/json" \
  --data '{
    "region": "bom",
    "plan": "<A16_PLAN_ID_FROM_ABOVE>",
    "os_id": <UBUNTU_22_04_OS_ID>,
    "label": "loan-doc-pipeline-a16",
    "hostname": "loan-doc-pipeline"
  }'
```
Or the equivalent with `vultr-cli instance create --region bom --plan <plan> --os <id> --label loan-doc-pipeline-a16`.
Note the `main_ip` in the response — that's what you SSH into.

---

## 2. First login: verify the GPU is actually visible

```bash
ssh root@<instance-ip>

# Driver-level check
nvidia-smi
# Should list one A16 GPU slice with ~16GB

# Install Docker + NVIDIA Container Toolkit if the image doesn't already have them
curl -fsSL https://get.docker.com | sh
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | apt-key add -
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list \
  | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt update && apt install -y nvidia-container-toolkit
systemctl restart docker

# Container-level check — this is the one that actually matters
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```
If that last command doesn't show the GPU, stop here and fix it before doing anything
else — every later step assumes container GPU passthrough works.

---

## 3. Get your code onto the instance

```bash
# On the Vultr box
apt install -y git
git clone https://github.com/<you>/<loan-doc-pipeline-repo>.git /opt/app
cd /opt/app

# Secrets/env vars: don't commit these — copy separately
scp .env root@<instance-ip>:/opt/app/.env
```
If the repo is private, use a GitHub deploy key or a fine-grained PAT rather than
pasting your personal credentials onto the box.

---

## 4. Run the stack

Your `docker-compose.yml` should already reserve the GPU only for the services that
need it:

```yaml
services:
  ocr-service:
    build: ./services/ocr-worker
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  table-structure-service:   # TATR
    build: ./services/tatr-worker
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  llm-service:               # Ollama: 3B labeler + escalation VLM
    image: ollama/ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  api:                       # FastAPI orchestrator — CPU only
    build: ./services/api
    depends_on: [ocr-service, table-structure-service, llm-service]
    # No direct port exposure - only accessible via nginx

  nginx:                     # Reverse proxy with auth and IP restriction
    build: ./nginx
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 0   # No GPU needed for nginx
```
**Note:** The nginx service has been added to handle authentication and IP restriction.

```bash
docker compose build
docker compose up -d
docker compose ps          # confirm everything is healthy
docker compose logs -f nginx   # check nginx is running
docker compose logs -f ocr-worker   # spot-check GPU services are actually using the GPU
```

---

## 5. Enable Basic Authentication and IP Restriction

### 5.1 Create the password file
The nginx service uses basic authentication. You need to create a `.htpasswd` file:

```bash
# Option 1: Use htpasswd utility (if available on host)
# Install apache2-utils if needed: apt install -y apache2-utils
htpasswd -c /opt/app/nginx/.htpasswd your_username
# You will be prompted to enter and confirm the password

# Option 2: Generate using openssl (if htpasswd not available)
# First create the password hash
echo -n "your_username:$(openssl passwd -apr1)" >> /opt/app/nginx/.htpasswd
# Then enter your password when prompted

# Option 3: Use Python one-liner
python3 -c "
import crypt, getpass, pwd
username = input('Username: ')
password = getpass.getpass('Password: ')
hash = crypt.crypt(password, '\$6\$rounds=5000${\"usesomesaltforsillydemo\"}$')
print(f'{username}:{hash}')
" >> /opt/app/nginx/.htpasswd
```

### 5.2 Configure IP restriction
Edit `/opt/app/nginx/nginx.conf` and uncomment/modify the IP restriction lines:

```nginx
# IP restriction - replace with your IP or CIDR
# Example: allow 203.0.113.0/24; deny all;
# Replace 203.0.113.0/24 with your IP address or range

allow 203.0.113.0/24;  # <-- CHANGE THIS TO YOUR IP/RANGE
deny all;
```

**To find your IP address:** Visit https://whatismyipaddress.com from your network

**Examples:**
- Single IP: `allow 203.0.113.25; deny all;`
- IP range: `allow 203.0.113.0/24; deny all;`
- Multiple IPs: 
  ```
  allow 203.0.113.25;
  allow 198.51.100.10;
  deny all;
  ```

### 5.3 Restart nginx to apply changes
```bash
docker compose restart nginx
```

### 5.4 Verify the setup
- Visit http://<instance-ip> in your browser
- You should see a login prompt for basic auth
- After entering credentials, you should see the loan document upload interface
- If accessing from an IP not in the allow list, you should see a 403 Forbidden error

---

## 6. Get to the demo UI without exposing the box publicly

For a hackathon demo you don't need the API port open to the world — an SSH tunnel is
simpler and safer than configuring a Vultr Cloud Firewall rule:

```bash
# Run on your laptop
ssh -L 8000:localhost:8000 root@<instance-ip>
# Now http://localhost:8000 on your laptop hits the nginx reverse proxy on the A16 box
```
You'll first see the basic auth login prompt, then the loan document upload interface.

If you do want it reachable directly (e.g. a teammate needs access), add a Cloud
Firewall rule scoped to specific IPs rather than `0.0.0.0/0`.

---

## 7. Run the real test: full sample + the 2,000-page projection

```bash
scp doc_000.pdf root@<instance-ip>:/opt/app/data/
ssh root@<instance-ip> "cd /opt/app && docker compose exec api python run_pipeline.py --input data/doc_000.pdf"
```
Capture wall-clock time and `nvidia-smi`/`docker stats` GPU utilization during the run —
these are exactly the numbers Section 8 of `prd.md` flags as "to be replaced with
measured numbers." Multiply per-page timing out to 2,000 pages for the write-up's cost
projection.

---

## 8. Cost control

A16 instances bill **per GPU-hour whether or not you're actively running the pipeline**.
For a hackathon budget:
- Stop (don't just leave idle) the instance between work sessions: `vurtr-cli instance stop <id>` or via Console.
- Take a snapshot before stopping/destroying if you want to redeploy quickly right
  before the live demo without redoing Steps 1–4.
- Destroy the instance after the hackathon submission window closes.

---

## 9. Quick checklist

| Step | Done when… |
|------|------------|
| Instance provisioned | `nvidia-smi` over SSH shows the A16 |
| Container GPU passthrough | `docker run --gpus all ... nvidia-smi` works |
| Code deployed | `docker compose ps` shows all services healthy |
| Nginx running | `docker compose logs nginx` shows nginx is ready |
| Auth working | Visiting http://<instance-ip> prompts for credentials |
| IP restriction working | Access from non-allowed IP shows 403 Forbidden |
| Tunnel/access working | `localhost:8000` loads from your laptop after auth |
| Full sample run completed | timing + GPU utilization numbers captured for `prd.md` §8 |
| Cost controlled | instance stopped/snapshotted when not in active use |

---