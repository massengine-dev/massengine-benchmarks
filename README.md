# MassEngine Reproducible Benchmarks (`massengine-benchmarks`)

Reproducible benchmark plugins, automated runner scripts, and unmodified raw JSON telemetry for [MassEngine](https://massengine.com) (`v0.11.3`).

- **Interactive Live 20M Wikipedia Demo (Zero Signup)**: [https://massengine.com/demo](https://massengine.com/demo)
- **ES 9.5.6 & OpenSearch 3.9 FAISS (`Cohere-10M`) 3-Way Report**: [https://massengine.com/benchmarks-es-faiss](https://massengine.com/benchmarks-es-faiss)
- **Full Cohere-10M & 144.1M AWS EC2 Report**: [https://massengine.com/benchmarks-144m](https://massengine.com/benchmarks-144m)
- **OpenSearch 3.9 (`Lucene 10.5.1`) Selectivity Study**: [https://massengine.com/benchmarks](https://massengine.com/benchmarks)

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

- **In-Memory (`16c64g`)**: `1 × m6id.4xlarge` (`16 vCPUs`, `64 GiB RAM`, local NVMe)
- **Direct NVMe Mode (`16c32g`)**: `1 × c6id.4xlarge` (`16 vCPUs`, `32 GiB RAM` — **half the RAM**, `--nvme-mode`)

| Official `VectorDBBench` Case | `16c64g` In-Memory (`m6id.4xlarge`) | `16c32g` Direct NVMe (`c6id.4xlarge`) | Serial Latency (`p99` / `p95`) | `Recall@100` | 10M Load + Index Time |
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

## 3. Reproducing `Cohere-10M` (`VectorDBBench`) in Your Own VPC

### Step 0: Get a Multi-Core Evaluation License Key
MassEngine includes a **1-Core Free Forever** tier (`≤ 1M` vectors) out of the box, and pins OS CPU affinity to the licensed vCPU count:
- **Self-Serve 8-Core Multi-Node Trial (21 Days, No Credit Card)**: Sign up at [https://massengine.com/console](https://massengine.com/console), click **+ Add New License**, and enter promo code **`ME-EVAL-LAUNCH-21-DAYS`** (ideal for `1 × c6id.2xlarge` or `2 × c6id.xlarge`).
- **16+ Core `VectorDBBench` Reproduction (`m6id.4xlarge` / `c6id.4xlarge`)**: Email `eng@massengine.com` from your work address to receive a complimentary 16-core or 64-core benchmark key so all 16 vCPUs are unlocked.

### Step 1: Start MassEngine on the Database Host (`m6id.4xlarge` or `c6id.4xlarge`)
```bash
git clone https://github.com/massengine-dev/massengine-benchmarks.git
cd massengine-benchmarks

# Set NVME_MODE=true for c6id.4xlarge (32 GiB RAM) or NVME_MODE=false for m6id.4xlarge (64 GiB RAM)
MASSENGINE_LICENSE_KEY="meli_your_eval_key" \
MASSENGINE_API_KEY="change-me-bench-token" \
NVME_MODE=true \
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

## License

Apache License 2.0 — see [LICENSE](./LICENSE).
