#!/usr/bin/env bash
# Runs official upstream Zilliz VectorDBBench Cohere-1M & Streaming suites
# tuned for an 8-core evaluation cluster (1x 8-vCPU node or 2x 4-vCPU HA).
#
# Usage:
#   MASSENGINE_URL="http://127.0.0.1:8080" \
#   MASSENGINE_API_KEY="meadm_..." \
#   ./vectordbbench/run_cohere_1m_8core.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${WORK_DIR:-$(pwd)/.vdbbench-work}"
MASSENGINE_URL="${MASSENGINE_URL:-http://127.0.0.1:8080}"
DB_LABEL="${DB_LABEL:-massengine-8c-eval}"
DB_VERSION="${DB_VERSION:-v0.11.8}"
NUM_SHARDS="${NUM_SHARDS:-8}"
RF="${RF:-1}"
LOAD_CONCURRENCY="${LOAD_CONCURRENCY:-8}"
CONCURRENCY_LIST="${CONCURRENCY_LIST:-1,4,8,16,32}"

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

echo "--- [1/4] Performance768D1M (Cohere 1M Unfiltered) ---"
"${VDB}" massengine \
  --case-type Performance768D1M \
  --db-label "${DB_LABEL}" \
  --db-version "${DB_VERSION}" \
  --url "${MASSENGINE_URL}" \
  --api-key "${MASSENGINE_API_KEY}" \
  --tenant vdbbench \
  --num-shards "${NUM_SHARDS}" \
  --rf "${RF}" \
  --data-type int8 \
  --nprobe 48 \
  --rerank-pool 256 \
  --insert-batch-size 4096 \
  --load-concurrency "${LOAD_CONCURRENCY}" \
  --concurrency-duration 20 \
  --num-concurrency "${CONCURRENCY_LIST}"

echo "--- [2/4] Performance768D1M1P (Cohere 1M 1% Int Filter, 99% Match) ---"
"${VDB}" massengine \
  --case-type Performance768D1M1P \
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
  --nprobe 56 \
  --rerank-pool 256 \
  --concurrency-duration 20 \
  --num-concurrency "${CONCURRENCY_LIST}"

echo "--- [3/4] Performance768D1M99P (Cohere 1M 99% Int Filter, 1% Match) ---"
"${VDB}" massengine \
  --case-type Performance768D1M99P \
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
  --nprobe 48 \
  --rerank-pool 256 \
  --concurrency-duration 20 \
  --num-concurrency "${CONCURRENCY_LIST}"

echo "--- [4/4] StreamingPerformanceCase (Cohere 100K Concurrent Read+Write @ 1,000 writes/s) ---"
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
  --rerank-pool 256

echo "=== Completed all 4 official 8-core VectorDBBench suites. Output JSONs saved under ${RESULTS_LOCAL_DIR}/ ==="
