#!/usr/bin/env bash
# Runs the official 5-suite Zilliz VectorDBBench Cohere-10M (768-d, COSINE, RF=1)
# benchmark against a MassEngine endpoint using an unmodified upstream VectorDBBench clone.
#
# Usage:
#   MASSENGINE_URL="http://10.0.1.25:8080" \
#   MASSENGINE_API_KEY="bench-token-change-me" \
#   DB_LABEL="16c32g-nvme-c6id.4xlarge" \
#   ./vectordbbench/run_cohere_10m.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${WORK_DIR:-$(pwd)/.vdbbench-work}"
MASSENGINE_URL="${MASSENGINE_URL:-http://127.0.0.1:8080}"
DB_LABEL="${DB_LABEL:-massengine-16c}"
DB_VERSION="${DB_VERSION:-v0.11.8}"
NUM_SHARDS="${NUM_SHARDS:-8}"
RF="${RF:-1}"
LOAD_CONCURRENCY="${LOAD_CONCURRENCY:-16}"
CONCURRENCY_LIST="${CONCURRENCY_LIST:-1,5,10,20,30,40,60,80}"

if [[ -z "${MASSENGINE_API_KEY:-}" ]]; then
  echo "ERROR: MASSENGINE_API_KEY is required." >&2
  exit 1
fi

mkdir -p "${WORK_DIR}/datasets" "${WORK_DIR}/results"

if [[ ! -d "${WORK_DIR}/VectorDBBench/.git" ]]; then
  echo "=== Cloning official upstream zilliztech/VectorDBBench ==="
  git clone --depth 1 https://github.com/zilliztech/VectorDBBench.git "${WORK_DIR}/VectorDBBench"
fi

python3 "${SCRIPT_DIR}/install_massengine_plugin.py" --vdbbench-dir "${WORK_DIR}/VectorDBBench"

if [[ ! -x "${WORK_DIR}/venv/bin/vectordbbench" ]]; then
  echo "=== Setting up Python virtualenv for VectorDBBench ==="
  python3 -m venv "${WORK_DIR}/venv"
  "${WORK_DIR}/venv/bin/pip" install -q --upgrade pip
  "${WORK_DIR}/venv/bin/pip" install -q -e "${WORK_DIR}/VectorDBBench" urllib3 orjson
fi

export DATASET_LOCAL_DIR="${DATASET_LOCAL_DIR:-${WORK_DIR}/datasets}"
export RESULTS_LOCAL_DIR="${RESULTS_LOCAL_DIR:-${WORK_DIR}/results}"
VDB="${WORK_DIR}/venv/bin/vectordbbench"

echo "--- [1/5] Performance768D10M (Cohere 10M Unfiltered) ---"
"${VDB}" massengine \
  --case-type Performance768D10M \
  --db-label "${DB_LABEL}" \
  --db-version "${DB_VERSION}" \
  --url "${MASSENGINE_URL}" \
  --api-key "${MASSENGINE_API_KEY}" \
  --tenant vdbbench \
  --num-shards "${NUM_SHARDS}" \
  --rf "${RF}" \
  --data-type int8 \
  --nprobe 52 \
  --rerank-pool 384 \
  --insert-batch-size 4096 \
  --load-concurrency "${LOAD_CONCURRENCY}" \
  --concurrency-duration 30 \
  --num-concurrency "${CONCURRENCY_LIST}"

echo "--- [2/5] Performance768D10M1P (Cohere 10M 1% Int Filter, 99% Match) ---"
"${VDB}" massengine \
  --case-type Performance768D10M1P \
  --skip-load \
  --skip-drop-old \
  --db-label "${DB_LABEL}" \
  --db-version "${DB_VERSION}" \
  --url "${MASSENGINE_URL}" \
  --api-key "${MASSENGINE_API_KEY}" \
  --tenant vdbbench \
  --num-shards "${NUM_SHARDS}" \
  --rf "${RF}" \
  --data-type int8 \
  --nprobe 60 \
  --rerank-pool 384 \
  --concurrency-duration 30 \
  --num-concurrency "${CONCURRENCY_LIST}"

echo "--- [3/5] Performance768D10M99P (Cohere 10M 99% Int Filter, 1% Match) ---"
"${VDB}" massengine \
  --case-type Performance768D10M99P \
  --skip-load \
  --skip-drop-old \
  --db-label "${DB_LABEL}" \
  --db-version "${DB_VERSION}" \
  --url "${MASSENGINE_URL}" \
  --api-key "${MASSENGINE_API_KEY}" \
  --tenant vdbbench \
  --num-shards "${NUM_SHARDS}" \
  --rf "${RF}" \
  --data-type int8 \
  --nprobe 52 \
  --rerank-pool 384 \
  --concurrency-duration 30 \
  --num-concurrency "${CONCURRENCY_LIST}"

echo "--- [4/5] LabelFilterPerformanceCase (Cohere 10M 1.0% Scalar Label Filter) ---"
"${VDB}" massengine \
  --case-type LabelFilterPerformanceCase \
  --dataset-with-size-type "Large Cohere (768dim, 10M)" \
  --label-percentage 0.01 \
  --db-label "${DB_LABEL}" \
  --db-version "${DB_VERSION}" \
  --url "${MASSENGINE_URL}" \
  --api-key "${MASSENGINE_API_KEY}" \
  --tenant vdbbench \
  --num-shards "${NUM_SHARDS}" \
  --rf "${RF}" \
  --data-type int8 \
  --nprobe 60 \
  --rerank-pool 384 \
  --insert-batch-size 4096 \
  --load-concurrency "${LOAD_CONCURRENCY}" \
  --concurrency-duration 30 \
  --num-concurrency "${CONCURRENCY_LIST}"

echo "--- [5/5] StreamingPerformanceCase (Cohere 100K Concurrent Read+Write @ 1,000 writes/s) ---"
"${VDB}" massengine \
  --case-type StreamingPerformanceCase \
  --streaming-insert-rate 1000 \
  --insert-batch-size 500 \
  --db-label "${DB_LABEL}" \
  --db-version "${DB_VERSION}" \
  --url "${MASSENGINE_URL}" \
  --api-key "${MASSENGINE_API_KEY}" \
  --tenant vdbbench \
  --num-shards "${NUM_SHARDS}" \
  --rf "${RF}" \
  --data-type int8 \
  --nprobe 28 \
  --rerank-pool 320

echo "=== Completed all 5 official VectorDBBench suites. Output JSONs saved under ${RESULTS_LOCAL_DIR}/ ==="
