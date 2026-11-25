# MassEngine Reproducible Benchmarks (`massengine-benchmarks`)

Reproducible benchmark plugins, automated cluster installers, evaluation runners, and unmodified raw JSON telemetry for [MassEngine](https://massengine.com) (`v0.11.2`–`v0.11.9`).

- **5-Minute Technical Walkthrough Video (MassEngine vs. HNSW, ES 9.5, OS FAISS, Qdrant & Milvus)**: [https://www.youtube.com/watch?v=fnZiKAPpn-A](https://www.youtube.com/watch?v=fnZiKAPpn-A)
- **8-Core 21-Day Free Evaluation & Benchmark Guide**: [https://massengine.com/docs-eval](https://massengine.com/docs-eval)
- **Interactive Live 20M Wikipedia Demo (Zero Signup)**: [https://massengine.com/demo](https://massengine.com/demo)
- **ES 9.5.6 & OpenSearch 3.9 FAISS (`Cohere-10M`) 3-Way Report**: [https://massengine.com/benchmarks-es-faiss](https://massengine.com/benchmarks-es-faiss)
- **Full Cohere-10M & 144.1M AWS EC2 Report**: [https://massengine.com/benchmarks-144m](https://massengine.com/benchmarks-144m)
- **Multimodal & CLIP Visual Embeddings (`CLIP ViT-B/32` & `Deep-Image-96` 10M)**: [https://massengine.com/benchmarks-multimodal](https://massengine.com/benchmarks-multimodal)
- **OpenSearch 3.9 (`Lucene 10.5.1`) Selectivity Study**: [https://massengine.com/benchmarks](https://massengine.com/benchmarks)

---

## Quickstart: 8-Core 21-Day Free Evaluation Benchmark (`ME-EVAL-LAUNCH-21-DAYS`)

Redeem promo code **`ME-EVAL-LAUNCH-21-DAYS`** in [massengine.com/console](https://massengine.com/console) for a free 21-day, 8-core floating license key (`meli_...`), then benchmark either a **Single 8-vCPU Node** or a **2-Node × 4-vCPU HA Cluster (`RF=2`)** (see [massengine.com/docs-eval](https://massengine.com/docs-eval) for AWS CloudFormation, GCP Terraform, Docker Compose, and bare-metal walkthroughs):

### 1A. Option A — Single-Node 8-vCPU Setup (e.g., `c6id.2xlarge` / `m6id.2xlarge` / `c3d-standard-8`)
```bash
git clone https://github.com/massengine-dev/massengine-benchmarks.git
cd massengine-benchmarks

MASSENGINE_LICENSE_KEY="meli_your_8core_eval_key" \
MASSENGINE_API_KEY="meadm_change_me_bench_token" \
DIM=1024 DATA_DIR=/var/lib/massengine \
./vectordbbench/install_server_node.sh
```

### 1B. Option B — 2-Node HA Setup (`2 × 4 vCPU` = 8 Cores, `RF=2` + Free Coordinator)
```bash
NODE_SECRET="$(openssl rand -hex 32)"

# On Data Node 0 (10.0.0.11, 4 vCPUs):
ROLE=node NODE_ID=0 NODES=2 RF=2 DIM=1024 NODE_SECRET="${NODE_SECRET}" \
MASSENGINE_LICENSE_KEY="meli_your_8core_eval_key" \
./vectordbbench/install_server_node.sh

# On Data Node 1 (10.0.0.12, 4 vCPUs):
ROLE=node NODE_ID=1 NODES=2 RF=2 DIM=1024 NODE_SECRET="${NODE_SECRET}" \
MASSENGINE_LICENSE_KEY="meli_your_8core_eval_key" \
./vectordbbench/install_server_node.sh

# On Stateless Coordinator Host (consumes 0 licensed cores):
ROLE=server NODES=2 RF=2 DIM=1024 NODE_SECRET="${NODE_SECRET}" \
NODE_ADDRS="10.0.0.11:9410,10.0.0.12:9410" \
MASSENGINE_LICENSE_KEY="meli_your_8core_eval_key" \
MASSENGINE_API_KEY="meadm_change_me_bench_token" \
./vectordbbench/install_server_node.sh
```

### 2. Run the Self-Contained 3-Minute Benchmark (+ Live HA Drain Test)
```bash
# Quick 100K-vector ingest, Recall@10, unfiltered / 1%-filtered / hybrid-BM25 sweep (+ HA drain check):
python3 ./eval-8core/bench_eval_cluster.py \
  --url http://127.0.0.1:8080 \
  --api-key "meadm_change_me_bench_token" \
  --vectors 100000 \
  --verify-ha-drain \
  --out eval_report_100k.json

# Or run official upstream VectorDBBench (Cohere-1M 768-d; restart with DIM=768 first):
MASSENGINE_URL="http://<GATEWAY_HOST>:8080" \
MASSENGINE_API_KEY="meadm_change_me_bench_token" \
./vectordbbench/run_cohere_1m_8core.sh
```

---

## 0. AWS EC2 3-Way Head-to-Head (`Cohere-10M`: MassEngine `v0.11.3` vs. Elasticsearch `9.5.6` vs. OpenSearch `3.9.0` + FAISS)

11 dedicated single-node AWS EC2 evaluations (`c6id.4xlarge` `16c/32g` and `m6id.4xlarge` `16c/64g`, driven from `c6id.8xlarge` `32c/64g`) across all 7 official Zilliz `Cohere-10M` (`10,000,000 × 768-d`) exact ground-truth sets:

| Tier & Configuration | Build + Optimize (`1` seg/shard) | Process RSS | NVMe Disk | Live Write `p99` (`1K/s`) | Live `1%` Filtered QPS (`p95`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`16c32g` MassEngine `v0.11.3` (NVMe)** | **`2.0 min`** (`82,690/s`) | **`1.53 GiB` heap** (`12.36 GiB` mapped) | **`11.85 GiB`** | **`40.0 ms`** | **`3,844.4 QPS` (`6.61 ms`)** |
| **`16c32g` MassEngine `v0.11.3` (In-Mem)** | **`2.1 min`** (`79,032/s`) | `1.72 GiB` heap (`12.55 GiB` mapped) | **`11.92 GiB`** | **`37.2 ms`** | **`4,015.7 QPS` (`6.21 ms`)** |
| `16c32g` ES `9.5.6` (`bbq_hnsw`) | `31.2 min` (`5,346/s`) | `11.35 GiB` | `30.58 GiB` | `88.4 ms` | `629.9 QPS` (`39.17 ms`) |
| `16c32g` ES `9.5.6` (`int8_hnsw`) | `52.3 min` (`3,189/s`) | `17.40 GiB` | `36.75 GiB` | `106.1 ms` | `867.4 QPS` (`29.97 ms`) |
| `16c32g` OS `3.9.0` (`faiss_on_disk` `32x`) | `50.0 min` (`3,336/s`) | `29.05 GiB` | `31.44 GiB` | `272.6 ms` | `162.2 QPS` (`147.48 ms`) |
| `16c32g` OS `3.9.0` (`faiss_fp16`, `mem_opt`) | `64.6 min` (`2,578/s`) | `12.93 GiB` | `44.70 GiB` | `225.7 ms` | `9.8 QPS` (`2,051.81 ms`) |
| **`16c64g` MassEngine `v0.11.3` (In-Mem)** | **`2.6 min`** (`64,764/s`) | **`1.72 GiB` heap** (`12.55 GiB` mapped) | **`11.90 GiB`** | **`40.3 ms`** | **`3,544.7 QPS` (`7.14 ms`)** |
| `16c64g` ES `9.5.6` (`bbq_hnsw`) | `32.5 min` (`5,127/s`) | `19.89 GiB` | `30.58 GiB` | `91.5 ms` | `570.3 QPS` (`42.42 ms`) |
| `16c64g` ES `9.5.6` (`int8_hnsw`) | `48.8 min` (`3,416/s`) | `26.21 GiB` | `36.75 GiB` | `99.9 ms` | `840.0 QPS` (`30.21 ms`) |
| `16c64g` OS `3.9.0` (`faiss_on_disk` `32x`) | `39.5 min` (`4,214/s`) | `48.41 GiB` | `31.44 GiB` | `277.7 ms` | `162.2 QPS` (`150.55 ms`) |
| `16c64g` OS `3.9.0` (`faiss_fp16`, Full In-RAM) | `67.2 min` (`2,480/s`) | `38.96 GiB` | `44.70 GiB` | `262.4 ms` | `933.1 QPS` (`34.60 ms`) |

- Reproducible 4-phase driver & dataset stager: [`es-opensearch-10m/`](./es-opensearch-10m/)
- All 11 raw JSON telemetry files & auto-generated summary tables: [`results/cohere-10m-es-os-faiss/`](./results/cohere-10m-es-os-faiss/) ([`SUMMARY.md`](./results/cohere-10m-es-os-faiss/SUMMARY.md))

---

## 1. Official Zilliz `VectorDBBench` (`Cohere-10M`, `10,000,000 × 768-d`, `COSINE`, `RF=1`, `v0.11.2`)

Executed with unmodified upstream [`zilliztech/VectorDBBench`](https://github.com/zilliztech/VectorDBBench) (`install_massengine_plugin.py` verifies via `git status --porcelain` that zero upstream runner, dataset, or metric files are modified) against a single 16-vCPU AWS EC2 node (`8` local shards, `RF=1`, `us-east-1`):

- **Full-RAM Node (`16c64g`)**: `1 × m6id.4xlarge` (`16 vCPUs`, `64 GiB RAM`, local NVMe)
- **Lean-RAM Node (`16c32g`)**: `1 × c6id.4xlarge` (`16 vCPUs`, `32 GiB RAM` — **half the RAM**, unified adaptive storage)

| Official `VectorDBBench` Case | `16c64g` Full-RAM (`m6id.4xlarge`) | `16c32g` Lean-RAM (`c6id.4xlarge`) | Serial Latency (`p99` / `p95`) | `Recall@100` | 10M Load + Index Time |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`Performance768D10M`** (Unfiltered) | **`378.6 QPS`** | **`403.7 QPS`** | `5.20 ms` / `4.80 ms` (NVMe)<br>`6.30 ms` / `5.80 ms` (RAM) | `0.9837` (NVMe)<br>`0.9840` (RAM) | **`645.7s` (`10.8m` RAM)**<br>**`646.8s` (`10.8m` NVMe)** |
| **`Performance768D10M1P`** (Int Filter 1% • 99% Match) | **`292.3 QPS`** | **`309.4 QPS`** | `6.20 ms` / `5.90 ms` (NVMe)<br>`7.10 ms` / `6.70 ms` (RAM) | `0.9839` (NVMe)<br>`0.9842` (RAM) | Reused 10M index |
| **`Performance768D10M99P`** (Int Filter 99% • 1% Match) | **`1,557.9 QPS`** | **`1,656.5 QPS`** | **`2.00 ms` / `1.80 ms` (NVMe)**<br>**`2.00 ms` / `1.90 ms` (RAM)** | `0.9639` (NVMe)<br>`0.9668` (RAM) | Reused 10M index |
| **`LabelFilterPerformanceCase`** (1.0% Scalar Label) | **`3,790.2 QPS`** | **`3,755.3 QPS`** | **`1.50 ms` / `1.40 ms` (RAM)**<br>**`1.60 ms` / `1.50 ms` (NVMe)** | `0.9712` (RAM)<br>`0.9714` (NVMe) | **`663.6s` (`11.1m` NVMe)**<br>**`663.9s` (`11.1m` RAM)** |
| **`StreamingPerformanceCase`** (100K @ `1,000 writes/s`) | **`1,679.0 QPS` (live)**<br>**`5,214.5 QPS` (post)** | **`1,706.3 QPS` (live)**<br>**`4,969.0 QPS` (post)** | `2.30 ms` live / `1.50 ms` post (NVMe)<br>`2.50 ms` live / `1.40 ms` post (RAM) | `0.9852–0.9853` (live)<br>`0.9839–0.9842` (post) | `0.80s–0.91s` optimize |

Raw unmodified `VectorDBBench` output JSONs: [`results/vectordbbench-cohere-10m/v0.11.2/`](./results/vectordbbench-cohere-10m/v0.11.2/) (archived `v0.9.19`: [`results/vectordbbench-cohere-10m/v0.9.19/`](./results/vectordbbench-cohere-10m/v0.9.19/)).

---

## 2. 144.1M Multilingual Wikipedia AWS Scale Benchmark (`1024-d`, `RF=2`)

Full 21-language [`Upstash/wikipedia-2024-06-bge-m3`](https://huggingface.co/datasets/Upstash/wikipedia-2024-06-bge-m3) corpus (`144,137,311` unique `1024-d` vectors • `288,274,622` total replicated vectors across `16` shards at `RF=2` • `1.18 TB` raw float32):

| AWS EC2 Topology | Total vCPUs & RAM | Measured Cluster RSS | Total Load + Index Time | Filtered Search (`1.42%` / `2.05M` Matches) | AWS On-Demand (`us-east-1`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 1 In-Memory (`4 × r6id.8xlarge`)** | `128 vCPUs` • `1,024 GiB` | `510.14 GiB` (`127.5 GiB/node`) | **`900.1s` (`15.0 min` • `160,129 docs/s`)** | **`3,937.8 QPS`** (`1.29 ms` p50 @ `c=1`, `R@10=0.9478`) | `$9.285 / hr` |
| **Tier 2 Direct NVMe (`4 × c6id.4xlarge`)** | `64 vCPUs` • `128 GiB` | **`62.73 GiB` (`15.7 GiB/node`)** | **`1,073.9s` (`17.9 min` • `134,219 docs/s`)** | **`2,114.6 QPS`** (`1.52 ms` p50 @ `c=1`, `R@10=0.9480`) | **`$2.851 / hr` (`$2,053/mo`)** |

Raw JSON telemetry reports: [`results/wikipedia-144m-aws/`](./results/wikipedia-144m-aws/).

---

## 3. Multimodal & Visual Embeddings (`CLIP ViT-B/32` In-Dist / OOD & `Deep-Image-96` 10M)

Evaluated with automatic zero-tuning vector partitioning across 1.28M ImageNet CLIP (`512-d`), 1.00M out-of-distribution text-to-image LAION-400M CLIP (`512-d`), and 9.99M `deep-image-96-angular` CNN descriptors (`96-d`), holding 10M vectors in **`0.877 GiB` RSS (`3.03 GiB` disk)** at `int8`:

| Dataset (`N × Dim`) | Precision | Effective Load Rate | Process RSS / Disk | Unfiltered `Recall@10` (`p50`) | `1%` Filtered `Recall@10` / Peak QPS |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`imagenet-clip-512`** (`1.28M × 512-d`) | `int8` / `float16` | `110,967/s` / `88,800/s` | `0.27 GiB` / `1.31–1.92 GiB` | `0.9829` / **`0.9957`** (`0.46 ms`) | `0.9910` / **`32,324 QPS`** (`0.28 ms` p50) |
| **`laion-clip-512` (Text→Image OOD)** (`1.00M × 512-d`) | `int8` / `float16` | `120,038/s` / `102,265/s` | `0.26 GiB` / `1.28–1.76 GiB` | `0.9821` / **`0.9967`** (`0.48–3.4 ms`) | `0.9782` / **`33,494 QPS`** (`0.28 ms` p50) |
| **`deep-image-96-angular`** (`9.99M × 96-d`) | `int8` / `float16` | `192,582/s` (`51.9s`) | **`0.88 GiB`** / `3.03–4.22 GiB` | `0.9729` / **`0.9984`** (`0.52–1.5 ms`) | `0.9857` / **`23,377 QPS`** (`0.36 ms` p50) |

- Reproduction scripts: [`multimodal-image/stage_hdf5.py`](./multimodal-image/stage_hdf5.py) & [`multimodal-image/bench_multimodal_http.py`](./multimodal-image/bench_multimodal_http.py)
- Unmodified raw JSON results: [`results/multimodal-image/`](./results/multimodal-image/)

---

## 4. Reproducing `Cohere-10M` (`VectorDBBench`) in Your Own VPC

### Step 0: Get a Multi-Core Evaluation License Key
MassEngine includes a **1-Core Free Forever** tier (`≤ 1M` vectors) out of the box, and pins OS CPU affinity to the licensed vCPU count:
- **Self-Serve 8-Core Multi-Node Trial (21 Days, No Credit Card)**: Sign up at [https://massengine.com/console](https://massengine.com/console), click **+ Add New License**, and enter promo code **`ME-EVAL-LAUNCH-21-DAYS`** (ideal for `1 × c6id.2xlarge` or `2 × c6id.xlarge`).
- **16+ Core `VectorDBBench` Reproduction (`m6id.4xlarge` / `c6id.4xlarge`)**: Email `eng@massengine.com` from your work address to receive a complimentary 16-core or 64-core benchmark key so all 16 vCPUs are unlocked.

### Step 1: Start MassEngine on the Database Host (`m6id.4xlarge` or `c6id.4xlarge`)
```bash
git clone https://github.com/massengine-dev/massengine-benchmarks.git
cd massengine-benchmarks

# Identical flags run on both 64 GiB m6id.4xlarge and 32 GiB c6id.4xlarge
# (MassEngine auto-adapts RAM/NVMe residency and GOMEMLIMIT to host RAM)
MASSENGINE_LICENSE_KEY="meli_your_eval_key" \
MASSENGINE_API_KEY="change-me-bench-token" \
DATA_DIR=/mnt/nvme/massengine \
./vectordbbench/install_server_node.sh
```

### Step 2: Run Unmodified `zilliztech/VectorDBBench` from the Driver Host
Run from a separate driver instance in the same VPC/AZ (recommended so Python Parquet/Arrow readers do not contend for CPU cores with the database under test):
```bash
git clone https://github.com/massengine-dev/massengine-benchmarks.git
cd massengine-benchmarks

MASSENGINE_URL="http://<DB_PRIVATE_IP>:8080" \
MASSENGINE_API_KEY="change-me-bench-token" \
DB_LABEL="16c32g-nvme-c6id.4xlarge" \
./vectordbbench/run_cohere_10m.sh
```
*(For an 8-core evaluation cluster, run `./vectordbbench/run_cohere_1m_8core.sh` or pass `LOAD_CONCURRENCY=8 CONCURRENCY_LIST=1,4,8,16,32` to `run_cohere_10m.sh`.)*

## License

Apache License 2.0 — see [LICENSE](./LICENSE).
