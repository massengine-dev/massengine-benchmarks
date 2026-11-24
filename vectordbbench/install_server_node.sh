#!/usr/bin/env bash
# Downloads SHA-256-verified MassEngine release binaries onto a Linux host
# and configures systemd services for either:
#   - ROLE=all    (default): single-node data node + HTTP coordinator gateway
#   - ROLE=node            : dedicated data node (consumes licensed cores)
#   - ROLE=server          : stateless HTTP coordinator gateway (0 licensed cores)
#
# Usage (Single 8-Core Evaluation Node):
#   MASSENGINE_LICENSE_KEY="meli_..." \
#   MASSENGINE_API_KEY="bench-token-change-me" \
#   DATA_DIR=/mnt/nvme/massengine \
#   ./vectordbbench/install_server_node.sh
#
# Usage (2-Node x 4-vCPU HA Evaluation Cluster, RF=2 + Free Coordinator):
#   # Data Node 0 (10.0.0.11):
#   ROLE=node NODE_ID=0 NODES=2 RF=2 DIM=1024 NODE_SECRET="shared-hex" \
#     MASSENGINE_LICENSE_KEY="meli_..." ./vectordbbench/install_server_node.sh
#   # Data Node 1 (10.0.0.12):
#   ROLE=node NODE_ID=1 NODES=2 RF=2 DIM=1024 NODE_SECRET="shared-hex" \
#     MASSENGINE_LICENSE_KEY="meli_..." ./vectordbbench/install_server_node.sh
#   # Stateless Coordinator (0 licensed cores):
#   ROLE=server NODES=2 RF=2 DIM=1024 NODE_SECRET="shared-hex" \
#     NODE_ADDRS="10.0.0.11:9410,10.0.0.12:9410" \
#     MASSENGINE_LICENSE_KEY="meli_..." MASSENGINE_API_KEY="meadm_..." \
#     ./vectordbbench/install_server_node.sh

set -euo pipefail

ROLE="${ROLE:-all}"
VERSION="${MASSENGINE_VERSION:-}"
DATA_DIR="${DATA_DIR:-/var/lib/massengine}"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
LISTEN_ADDR="${LISTEN_ADDR:-0.0.0.0:8080}"
NODE_ID="${NODE_ID:-0}"
NODES="${NODES:-1}"
SHARDS="${SHARDS:-8}"
RF="${RF:-1}"
DIM="${DIM:-768}"
MAX_CORES="${MAX_CORES:-0}"
NODE_ADDRS="${NODE_ADDRS:-}"
NODE_SECRET="${NODE_SECRET:-}"
LICENSE_KEY="$(printf '%s' "${MASSENGINE_LICENSE_KEY:-}" | tr -d ' \t\r\n')"

case "${ROLE}" in
  all|node|server) ;;
  *)
    echo "ERROR: Invalid ROLE='${ROLE}'. Must be all, node, or server." >&2
    exit 1
    ;;
esac

if [[ "${ROLE}" == "all" ]]; then
  NODE_RPC_ADDR="${NODE_RPC_ADDR:-127.0.0.1:9410}"
else
  NODE_RPC_ADDR="${NODE_RPC_ADDR:-0.0.0.0:9410}"
fi

if [[ "${ROLE}" != "node" && -z "${MASSENGINE_API_KEY:-}" ]]; then
  echo "ERROR: Set MASSENGINE_API_KEY to a Bearer token (e.g. meadm_...) for HTTP requests." >&2
  exit 1
fi

if [[ -z "${LICENSE_KEY}" ]]; then
  cat >&2 <<EOF
ERROR: MASSENGINE_LICENSE_KEY is required to download and run MassEngine release binaries.
Get your free key at https://massengine.com/console:
  - 1-Core Developer License ($0/mo): up to 1M vectors on 1 node
  - 8-Core 21-Day Evaluation ($0 trial): redeem code ME-EVAL-LAUNCH-21-DAYS
EOF
  exit 1
fi

if [[ "${ROLE}" == "server" && -z "${NODE_ADDRS}" ]]; then
  if [[ "${NODES}" -gt 1 ]]; then
    echo "ERROR: NODE_ADDRS is required when ROLE=server and NODES > 1 (e.g. NODE_ADDRS=10.0.0.11:9410,10.0.0.12:9410)." >&2
    exit 1
  fi
  NODE_ADDRS="127.0.0.1:9410"
fi

ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64|amd64) BIN_ARCH="amd64" ;;
  aarch64|arm64) BIN_ARCH="arm64" ;;
  *) echo "Unsupported architecture: ${ARCH}" >&2; exit 1 ;;
esac

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

curl -fsSL -H "Cache-Control: no-cache" "https://massengine.com/releases/version.json" -o "${TMP_DIR}/version.json"
if [[ -z "${VERSION}" ]]; then
  VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["latest_version"])' "${TMP_DIR}/version.json")"
fi

COMPONENTS=()
case "${ROLE}" in
  all)    COMPONENTS=(node server) ;;
  node)   COMPONENTS=(node) ;;
  server) COMPONENTS=(server) ;;
esac

echo "=== Downloading MassEngine ${VERSION} (linux-${BIN_ARCH}, role=${ROLE}) & verifying SHA-256 checksums ==="
for COMP in "${COMPONENTS[@]}"; do
  BIN_NAME="massengine-${COMP}-linux-${BIN_ARCH}"
  printf 'header = "Authorization: Bearer %s"\n' "${LICENSE_KEY}" | \
    curl -fsSL -H "Cache-Control: no-cache" -K - "https://massengine.com/releases/${BIN_NAME}" -o "${TMP_DIR}/${BIN_NAME}"
  EXPECTED_SHA="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["checksums"][sys.argv[2]])' "${TMP_DIR}/version.json" "${BIN_NAME}")"
  echo "${EXPECTED_SHA}  ${TMP_DIR}/${BIN_NAME}" | sha256sum -c -
  sudo install -m 0755 "${TMP_DIR}/${BIN_NAME}" "${INSTALL_DIR}/massengine-${COMP}"
