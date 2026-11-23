#!/usr/bin/env bash
# Downloads SHA-256-verified MassEngine release binaries onto a Linux benchmark host
# and starts a single-node 8-shard data node + HTTP gateway via systemd (In-Memory or Direct NVMe Mode).
#
# Usage:
#   MASSENGINE_LICENSE_KEY="meli_..." \
#   MASSENGINE_API_KEY="bench-token-change-me" \
#   NVME_MODE=true \
#   DATA_DIR=/mnt/nvme/massengine \
#   ./vectordbbench/install_server_node.sh

set -euo pipefail

VERSION="${MASSENGINE_VERSION:-v0.11.3}"
NVME_MODE="${NVME_MODE:-false}"
DATA_DIR="${DATA_DIR:-/var/lib/massengine}"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
LISTEN_ADDR="${LISTEN_ADDR:-0.0.0.0:8080}"
NODE_RPC_ADDR="${NODE_RPC_ADDR:-127.0.0.1:9410}"
DIM="${DIM:-768}"
SHARDS="${SHARDS:-8}"
RF="${RF:-1}"

if [[ -z "${MASSENGINE_API_KEY:-}" ]]; then
  echo "ERROR: Set MASSENGINE_API_KEY to a Bearer token for benchmark requests." >&2
  exit 1
fi

HOST_CORES="$(nproc 2>/dev/null || echo 1)"
if [[ -z "${MASSENGINE_LICENSE_KEY:-}" && "${HOST_CORES}" -gt 1 ]]; then
  cat >&2 <<EOF
WARNING: MASSENGINE_LICENSE_KEY is not set on a ${HOST_CORES}-vCPU machine.
Without a multi-core license key, MassEngine runs in 1-Core Free Tier mode (pinned to 1 vCPU / 1M vectors).
For multi-core benchmarks:
  - Redeem the free 21-day 8-core code ME-EVAL-LAUNCH-21-DAYS at https://massengine.com/console
  - Or request a 16+ core benchmark license from eng@massengine.com
EOF
fi

ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64|amd64) BIN_ARCH="amd64" ;;
  aarch64|arm64) BIN_ARCH="arm64" ;;
  *) echo "Unsupported architecture: ${ARCH}" >&2; exit 1 ;;
esac

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "=== Downloading MassEngine ${VERSION} (linux-${BIN_ARCH}) & verifying SHA-256 checksums ==="
curl -fsSL "https://massengine.com/releases/version.json" -o "${TMP_DIR}/version.json"

for COMP in node server; do
  BIN_NAME="massengine-${COMP}-linux-${BIN_ARCH}"
  curl -fsSL "https://massengine.com/releases/${BIN_NAME}" -o "${TMP_DIR}/${BIN_NAME}"
  EXPECTED_SHA="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["checksums"][sys.argv[2]])' "${TMP_DIR}/version.json" "${BIN_NAME}")"
  echo "${EXPECTED_SHA}  ${TMP_DIR}/${BIN_NAME}" | sha256sum -c -
  sudo install -m 0755 "${TMP_DIR}/${BIN_NAME}" "${INSTALL_DIR}/massengine-${COMP}"
done

sudo mkdir -p "${DATA_DIR}/node-0" "${DATA_DIR}/gw" /etc/massengine
NODE_SECRET="$(head -c 24 /dev/urandom | base64 | tr -d '/+=\n')"
printf '%s\n' "${NODE_SECRET}" | sudo tee /etc/massengine/node_auth.secret >/dev/null
printf '%s\n' "${MASSENGINE_API_KEY}" | sudo tee /etc/massengine/client_auth.token >/dev/null
sudo chmod 0600 /etc/massengine/node_auth.secret /etc/massengine/client_auth.token

LICENSE_ARG=""
if [[ -n "${MASSENGINE_LICENSE_KEY:-}" ]]; then
  printf '%s\n' "${MASSENGINE_LICENSE_KEY}" | sudo tee /etc/massengine/bench.license >/dev/null
  sudo chmod 0600 /etc/massengine/bench.license
  LICENSE_ARG="--license-key /etc/massengine/bench.license"
fi

if [[ "${NVME_MODE}" == "true" ]]; then
  EXTRA_ARGS="--nvme-mode --flush-threshold 250000"
  NODE_GOMEM="${NODE_GOMEM:-21GiB}"
  SRV_GOMEM="${SRV_GOMEM:-4GiB}"
  GOGC_VAL="40"
else
  EXTRA_ARGS="--release-vectors=true --cold-meta=true --flush-threshold 250000"
  NODE_GOMEM="${NODE_GOMEM:-48GiB}"
  SRV_GOMEM="${SRV_GOMEM:-6GiB}"
  GOGC_VAL="50"
fi

sudo tee /etc/systemd/system/massengine-node.service >/dev/null <<SVC
[Unit]
Description=MassEngine Benchmark Data Node
After=network.target

[Service]
Type=simple
LimitNOFILE=1048576
Environment="GOMEMLIMIT=${NODE_GOMEM}"
Environment="GOGC=${GOGC_VAL}"
ExecStart=${INSTALL_DIR}/massengine-node --addr ${NODE_RPC_ADDR} --root ${DATA_DIR}/node-0 --node 0 --nodes 1 --shards ${SHARDS} --rf ${RF} --dim ${DIM} --cells 0 --max-segments 8 ${EXTRA_ARGS} --auth-file /etc/massengine/node_auth.secret ${LICENSE_ARG}
Restart=no

[Install]
WantedBy=multi-user.target
SVC

sudo tee /etc/systemd/system/massengine-server.service >/dev/null <<SVC
[Unit]
Description=MassEngine Benchmark HTTP Gateway
After=massengine-node.service
Requires=massengine-node.service

[Service]
Type=simple
LimitNOFILE=1048576
Environment="GOMEMLIMIT=${SRV_GOMEM}"
Environment="GOGC=${GOGC_VAL}"
ExecStart=${INSTALL_DIR}/massengine-server --listen ${LISTEN_ADDR} --root ${DATA_DIR}/gw --node-addrs ${NODE_RPC_ADDR} --nodes 1 --shards ${SHARDS} --rf ${RF} --dim ${DIM} --node-auth-file /etc/massengine/node_auth.secret --client-auth-file /etc/massengine/client_auth.token ${LICENSE_ARG}
Restart=no

[Install]
WantedBy=multi-user.target
SVC

sudo systemctl daemon-reload
sudo systemctl restart massengine-node
sleep 2
sudo systemctl restart massengine-server

PORT="${LISTEN_ADDR##*:}"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/v1/health" >/dev/null 2>&1; then
    echo "OK: MassEngine (${VERSION}) is healthy at http://${LISTEN_ADDR} (nvme_mode=${NVME_MODE})."
    curl -fsS "http://127.0.0.1:${PORT}/v1/health" && echo ""
    exit 0
  fi
  sleep 1
done

echo "ERROR: Timed out waiting for MassEngine health check; inspect journalctl -u massengine-node -u massengine-server" >&2
exit 1
