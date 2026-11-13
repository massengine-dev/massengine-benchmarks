# MassEngine Reproducible Benchmarks (`massengine-benchmarks`)

Reproducible benchmark plugins, automated runner scripts, and unmodified raw JSON telemetry for [MassEngine](https://massengine.com) (`v0.9.19`).

- **Interactive Live 20M Wikipedia Demo (Zero Signup)**: [https://massengine.com/demo](https://massengine.com/demo)
- **Full Cohere-10M & 144.1M AWS EC2 Report**: [https://massengine.com/benchmarks-144m](https://massengine.com/benchmarks-144m)
- **OpenSearch 3.9 (`Lucene 10.5.1`) Head-to-Head Report**: [https://massengine.com/benchmarks](https://massengine.com/benchmarks)

---

## 1. Official Zilliz `VectorDBBench` (`Cohere-10M`, `10,000,000 × 768-d`, `COSINE`, `RF=1`)

Executed with unmodified upstream [`zilliztech/VectorDBBench`](https://github.com/zilliztech/VectorDBBench) (`install_massengine_plugin.py` verifies via `git status --porcelain` that zero upstream runner, dataset, or metric files are modified) against a single 16-vCPU AWS EC2 node (`8` local shards, `RF=1`, `us-east-1`):

- **In-Memory (`16c64g`)**: `1 × m6id.4xlarge` (`16 vCPUs`, `64 GiB RAM`, local NVMe)
- **Direct NVMe Mode (`16c32g`)**: `1 × c6id.4xlarge` (`16 vCPUs`, `32 GiB RAM` — **half the RAM**, `--nvme-mode`)

| Official `VectorDBBench` Case | `16c64g` In-Memory (`m6id.4xlarge`) | `16c32g` Direct NVMe (`c6id.4xlarge`) | Serial Latency (`p99` / `p95`) | `Recall@100` | 10M Load + Index Time |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`Performance768D10M`** (Unfiltered) | **`441.6 QPS`** | **`452.2 QPS`** | `6.20 ms` / `5.70 ms` (NVMe)<br>`6.30 ms` / `5.80 ms` (RAM) | `0.9833` | **`667.9s` (`11.1m` RAM)**<br>**`680.5s` (`11.3m` NVMe)** |
| **`Performance768D10M1P`** (Int Filter 1% • 99% Match) | **`313.4 QPS`** | **`320.9 QPS`** | `8.30 ms` / `7.80 ms` (RAM)<br>`8.40 ms` / `7.80 ms` (NVMe) | `0.9836` | Reused 10M index |
| **`Performance768D10M99P`** (Int Filter 99% • 1% Match) | **`1,122.8 QPS`** | **`1,133.0 QPS`** | **`3.20 ms` / `3.10 ms`** | `0.9582` | Reused 10M index |
| **`LabelFilterPerformanceCase`** (1.0% Scalar Label) | **`504.2 QPS`** | **`511.2 QPS`** | **`5.60 ms` / `5.30 ms`** | `0.9653` | **`668.2s` (`11.1m` NVMe)**<br>**`676.4s` (`11.3m` RAM)** |
| **`StreamingPerformanceCase`** (100K @ `1,000 writes/s`) | **`1,668.6 QPS` (live)**<br>**`4,708.0 QPS` (post)** | **`1,797.1 QPS` (live)**<br>**`4,463.2 QPS` (post)** | `2.20 ms` live / `1.60 ms` post (RAM)<br>`2.40 ms` live / `1.80 ms` post (NVMe) | `0.9854` (live)<br>`0.9841` (post) | `0.90s` optimize |

Raw unmodified `VectorDBBench` output JSONs: [`results/vectordbbench-cohere-10m/v0.9.19/`](./results/vectordbbench-cohere-10m/v0.9.19/).

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