done

sudo install -d -m 0700 /etc/massengine "${DATA_DIR}"
if [[ -z "${NODE_SECRET}" ]]; then
  if sudo test -s /etc/massengine/node_auth.secret; then
    NODE_SECRET="$(sudo cat /etc/massengine/node_auth.secret | tr -d ' \t\r\n')"
  else
    NODE_SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  fi
fi
printf '%s\n' "${NODE_SECRET}" | sudo tee /etc/massengine/node_auth.secret >/dev/null
sudo chmod 0600 /etc/massengine/node_auth.secret

printf '%s\n' "${LICENSE_KEY}" | sudo tee /etc/massengine/license.key >/dev/null
sudo chmod 0600 /etc/massengine/license.key

if [[ "${ROLE}" != "node" ]]; then
  printf '%s\n' "${MASSENGINE_API_KEY}" | sudo tee /etc/massengine/admin.token >/dev/null
  sudo chmod 0600 /etc/massengine/admin.token
fi

NODE_GOMEM="${NODE_GOMEM:-}"
SRV_GOMEM="${SRV_GOMEM:-}"
GOGC_VAL="${GOGC_VAL:-50}"
NODE_MEM_LINE=""
SRV_MEM_LINE=""
if [[ -n "${NODE_GOMEM}" ]]; then
  NODE_MEM_LINE="Environment=\"GOMEMLIMIT=${NODE_GOMEM}\""
fi
if [[ -n "${SRV_GOMEM}" ]]; then
  SRV_MEM_LINE="Environment=\"GOMEMLIMIT=${SRV_GOMEM}\""
fi

if [[ "${ROLE}" == "all" || "${ROLE}" == "node" ]]; then
  sudo mkdir -p "${DATA_DIR}/node-${NODE_ID}"
  sudo tee /etc/systemd/system/massengine-node.service >/dev/null <<SVC
[Unit]
Description=MassEngine Data Node (${NODE_ID})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
LimitNOFILE=1048576
LimitMEMLOCK=infinity
${NODE_MEM_LINE}
Environment="GOGC=${GOGC_VAL}"
ExecStart=${INSTALL_DIR}/massengine-node --addr ${NODE_RPC_ADDR} --root ${DATA_DIR}/node-${NODE_ID} --node ${NODE_ID} --nodes ${NODES} --shards ${SHARDS} --rf ${RF} --dim ${DIM} --max-cores ${MAX_CORES} --auth-file /etc/massengine/node_auth.secret --license-key /etc/massengine/license.key
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
SVC
fi

if [[ "${ROLE}" == "all" || "${ROLE}" == "server" ]]; then
  GATEWAY_ADDRS="${NODE_ADDRS:-${NODE_RPC_ADDR}}"
  sudo mkdir -p "${DATA_DIR}/gw"
  DEPS=""
  if [[ "${ROLE}" == "all" ]]; then
    DEPS="After=massengine-node.service
Requires=massengine-node.service"
  else
    DEPS="After=network-online.target
Wants=network-online.target"
  fi
  sudo tee /etc/systemd/system/massengine-server.service >/dev/null <<SVC
[Unit]
Description=MassEngine HTTP Coordinator Gateway
${DEPS}

[Service]
Type=simple
LimitNOFILE=1048576
${SRV_MEM_LINE}
Environment="GOGC=${GOGC_VAL}"
ExecStart=${INSTALL_DIR}/massengine-server --listen ${LISTEN_ADDR} --root ${DATA_DIR}/gw --node-addrs ${GATEWAY_ADDRS} --nodes ${NODES} --shards ${SHARDS} --rf ${RF} --dim ${DIM} --route-path ${DATA_DIR}/gw/routes.json --tenant-keys-file ${DATA_DIR}/gw/tenant_keys.json --tenant-state-file ${DATA_DIR}/gw/tenant_state.json --node-auth-file /etc/massengine/node_auth.secret --client-auth-file /etc/massengine/admin.token --license-key /etc/massengine/license.key
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
SVC
fi

sudo systemctl daemon-reload
if [[ "${ROLE}" == "all" || "${ROLE}" == "node" ]]; then
  sudo systemctl enable --now massengine-node
  sudo systemctl restart massengine-node
fi

if [[ "${ROLE}" == "node" ]]; then
  echo "OK: massengine-node (${VERSION}, node=${NODE_ID}/${NODES}) started on ${NODE_RPC_ADDR}."
  exit 0
fi

sleep 2
sudo systemctl enable --now massengine-server
sudo systemctl restart massengine-server

PORT="${LISTEN_ADDR##*:}"
for _ in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${PORT}/v1/health" >/dev/null 2>&1; then
    echo "OK: MassEngine (${VERSION}) gateway is healthy at http://${LISTEN_ADDR} (role=${ROLE}, nodes=${NODES}, shards=${SHARDS}, rf=${RF})."
    curl -fsS "http://127.0.0.1:${PORT}/v1/health" && echo ""
    exit 0
  fi
  sleep 1
done

echo "ERROR: Timed out waiting for MassEngine health check; inspect journalctl -u massengine-node -u massengine-server" >&2
exit 1
