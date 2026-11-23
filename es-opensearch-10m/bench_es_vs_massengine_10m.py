#!/usr/bin/env python3
"""
Apples-to-Apples Cohere-10M (10,000,000 x 768-d) Benchmark Driver:
MassEngine vs. Elasticsearch 9.x (bbq_hnsw & int8_hnsw) vs. OpenSearch 3.x (FAISS fp16 & on_disk 32x)

Executes 4 rigorous phases against a single 16-vCPU database node over private VPC networking:
  Phase 1: Multi-process Bulk Ingest (10,000,000 L2-normalized vectors + scalar/numeric metadata)
  Phase 2: Pre-ForceMerge / Post-Ingest Search Sweep (7 selectivity levels @ k=10 + 3 VDBBench cases @ k=100)
  Phase 3: Explicit ForceMerge (max_num_segments=1 on ES/OS, /v1/compact on MassEngine) + Post-Merge Search Sweep
  Phase 4: Live Streaming Read+Write (1,000 writes/s on the 10M index + 16 concurrent search clients for 60s)
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import shlex
import struct
import subprocess
import sys
import threading
import time
from typing import Any

import numpy as np
import urllib3

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

MAGIC_MBIN = b"MBIN\x01\x00\x00\x00"
_MEB1_HEADER_STRUCT = struct.Struct("<4sHHHII")
_MES1_HEADER_STRUCT = struct.Struct("<4sHHHHIIIII")
_MESR_HEADER_STRUCT = struct.Struct("<4sHHII")
_U16_STRUCT = struct.Struct("<H")
_U64_STRUCT = struct.Struct("<Q")


def json_dumps_bytes(obj: Any, numpy_opt: bool = False) -> bytes:
    if _orjson is not None:
        opts = _orjson.OPT_SERIALIZE_NUMPY if numpy_opt else 0
        return _orjson.dumps(obj, option=opts)
    if numpy_opt:
        raise RuntimeError("orjson is required for fast numpy bulk serialization")
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


def json_loads_bytes(raw: bytes) -> Any:
    if _orjson is not None:
        return _orjson.loads(raw)
    return json.loads(raw.decode("utf-8"))


def get_rec_dtype(dim: int) -> np.dtype:
    return np.dtype(
        [
            ("doc_id", "<u8"),
            ("cat_id", "<u2"),
            ("vdb_id", "<i8"),
            ("vec", "<f4", (dim,)),
        ]
    )


def pack_meb1_batch(
    tenant_bytes: bytes,
    db_bytes: bytes,
    vecs_np: np.ndarray,
    ids_np: np.ndarray,
    cats_np: np.ndarray,
) -> bytes:
    count, dim = vecs_np.shape
    flags = 1 | (1 << 2)  # integer doc IDs + uint16 category
    hdr = _MEB1_HEADER_STRUCT.pack(
        b"MEB1",
        flags,
        len(tenant_bytes),
        len(db_bytes),
        count,
        dim,
    )
    return b"".join(
        [
            hdr,
            tenant_bytes,
            db_bytes,
            np.ascontiguousarray(vecs_np, dtype="<f4").tobytes(),
            np.ascontiguousarray(ids_np, dtype="<u8").tobytes(),
            np.ascontiguousarray(cats_np, dtype="<u2").tobytes(),
        ]
    )


def pack_mes1_query(
    tenant_bytes: bytes,
    db_bytes: bytes,
    qvec_f32: np.ndarray,
    k: int,
    nprobe: int,
    rerank_pool: int,
    category: int | None = None,
    min_doc_id: int | None = None,
) -> bytes:
    # skip_meta (1<<0) | binary_response (1<<1) | omit_str_ids (1<<8)
    flags = (1 << 0) | (1 << 1) | (1 << 8)
    trailer = b""
    if category is not None:
        flags |= 1 << 4
        trailer += _U16_STRUCT.pack(category)
    if min_doc_id is not None:
        flags |= 1 << 5
        trailer += _U64_STRUCT.pack(min_doc_id)
    hdr = _MES1_HEADER_STRUCT.pack(
        b"MES1",
        flags,
        len(tenant_bytes),
        len(db_bytes),
        0,
        int(qvec_f32.shape[0]),
        k,
        max(0, nprobe),
        max(0, rerank_pool),
        0,
    )
    return hdr + tenant_bytes + db_bytes + np.ascontiguousarray(qvec_f32, dtype="<f4").tobytes() + trailer


def unpack_mesr_ids(raw: bytes) -> list[int]:
    magic, _, _, cnt, _ = _MESR_HEADER_STRUCT.unpack_from(raw, 0)
    if magic != b"MESR":
        raise RuntimeError(f"Unexpected MESR header magic: {magic!r}")
    if cnt == 0:
        return []
    return np.frombuffer(raw, dtype="<u8", count=cnt, offset=16).tolist()


# ---------------------------------------------------------------------------
# Multiprocessing Bulk Ingest Workers
# ---------------------------------------------------------------------------
_INGEST_CFG: dict[str, Any] = {}
_INGEST_HTTP: urllib3.PoolManager | None = None
_INGEST_AUTH_HEADERS: dict[str, str] = {}


def _init_ingest_worker(cfg: dict[str, Any]) -> None:
    global _INGEST_CFG, _INGEST_HTTP, _INGEST_AUTH_HEADERS
    _INGEST_CFG = cfg
    _INGEST_AUTH_HEADERS = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
    _INGEST_HTTP = urllib3.PoolManager(
        num_pools=4,
        maxsize=8,
        headers=_INGEST_AUTH_HEADERS,
        timeout=urllib3.Timeout(connect=10.0, read=600.0),
    )


def _ingest_slice_worker(task: tuple[str, int, int, int]) -> tuple[int, int]:
    assert _INGEST_HTTP is not None
    mbin_path, start_row, end_row, dim = task
    rec_dtype = get_rec_dtype(dim)
    mm = np.memmap(mbin_path, dtype=rec_dtype, mode="r", offset=16, shape=(end_row,))
    chunk = mm[start_row:end_row]
    engine = _INGEST_CFG["engine"]
    base_url = _INGEST_CFG["url"]
    batch_size = int(_INGEST_CFG["batch_size"])
    total_sent = 0
    retries = 0

    if engine == "massengine":
        tenant_b = _INGEST_CFG["tenant"].encode("utf-8")
        db_b = _INGEST_CFG["collection"].encode("utf-8")
        me_headers = {**_INGEST_AUTH_HEADERS, "Content-Type": "application/octet-stream"}
        for off in range(0, len(chunk), batch_size):
            sub = chunk[off : off + batch_size]
            payload = pack_meb1_batch(
                tenant_b,
                db_b,
                sub["vec"],
                sub["doc_id"],
                sub["cat_id"],
            )
            for attempt in range(8):
                resp = _INGEST_HTTP.request(
                    "POST",
                    f"{base_url}/v1/ingest",
                    body=payload,
                    headers=me_headers,
                )
                if resp.status == 200:
                    break
                retries += 1
                if attempt == 7:
                    raise RuntimeError(
                        f"MassEngine ingest failed ({resp.status}): {resp.data[:300]!r}"
                    )
                time.sleep(min(4.0, 0.2 * (2**attempt)))
            total_sent += len(sub)
    elif engine in ("elasticsearch", "opensearch"):
        idx_name = _INGEST_CFG["collection"]
        for off in range(0, len(chunk), batch_size):
            sub = chunk[off : off + batch_size]
            parts: list[bytes] = []
            ids = np.asarray(sub["doc_id"])
            cats = np.asarray(sub["cat_id"])
            vecs = np.asarray(sub["vec"], dtype=np.float32)
            for i in range(len(sub)):
                did = int(ids[i])
                parts.append(f'{{"index":{{"_id":"{did}"}}}}'.encode("ascii"))
                parts.append(
                    json_dumps_bytes(
                        {"doc_id": did, "cat_id": str(int(cats[i])), "emb": vecs[i]},
                        numpy_opt=True,
                    )
                )
            body = b"\n".join(parts) + b"\n"
            for attempt in range(10):
                resp = _INGEST_HTTP.request(
                    "POST",
                    f"{base_url}/{idx_name}/_bulk?filter_path=errors",
                    body=body,
                    headers={"Content-Type": "application/x-ndjson"},
                )
                if resp.status == 200:
                    parsed = json_loads_bytes(resp.data)
                    if not parsed.get("errors", False):
                        break
                retries += 1
                if attempt == 9:
                    raise RuntimeError(
                        f"{engine} bulk failed ({resp.status}): {resp.data[:300]!r}"
                    )
                time.sleep(min(5.0, 0.25 * (2**attempt)))
            total_sent += len(sub)
    else:
        raise ValueError(f"Unsupported engine: {engine}")

    del mm
    return total_sent, retries


# ---------------------------------------------------------------------------
# Multiprocessing Concurrent Search Workers (Forked Copy-on-Write Frames)
# ---------------------------------------------------------------------------
_SEARCH_FRAMES: list[bytes] = []
_SEARCH_CFG: dict[str, Any] = {}


def _search_proc_entry(args: tuple[int, int, float, float]) -> tuple[int, list[int]]:
    proc_idx, threads_in_proc, warmup_sec, duration_sec = args
    cfg = _SEARCH_CFG
    frames = _SEARCH_FRAMES
    n_frames = len(frames)
    engine = cfg["engine"]
    url = cfg["search_url"]
    headers = {"Content-Type": cfg["content_type"]}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    pool = urllib3.PoolManager(
        num_pools=2,
        maxsize=max(8, threads_in_proc + 4),
        headers=headers,
        timeout=urllib3.Timeout(connect=10.0, read=120.0),
    )

    latencies_us_all: list[list[int]] = [[] for _ in range(threads_in_proc)]
    counts = [0] * threads_in_proc
    errors: list[str] = []

    t_warm_end = time.perf_counter() + warmup_sec
    t_meas_end = t_warm_end + duration_sec

    def worker_fn(tid: int) -> None:
        idx = (proc_idx * 97 + tid * 31) % n_frames
        local_lats: list[int] = []
        local_cnt = 0
        try:
            while True:
                now = time.perf_counter()
                if now >= t_meas_end:
                    break
                frame = frames[idx]
                idx += 1
                if idx >= n_frames:
                    idx = 0
                t0 = time.perf_counter()
                resp = pool.request("POST", url, body=frame, headers=headers)
                t1 = time.perf_counter()
                if resp.status != 200:
                    raise RuntimeError(f"Search HTTP {resp.status}: {resp.data[:200]!r}")
                if engine in ("elasticsearch", "opensearch"):
                    # Parse response to include real client deserialization parity
                    _ = json_loads_bytes(resp.data)
                else:
                    _ = _MESR_HEADER_STRUCT.unpack_from(resp.data, 0)
                if t0 >= t_warm_end and t1 <= t_meas_end + 2.0:
                    local_cnt += 1
                    local_lats.append(int((t1 - t0) * 1_000_000))
        except Exception as exc:
            errors.append(str(exc))
        latencies_us_all[tid] = local_lats
        counts[tid] = local_cnt

    threads = [threading.Thread(target=worker_fn, args=(t,)) for t in range(threads_in_proc)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    pool.clear()

    if errors:
        raise RuntimeError(f"Search worker error: {errors[0]}")

    merged_lats: list[int] = []
    for sub in latencies_us_all:
        merged_lats.extend(sub)
    return sum(counts), merged_lats


# ---------------------------------------------------------------------------
# Node Telemetry & Engine Helpers
# ---------------------------------------------------------------------------
def collect_node_telemetry(
    engine: str,
    http: urllib3.PoolManager,
    base_url: str,
    collection: str,
    api_key: str,
    ssh_host: str | None,
    ssh_key: str | None,
) -> dict[str, Any]:
    info: dict[str, Any] = {}
    if engine in ("elasticsearch", "opensearch"):
        r_seg = http.request("GET", f"{base_url}/_cat/segments/{collection}?format=json")
        if r_seg.status == 200:
            segs = json_loads_bytes(r_seg.data)
            info["segment_count"] = len(segs)
        r_st = http.request("GET", f"{base_url}/{collection}/_stats/store,docs,merge")
        if r_st.status == 200:
            st = json_loads_bytes(r_st.data)["_all"]["primaries"]
            info["doc_count"] = st["docs"]["count"]
            info["store_bytes"] = st["store"]["size_in_bytes"]
            info["merge_total_time_ms"] = st["merges"]["total_time_in_millis"]
            info["merge_current"] = st["merges"]["current"]
        if engine == "opensearch":
            r_knn = http.request(
                "GET",
                f"{base_url}/_plugins/_knn/stats/graph_memory_usage,graph_memory_usage_percentage",
            )
            if r_knn.status == 200:
                knn_nodes = json_loads_bytes(r_knn.data).get("nodes", {})
                info["knn_graph_memory_bytes"] = sum(
                    int(v.get("graph_memory_usage", 0)) * 1024 for v in knn_nodes.values()
                )
    else:
        hdrs = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r_h = http.request("GET", f"{base_url}/v1/health", headers=hdrs)
        if r_h.status == 200:
            info["health"] = json_loads_bytes(r_h.data)

    if ssh_host and ssh_key:
        remote_py = r"""
import glob, json, os, subprocess

mem = {}
with open("/proc/meminfo") as f:
    for line in f:
        parts = line.split()
        if len(parts) >= 2:
            mem[parts[0].rstrip(":")] = int(parts[1]) * 1024

proc_rss = 0
proc_rss_anon = 0
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        comm = open(f"/proc/{pid}/comm").read().strip()
        if comm in ("massengine-node", "massengine-serv", "java"):
            for l in open(f"/proc/{pid}/status"):
                if l.startswith("VmRSS:"):
                    proc_rss += int(l.split()[1]) * 1024
                elif l.startswith("RssAnon:"):
                    proc_rss_anon += int(l.split()[1]) * 1024
    except Exception:
        pass

seg_files = len(glob.glob("/mnt/nvme/massengine-node-0/**/*.seg", recursive=True)) + len(
    glob.glob("/mnt/nvme/massengine-data/**/*.seg", recursive=True)
)
disk_bytes = 0
for p in ("/mnt/nvme/massengine-node-0", "/mnt/nvme/massengine-data", "/mnt/nvme/es-data", "/mnt/nvme/os-data"):
    if os.path.exists(p):
        out = subprocess.check_output(["sudo", "du", "-sb", p], text=True).split()[0]
        disk_bytes += int(out)

print(json.dumps({
    "mem_total_bytes": mem.get("MemTotal", 0),
    "mem_available_bytes": mem.get("MemAvailable", 0),
    "mem_used_bytes": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
    "page_cache_bytes": mem.get("Cached", 0),
    "proc_rss_bytes": proc_rss,
    "proc_rss_anon_bytes": proc_rss_anon,
    "nvme_data_bytes": disk_bytes,
    "me_seg_files": seg_files,
}))
"""
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            "-i",
            ssh_key,
            f"ubuntu@{ssh_host}",
            f"python3 -c {shlex.quote(remote_py)}",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            ssh_data = json.loads(res.stdout.strip().splitlines()[-1])
            info.update(ssh_data)
            if engine == "massengine":
                info["segment_count"] = ssh_data.get("me_seg_files", 0)
    return info


def build_query_frames(
    engine: str,
    collection: str,
    tenant: str,
    queries_f32: np.ndarray,
    k: int,
    case_spec: dict[str, Any],
    profile: dict[str, Any],
    es_index_type: str,
    os_index_type: str = "faiss_fp16",
) -> list[bytes]:
    frames: list[bytes] = []
    cat_id = case_spec.get("cat_id")
    min_doc_id = case_spec.get("min_doc_id")

    if engine == "massengine":
        tenant_b = tenant.encode("utf-8")
        db_b = collection.encode("utf-8")
        nprobe = int(profile["nprobe"])
        rerank_pool = int(profile["rerank_pool"])
        for i in range(queries_f32.shape[0]):
            frames.append(
                pack_mes1_query(
                    tenant_b,
                    db_b,
                    queries_f32[i],
                    k=k,
                    nprobe=nprobe,
                    rerank_pool=rerank_pool,
                    category=cat_id,
                    min_doc_id=min_doc_id,
                )
            )
    elif engine == "elasticsearch":
        num_candidates = max(k, int(profile["num_candidates"]))
        for i in range(queries_f32.shape[0]):
            knn_obj: dict[str, Any] = {
                "field": "emb",
                "query_vector": queries_f32[i],
                "k": k,
                "num_candidates": num_candidates,
            }
            if es_index_type == "bbq_hnsw":
                knn_obj["rescore_vector"] = {"oversample": float(profile.get("oversample", 3.0))}
            if cat_id is not None:
                knn_obj["filter"] = {"term": {"cat_id": str(int(cat_id))}}
            elif min_doc_id is not None:
                knn_obj["filter"] = {"range": {"doc_id": {"gte": int(min_doc_id)}}}
            q_body = {
                "size": k,
                "stored_fields": "_none_",
                "_source": False,
                "docvalue_fields": ["doc_id"],
                "knn": knn_obj,
            }
            frames.append(json_dumps_bytes(q_body, numpy_opt=True))
    elif engine == "opensearch":
        ef_search = max(k, int(profile["ef_search"]))
        for i in range(queries_f32.shape[0]):
            emb_q: dict[str, Any] = {
                "vector": queries_f32[i],
                "k": k,
                "method_parameters": {"ef_search": ef_search},
            }
            if os_index_type == "faiss_on_disk":
                emb_q["rescore"] = {"oversample_factor": float(profile.get("oversample", 3.0))}
            if cat_id is not None:
                emb_q["filter"] = {"term": {"cat_id": str(int(cat_id))}}
            elif min_doc_id is not None:
                emb_q["filter"] = {"range": {"doc_id": {"gte": int(min_doc_id)}}}
            q_body = {
                "size": k,
                "stored_fields": "_none_",
                "_source": False,
                "docvalue_fields": ["doc_id"],
                "query": {"knn": {"emb": emb_q}},
            }
            frames.append(json_dumps_bytes(q_body, numpy_opt=True))
    else:
        raise ValueError(f"Unsupported engine: {engine}")
    return frames


def summarize_latencies_us(lats_us: list[int]) -> dict[str, float]:
    if not lats_us:
        return {"mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
    arr = np.asarray(lats_us, dtype=np.float64) / 1000.0
    return {
        "mean_ms": round(float(np.mean(arr)), 3),
        "p50_ms": round(float(np.percentile(arr, 50)), 3),
        "p95_ms": round(float(np.percentile(arr, 95)), 3),
        "p99_ms": round(float(np.percentile(arr, 99)), 3),
    }


def run_serial_and_recall(
    engine: str,
    http: urllib3.PoolManager,
    search_url: str,
    content_type: str,
    api_key: str,
    frames: list[bytes],
    gt_lists: list[list[int]],
    k: int,
    max_queries: int = 500,
    soft_cap_sec: float = 22.0,
    min_queries: int = 150,
) -> dict[str, Any]:
    headers = {"Content-Type": content_type}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Warmup 40 queries
    for w in range(min(40, len(frames))):
        r = http.request("POST", search_url, body=frames[w], headers=headers)
        if r.status != 200:
            raise RuntimeError(f"Warmup search failed ({r.status}): {r.data[:200]!r}")

    lats_us: list[int] = []
    recalls: list[float] = []
    t_suite_start = time.perf_counter()
    limit = min(max_queries, len(frames), len(gt_lists))

    for i in range(limit):
        t0 = time.perf_counter()
        resp = http.request("POST", search_url, body=frames[i], headers=headers)
        t1 = time.perf_counter()
        if resp.status != 200:
            raise RuntimeError(f"Serial search failed ({resp.status}): {resp.data[:200]!r}")
        if engine == "massengine":
            got_ids = unpack_mesr_ids(resp.data)
        else:
            parsed = json_loads_bytes(resp.data)
            got_ids = [int(h["fields"]["doc_id"][0]) for h in parsed["hits"]["hits"]]

        lats_us.append(int((t1 - t0) * 1_000_000))
        gt_top = gt_lists[i][:k]
        if gt_top:
            recalls.append(len(set(got_ids[:k]) & set(gt_top)) / float(len(gt_top)))
        if (i + 1) >= min_queries and (t1 - t_suite_start) >= soft_cap_sec:
            break

    stats = summarize_latencies_us(lats_us)
    stats["queries_measured"] = len(lats_us)
    stats[f"recall_at_{k}"] = round(float(np.mean(recalls)) if recalls else 0.0, 4)
    stats["serial_qps"] = round(1000.0 / stats["mean_ms"], 2) if stats["mean_ms"] > 0 else 0.0
    return stats


def run_concurrent_qps(
    engine: str,
    search_url: str,
    content_type: str,
    api_key: str,
    frames: list[bytes],
    concurrency: int,
    warmup_sec: float = 2.0,
    duration_sec: float = 12.0,
) -> dict[str, Any]:
    global _SEARCH_FRAMES, _SEARCH_CFG
    _SEARCH_FRAMES = frames
    _SEARCH_CFG = {
        "engine": engine,
        "search_url": search_url,
        "content_type": content_type,
        "api_key": api_key,
    }

    num_procs = min(concurrency, min(16, os.cpu_count() or 8))
    base_threads = concurrency // num_procs
    rem = concurrency % num_procs
    proc_args = [
        (p, base_threads + (1 if p < rem else 0), warmup_sec, duration_sec)
        for p in range(num_procs)
    ]

    ctx = mp.get_context("fork")
    with ctx.Pool(processes=num_procs) as pool:
        results = pool.map(_search_proc_entry, proc_args)

    total_q = sum(r[0] for r in results)
    all_lats: list[int] = []
    for r in results:
        all_lats.extend(r[1])

    stats = summarize_latencies_us(all_lats)
    stats["concurrency"] = concurrency
    stats["duration_sec"] = duration_sec
    stats["completed_queries"] = total_q
    stats["qps"] = round(total_q / duration_sec, 2)
    return stats


def run_full_sweep(
    phase_label: str,
    engine: str,
    http: urllib3.PoolManager,
    base_url: str,
    collection: str,
    tenant: str,
    api_key: str,
    queries_f32: np.ndarray,
    gt_map: dict[str, list[list[int]]],
    es_index_type: str,
    warmup_sec: float,
    duration_sec: float,
    max_serial_queries: int,
    os_index_type: str = "faiss_fp16",
) -> dict[str, Any]:
    search_url = (
        f"{base_url}/v1/search" if engine == "massengine" else f"{base_url}/{collection}/_search"
    )
    content_type = "application/octet-stream" if engine == "massengine" else "application/json"

    k10_cases = [
        {"name": "unfiltered_100p", "selectivity": "100%", "gt_key": "unfiltered_100p"},
        {"name": "label_50p", "selectivity": "50%", "cat_id": 1, "gt_key": "label_50p"},
        {"name": "label_10p", "selectivity": "10%", "cat_id": 3, "gt_key": "label_10p"},
        {"name": "label_5p", "selectivity": "5%", "cat_id": 4, "gt_key": "label_5p"},
        {"name": "label_1p", "selectivity": "1%", "cat_id": 6, "gt_key": "label_1p"},
        {"name": "label_0_1p", "selectivity": "0.1%", "cat_id": 9, "gt_key": "label_0_1p"},
        {
            "name": "int_range_1p",
            "selectivity": "1% (range)",
            "min_doc_id": int(queries_f32.shape[1] == 768 and 9_900_001 or 1),
            "gt_key": "int_range_1p",
        },
    ]
    if "int_range_min_doc_id" in gt_map:
        k10_cases[-1]["min_doc_id"] = int(gt_map["int_range_min_doc_id"])  # type: ignore[arg-type]

    if engine == "massengine":
        std_k10_profile: dict[str, Any] = {"nprobe": 20, "rerank_pool": 128}
        hi_k10_profile: dict[str, Any] = {"nprobe": 36, "rerank_pool": 256}
        vdb_k100_profile: dict[str, Any] = {"nprobe": 28, "rerank_pool": 256}
    elif engine == "elasticsearch":
        if es_index_type == "bbq_hnsw":
            std_k10_profile = {"num_candidates": 250, "oversample": 10.0}
            hi_k10_profile = {"num_candidates": 500, "oversample": 20.0}
            vdb_k100_profile = {"num_candidates": 300, "oversample": 5.0}
        else:
            std_k10_profile = {"num_candidates": 100}
            hi_k10_profile = {"num_candidates": 250}
            vdb_k100_profile = {"num_candidates": 200}
    else:
        if os_index_type == "faiss_on_disk":
            std_k10_profile = {"ef_search": 250, "oversample": 10.0}
            hi_k10_profile = {"ef_search": 500, "oversample": 20.0}
            vdb_k100_profile = {"ef_search": 300, "oversample": 5.0}
        else:
            std_k10_profile = {"ef_search": 100}
            hi_k10_profile = {"ef_search": 250}
            vdb_k100_profile = {"ef_search": 200}

    sweep_out: dict[str, Any] = {"selectivity_k10": {}, "high_recall_k10": {}, "vdbbench_k100": {}}

    print(f"\n=== [{phase_label}] Running 7-Case Selectivity Sweep (k=10, iso-recall profile) ===", flush=True)
    for case in k10_cases:
        cname = case["name"]
        frames = build_query_frames(
            engine,
            collection,
            tenant,
            queries_f32,
            10,
            case,
            std_k10_profile,
            es_index_type,
            os_index_type,
        )
        serial = run_serial_and_recall(
            engine,
            http,
            search_url,
            content_type,
            api_key,
            frames,
            gt_map[case["gt_key"]],
            k=10,
            max_queries=max_serial_queries,
        )
        c16 = run_concurrent_qps(
            engine, search_url, content_type, api_key, frames, 16, warmup_sec, duration_sec
        )
        c32 = run_concurrent_qps(
            engine, search_url, content_type, api_key, frames, 32, warmup_sec, duration_sec
        )
        sweep_out["selectivity_k10"][cname] = {
            "selectivity": case["selectivity"],
            "profile": std_k10_profile,
            "serial_c1": serial,
            "concurrent_c16": c16,
            "concurrent_c32": c32,
        }
        print(
            f"  [{phase_label}][k=10][{cname:15s}] recall@10={serial['recall_at_10']:.4f} | "
            f"c=1 p50={serial['p50_ms']:.2f}ms p95={serial['p95_ms']:.2f}ms | "
            f"c=16 QPS={c16['qps']:.1f} | c=32 QPS={c32['qps']:.1f}",
            flush=True,
        )

    print(f"=== [{phase_label}] Running High-Recall & Out-of-Box Operating Points (k=10) ===", flush=True)
    for case in (k10_cases[0], k10_cases[2], k10_cases[4]):
        cname = case["name"]
        frames = build_query_frames(
            engine,
            collection,
            tenant,
            queries_f32,
            10,
            case,
            hi_k10_profile,
            es_index_type,
            os_index_type,
        )
        serial = run_serial_and_recall(
            engine,
            http,
            search_url,
            content_type,
            api_key,
            frames,
            gt_map[case["gt_key"]],
            k=10,
            max_queries=max_serial_queries,
        )
        c32 = run_concurrent_qps(
            engine, search_url, content_type, api_key, frames, 32, warmup_sec, duration_sec
        )
        sweep_out["high_recall_k10"][cname] = {
            "profile": hi_k10_profile,
            "serial_c1": serial,
            "concurrent_c32": c32,
        }
        print(
            f"  [{phase_label}][hi-k=10][{cname:15s}] recall@10={serial['recall_at_10']:.4f} | "
            f"c=1 p50={serial['p50_ms']:.2f}ms | c=32 QPS={c32['qps']:.1f}",
            flush=True,
        )

    if (engine == "elasticsearch" and es_index_type == "bbq_hnsw") or (
        engine == "opensearch" and os_index_type == "faiss_on_disk"
    ):
        oob_profile: dict[str, Any] = (
            {"num_candidates": 100, "oversample": 3.0}
            if engine == "elasticsearch"
            else {"ef_search": 100, "oversample": 3.0}
        )
        prefix = "es_default" if engine == "elasticsearch" else "os_default"
        for case in (k10_cases[0], k10_cases[4]):
            cname = f"{prefix}_{case['name']}"
            frames_oob = build_query_frames(
                engine,
                collection,
                tenant,
                queries_f32,
                10,
                case,
                oob_profile,
                es_index_type,
                os_index_type,
            )
            serial_oob = run_serial_and_recall(
                engine,
                http,
                search_url,
                content_type,
                api_key,
                frames_oob,
                gt_map[case["gt_key"]],
                k=10,
                max_queries=max_serial_queries,
            )
            c32_oob = run_concurrent_qps(
                engine, search_url, content_type, api_key, frames_oob, 32, warmup_sec, duration_sec
            )
            sweep_out["high_recall_k10"][cname] = {
                "profile": oob_profile,
                "serial_c1": serial_oob,
                "concurrent_c32": c32_oob,
            }
            print(
                f"  [{phase_label}][oob-k=10][{cname:15s}] recall@10={serial_oob['recall_at_10']:.4f} | "
                f"c=1 p50={serial_oob['p50_ms']:.2f}ms | c=32 QPS={c32_oob['qps']:.1f}",
                flush=True,
            )

    if engine in ("elasticsearch", "opensearch"):
        if engine == "elasticsearch":
            ultra_profile = (
                {"num_candidates": 1000, "oversample": 20.0}
                if es_index_type == "bbq_hnsw"
                else {"num_candidates": 1000}
            )
        else:
            ultra_profile = (
                {"ef_search": 1000, "oversample": 20.0}
                if os_index_type == "faiss_on_disk"
                else {"ef_search": 1000}
            )
        frames_u = build_query_frames(
            engine,
            collection,
            tenant,
            queries_f32,
            10,
            k10_cases[4],
            ultra_profile,
            es_index_type,
            os_index_type,
        )
        serial_u = run_serial_and_recall(
            engine,
            http,
            search_url,
            content_type,
            api_key,
            frames_u,
            gt_map["label_1p"],
            k=10,
            max_queries=max_serial_queries,
        )
        c32_u = run_concurrent_qps(
            engine, search_url, content_type, api_key, frames_u, 32, warmup_sec, duration_sec
        )
        sweep_out["high_recall_k10"]["label_1p_nc1000"] = {
            "profile": ultra_profile,
            "serial_c1": serial_u,
            "concurrent_c32": c32_u,
        }
        print(
            f"  [{phase_label}][nc=1000][label_1p       ] recall@10={serial_u['recall_at_10']:.4f} | "
            f"c=1 p50={serial_u['p50_ms']:.2f}ms | c=32 QPS={c32_u['qps']:.1f}",
            flush=True,
        )

    print(f"=== [{phase_label}] Running VectorDBBench Parity Cases (k=100) ===", flush=True)
    for case in (k10_cases[0], k10_cases[4], k10_cases[6]):
        cname = case["name"]
        k_eff = min(100, len(gt_map[case["gt_key"]][0]))
        frames = build_query_frames(
            engine,
            collection,
            tenant,
            queries_f32,
            k_eff,
            case,
            vdb_k100_profile,
            es_index_type,
            os_index_type,
        )
        serial = run_serial_and_recall(
            engine,
            http,
            search_url,
            content_type,
            api_key,
            frames,
            gt_map[case["gt_key"]],
            k=k_eff,
            max_queries=max_serial_queries,
        )
        c32 = run_concurrent_qps(
            engine, search_url, content_type, api_key, frames, 32, warmup_sec, duration_sec
        )
        sweep_out["vdbbench_k100"][cname] = {
            "k": k_eff,
            "profile": vdb_k100_profile,
            "serial_c1": serial,
            "concurrent_c32": c32,
        }
        print(
            f"  [{phase_label}][k={k_eff}][{cname:15s}] recall@{k_eff}={serial[f'recall_at_{k_eff}']:.4f} | "
            f"c=1 p95={serial['p95_ms']:.2f}ms | c=32 QPS={c32['qps']:.1f}",
            flush=True,
        )

    if engine == "massengine":
        hi_k100_profile = {"nprobe": 52, "rerank_pool": 384}
        for case in (k10_cases[0], k10_cases[4]):
            cname = f"{case['name']}_hi98"
            k_eff = min(100, len(gt_map[case["gt_key"]][0]))
            frames_h = build_query_frames(
                engine, collection, tenant, queries_f32, k_eff, case, hi_k100_profile, es_index_type
            )
            serial_h = run_serial_and_recall(
                engine,
                http,
                search_url,
                content_type,
                api_key,
                frames_h,
                gt_map[case["gt_key"]],
                k=k_eff,
                max_queries=max_serial_queries,
            )
            c32_h = run_concurrent_qps(
                engine, search_url, content_type, api_key, frames_h, 32, warmup_sec, duration_sec
            )
            sweep_out["vdbbench_k100"][cname] = {
                "k": k_eff,
                "profile": hi_k100_profile,
                "serial_c1": serial_h,
                "concurrent_c32": c32_h,
            }
            print(
                f"  [{phase_label}][k={k_eff}][{cname:15s}] recall@{k_eff}={serial_h[f'recall_at_{k_eff}']:.4f} | "
                f"c=1 p95={serial_h['p95_ms']:.2f}ms | c=32 QPS={c32_h['qps']:.1f}",
                flush=True,
            )

    return sweep_out


def run_streaming_phase(
    engine: str,
    base_url: str,
    collection: str,
    tenant: str,
    api_key: str,
    dim: int,
    base_doc_id: int,
    queries_f32: np.ndarray,
    es_index_type: str,
    target_wps: int = 1000,
    phase_half_sec: float = 30.0,
    os_index_type: str = "faiss_fp16",
) -> dict[str, Any]:
    """
    Runs paced streaming writes (default 1,000 docs/sec in batches of 250 every 250ms)
    on top of the loaded index while 16 concurrent search workers execute:
      - Window 1 (phase_half_sec): Unfiltered (100%) k=10 search
      - Window 2 (phase_half_sec): Selective (1% label_1p) k=10 search
    """
    total_stream_sec = phase_half_sec * 2.0 + 4.0
    batch_docs = max(25, target_wps // 4)
    interval_sec = batch_docs / float(target_wps)
    total_batches = int(math.ceil(total_stream_sec / interval_sec))

    rng = np.random.default_rng(20261113)
    stream_vecs = rng.standard_normal((min(4000, batch_docs * 16), dim)).astype(np.float32)
    stream_vecs /= np.maximum(np.linalg.norm(stream_vecs, axis=1, keepdims=True), 1e-12)
    stream_cats = np.asarray([(i % 10) + 1 for i in range(stream_vecs.shape[0])], dtype="<u2")

    write_stats: dict[str, Any] = {"written_docs": 0, "batch_lats_ms": [], "errors": []}
    stop_evt = threading.Event()

    def writer_loop() -> None:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        wpool = urllib3.PoolManager(
            num_pools=2,
            maxsize=4,
            headers=headers,
            timeout=urllib3.Timeout(connect=10.0, read=120.0),
        )
        t_start = time.perf_counter()
        cur_id = base_doc_id + 1
        b_idx = 0
        try:
            while not stop_evt.is_set() and b_idx < total_batches:
                target_t = t_start + b_idx * interval_sec
                now = time.perf_counter()
                if target_t > now:
                    time.sleep(target_t - now)
                v_off = (b_idx * batch_docs) % (stream_vecs.shape[0] - batch_docs + 1)
                vecs_b = stream_vecs[v_off : v_off + batch_docs]
                cats_b = stream_cats[v_off : v_off + batch_docs]
                ids_b = np.arange(cur_id, cur_id + batch_docs, dtype="<u8")
                cur_id += batch_docs

                wt0 = time.perf_counter()
                if engine == "massengine":
                    payload = pack_meb1_batch(
                        tenant.encode("utf-8"),
                        collection.encode("utf-8"),
                        vecs_b,
                        ids_b,
                        cats_b,
                    )
                    r = wpool.request(
                        "POST",
                        f"{base_url}/v1/ingest",
                        body=payload,
                        headers={**headers, "Content-Type": "application/octet-stream"},
                    )
                    if r.status != 200:
                        raise RuntimeError(f"Stream write HTTP {r.status}: {r.data[:200]!r}")
                else:
                    parts: list[bytes] = []
                    for j in range(batch_docs):
                        did = int(ids_b[j])
                        parts.append(f'{{"index":{{"_id":"{did}"}}}}'.encode("ascii"))
                        parts.append(
                            json_dumps_bytes(
                                {"doc_id": did, "cat_id": str(int(cats_b[j])), "emb": vecs_b[j]},
                                numpy_opt=True,
                            )
                        )
                    r = wpool.request(
                        "POST",
                        f"{base_url}/{collection}/_bulk?filter_path=errors",
                        body=b"\n".join(parts) + b"\n",
                        headers={"Content-Type": "application/x-ndjson"},
                    )
                    if r.status != 200:
                        raise RuntimeError(f"ES stream write HTTP {r.status}: {r.data[:200]!r}")
                wt1 = time.perf_counter()
                write_stats["written_docs"] += batch_docs
                write_stats["batch_lats_ms"].append((wt1 - wt0) * 1000.0)
                b_idx += 1
        except Exception as exc:
            write_stats["errors"].append(str(exc))
        finally:
            wpool.clear()

    search_url = (
        f"{base_url}/v1/search" if engine == "massengine" else f"{base_url}/{collection}/_search"
    )
    content_type = "application/octet-stream" if engine == "massengine" else "application/json"
    if engine == "massengine":
        std_k10: dict[str, Any] = {"nprobe": 20, "rerank_pool": 128}
    elif engine == "elasticsearch":
        if es_index_type == "bbq_hnsw":
            std_k10 = {"num_candidates": 250, "oversample": 10.0}
        else:
            std_k10 = {"num_candidates": 100}
    else:
        if os_index_type == "faiss_on_disk":
            std_k10 = {"ef_search": 250, "oversample": 10.0}
        else:
            std_k10 = {"ef_search": 100}

    frames_unfiltered = build_query_frames(
        engine,
        collection,
        tenant,
        queries_f32,
        10,
        {"name": "unfiltered_100p"},
        std_k10,
        es_index_type,
        os_index_type,
    )
    frames_label1p = build_query_frames(
        engine,
        collection,
        tenant,
        queries_f32,
        10,
        {"name": "label_1p", "cat_id": 6},
        std_k10,
        es_index_type,
        os_index_type,
    )

    w_thread = threading.Thread(target=writer_loop, daemon=True)
    t_wall0 = time.perf_counter()
    w_thread.start()
    time.sleep(1.5)  # let live writes begin before search measurement

    live_unfiltered = run_concurrent_qps(
        engine,
        search_url,
        content_type,
        api_key,
        frames_unfiltered,
        concurrency=16,
        warmup_sec=1.0,
        duration_sec=phase_half_sec - 1.0,
    )
    live_label_1p = run_concurrent_qps(
        engine,
        search_url,
        content_type,
        api_key,
        frames_label1p,
        concurrency=16,
        warmup_sec=1.0,
        duration_sec=phase_half_sec - 1.0,
    )

    stop_evt.set()
    w_thread.join(timeout=15.0)
    t_wall1 = time.perf_counter()

    if write_stats["errors"]:
        raise RuntimeError(f"Streaming writer failed: {write_stats['errors'][0]}")

    wlats = np.asarray(write_stats["batch_lats_ms"], dtype=np.float64)
    return {
        "target_writes_per_sec": target_wps,
        "achieved_writes_per_sec": round(write_stats["written_docs"] / max(0.001, t_wall1 - t_wall0), 1),
        "total_streamed_docs": int(write_stats["written_docs"]),
        "write_batch_p50_ms": round(float(np.percentile(wlats, 50)), 2) if len(wlats) else 0.0,
        "write_batch_p99_ms": round(float(np.percentile(wlats, 99)), 2) if len(wlats) else 0.0,
        "live_search_unfiltered_c16": live_unfiltered,
        "live_search_label_1p_c16": live_label_1p,
    }


# ---------------------------------------------------------------------------
# Synthetic Self-Test Dataset Generator (for fast local verification)
# ---------------------------------------------------------------------------
def generate_synthetic_staged_dir(out_dir: str, num_docs: int = 4000, dim: int = 64) -> None:
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(12345)
    vecs = rng.standard_normal((num_docs, dim)).astype(np.float32)
    vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)
    doc_ids = np.arange(1, num_docs + 1, dtype="<u8")

    # Assign categories with realistic skew matching Cohere labels
    cats = np.full(num_docs, 10, dtype="<u2")
    for i in range(num_docs):
        r = i % 1000
        if r < 500:
            cats[i] = 1  # 50%
        elif r < 600:
            cats[i] = 3  # 10%
        elif r < 650:
            cats[i] = 4  # 5%
        elif r < 660:
            cats[i] = 6  # 1%
        elif r == 660:
            cats[i] = 9  # 0.1%

    rec_dtype = get_rec_dtype(dim)
    shards_meta = []
    per_shard = num_docs // 2
    for s in range(2):
        lo, hi = s * per_shard, (s + 1) * per_shard
        recs = np.empty(hi - lo, dtype=rec_dtype)
        recs["doc_id"] = doc_ids[lo:hi]
        recs["cat_id"] = cats[lo:hi]
        recs["vdb_id"] = (doc_ids[lo:hi] - 1).astype("<i8")
        recs["vec"] = vecs[lo:hi]
        fn = f"shard_{s:02d}.mbin"
        with open(os.path.join(out_dir, fn), "wb") as f:
            f.write(MAGIC_MBIN)
            f.write(struct.pack("<II", hi - lo, dim))
            f.write(recs.tobytes())
        shards_meta.append({"shard_idx": s, "num_rows": hi - lo, "mbin_file": fn})

    num_q = 60
    qvecs = rng.standard_normal((num_q, dim)).astype(np.float32)
    qvecs /= np.maximum(np.linalg.norm(qvecs, axis=1, keepdims=True), 1e-12)
    scores = qvecs @ vecs.T  # exact dot product [num_q, num_docs]

    int_min_doc_id = int(num_docs * 0.95) + 1

    def topk_for_mask(mask: np.ndarray) -> list[list[int]]:
        idx_pool = np.nonzero(mask)[0]
        sub_scores = scores[:, idx_pool]
        k_lim = min(100, len(idx_pool))
        out = []
        for qi in range(num_q):
            order = np.argsort(-sub_scores[qi])[:k_lim]
            out.append([int(doc_ids[idx_pool[o]]) for o in order])
        return out

    gt_obj = {
        "dataset": f"Synthetic-{num_docs}x{dim}",
        "total_records": num_docs,
        "dim": dim,
        "shards": shards_meta,
        "queries": [{"query_id": i, "vec": qvecs[i].tolist()} for i in range(num_q)],
        "int_range_min_doc_id": int_min_doc_id,
        "ground_truth": {
            "unfiltered_100p": topk_for_mask(np.ones(num_docs, dtype=bool)),
            "label_50p": topk_for_mask(cats == 1),
            "label_10p": topk_for_mask(cats == 3),
            "label_5p": topk_for_mask(cats == 4),
            "label_1p": topk_for_mask(cats == 6),
            "label_0_1p": topk_for_mask(cats == 9),
            "int_range_1p": topk_for_mask(doc_ids >= int_min_doc_id),
        },
    }
    with open(os.path.join(out_dir, "ground_truth_cohere_10m_full.json"), "w") as f:
        json.dump(gt_obj, f)


# ---------------------------------------------------------------------------
# Main End-to-End Orchestration
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["massengine", "elasticsearch", "opensearch"], required=True)
    ap.add_argument("--es-index-type", choices=["bbq_hnsw", "int8_hnsw"], default="bbq_hnsw")
    ap.add_argument("--os-index-type", choices=["faiss_fp16", "faiss_on_disk"], default="faiss_fp16")
    ap.add_argument("--os-memory-optimized", choices=["true", "false"], default="false")
    ap.add_argument("--os-index-threads", type=int, default=16)
    ap.add_argument("--es-shards", type=int, default=4)
    ap.add_argument("--me-shards", type=int, default=8)
    ap.add_argument("--url", required=True)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--tenant", default="vdbbench")
    ap.add_argument("--collection", default="cohere10m")
    ap.add_argument("--staged-dir", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--ingest-workers", type=int, default=16)
    ap.add_argument("--batch-size", type=int, default=0)
    ap.add_argument("--slice-rows", type=int, default=25000)
    ap.add_argument("--warmup-sec", type=float, default=2.0)
    ap.add_argument("--duration-sec", type=float, default=12.0)
    ap.add_argument("--max-serial-queries", type=int, default=500)
    ap.add_argument("--stream-half-sec", type=float, default=30.0)
    ap.add_argument("--stream-wps", type=int, default=1000)
    ap.add_argument("--ssh-host", default="")
    ap.add_argument("--ssh-key", default="")
    ap.add_argument("--generate-synthetic", type=int, default=0)
    ap.add_argument("--synthetic-dim", type=int, default=64)
    args = ap.parse_args()

    if args.generate_synthetic > 0:
        generate_synthetic_staged_dir(
            args.staged_dir, num_docs=args.generate_synthetic, dim=args.synthetic_dim
        )

    gt_path = os.path.join(args.staged_dir, "ground_truth_cohere_10m_full.json")
    with open(gt_path, "rb") as f:
        meta = json_loads_bytes(f.read())

    total_records = int(meta["total_records"])
    dim = int(meta["dim"])
    queries_f32 = np.asarray([q["vec"] for q in meta["queries"]], dtype="<f4")
    gt_map: dict[str, Any] = dict(meta["ground_truth"])
    if "int_range_min_doc_id" in meta:
        gt_map["int_range_min_doc_id"] = int(meta["int_range_min_doc_id"])

    base_url = args.url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    http = urllib3.PoolManager(
        num_pools=4,
        maxsize=32,
        headers=headers,
        timeout=urllib3.Timeout(connect=10.0, read=1800.0),
    )

    batch_size = args.batch_size or (4096 if args.engine == "massengine" else 1000)
    collection = args.collection.lower()
    os_mem_opt = args.os_memory_optimized == "true"

    # 0. Drop & recreate target collection / index
    mode_desc = (
        args.es_index_type
        if args.engine == "elasticsearch"
        else (
            f"{args.os_index_type},mem_opt={os_mem_opt}"
            if args.engine == "opensearch"
            else "int8"
        )
    )
    print(
        f"=== Preparing {args.engine} ({mode_desc}) collection '{collection}' at {base_url} ===",
        flush=True,
    )
    if args.engine == "massengine":
        for p in (
            f"/v1/tenants/{args.tenant}/databases/{collection}",
            f"/v1/databases/{collection}",
        ):
            http.request("DELETE", f"{base_url}{p}", headers=headers)
        create_body = {
            "num_shards": args.me_shards,
            "rf": 1,
            "mode": "distributed" if args.me_shards > 1 else "single",
            "data_type": "int8",
        }
        r = http.request(
            "PUT",
            f"{base_url}/v1/tenants/{args.tenant}/databases/{collection}",
            body=json_dumps_bytes(create_body),
            headers={**headers, "Content-Type": "application/json"},
        )
        if r.status not in (200, 409):
            r = http.request(
                "PUT",
                f"{base_url}/v1/databases/{collection}",
                body=json_dumps_bytes({"data_type": "int8"}),
                headers={**headers, "Content-Type": "application/json"},
            )
            if r.status not in (200, 409):
                raise RuntimeError(f"MassEngine create db failed ({r.status}): {r.data!r}")
    elif args.engine == "elasticsearch":
        http.request("DELETE", f"{base_url}/{collection}")
        idx_opts: dict[str, Any] = {
            "type": args.es_index_type,
            "m": 16,
            "ef_construction": 200,
        }
        if args.es_index_type == "bbq_hnsw":
            idx_opts["rescore_vector"] = {"oversample": 3.0}
        es_mapping = {
            "settings": {
                "index.number_of_shards": args.es_shards,
                "index.number_of_replicas": 0,
                "index.mapping.exclude_source_vectors": True,
                "index.refresh_interval": "-1",
                "index.store.preload": ["vex", "veq", "veb", "vem", "vemq", "vemb"],
                "index.merge.intra_merge_parallelism_enabled": True,
                "index.merge.scheduler.auto_throttle": False,
                "index.merge.scheduler.max_thread_count": 8,
            },
            "mappings": {
                "properties": {
                    "doc_id": {"type": "long"},
                    "cat_id": {"type": "keyword"},
                    "emb": {
                        "type": "dense_vector",
                        "dims": dim,
                        "index": True,
                        "similarity": "dot_product",
                        "index_options": idx_opts,
                    },
                }
            },
        }
        r = http.request(
            "PUT",
            f"{base_url}/{collection}",
            body=json_dumps_bytes(es_mapping),
            headers={"Content-Type": "application/json"},
        )
        if r.status != 200:
            raise RuntimeError(f"ES create index failed ({r.status}): {r.data!r}")
    else:
        # OpenSearch 3.x + FAISS peak-optimized configuration
        r_cs = http.request(
            "PUT",
            f"{base_url}/_cluster/settings",
            body=json_dumps_bytes(
                {
                    "persistent": {
                        "knn.algo_param.index_thread_qty": args.os_index_threads,
                        "knn.memory.circuit_breaker.limit": "70%",
                    }
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        if r_cs.status != 200:
            raise RuntimeError(f"OpenSearch cluster settings failed ({r_cs.status}): {r_cs.data!r}")
        http.request("POST", f"{base_url}/_plugins/_knn/clear_cache/{collection}")
        http.request("DELETE", f"{base_url}/{collection}")

        os_settings: dict[str, Any] = {
            "index.knn": True,
            "index.knn.derived_source.enabled": True,
            "index.number_of_shards": args.es_shards,
            "index.number_of_replicas": 0,
            "index.refresh_interval": "-1",
            "index.merge.scheduler.max_thread_count": 8,
        }
        if args.os_index_type == "faiss_on_disk":
            emb_mapping: dict[str, Any] = {
                "type": "knn_vector",
                "dimension": dim,
                "space_type": "innerproduct",
                "data_type": "float",
                "mode": "on_disk",
                "compression_level": "32x",
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "parameters": {"m": 16, "ef_construction": 200},
                },
            }
        else:
            os_settings["index.knn.memory_optimized_search"] = os_mem_opt
            emb_mapping = {
                "type": "knn_vector",
                "dimension": dim,
                "method": {
                    "name": "hnsw",
                    "space_type": "innerproduct",
                    "engine": "faiss",
                    "parameters": {
                        "m": 16,
                        "ef_construction": 200,
                        "encoder": {
                            "name": "sq",
                            "parameters": {"bits": 16, "type": "fp16", "clip": False},
                        },
                    },
                },
            }

        os_mapping = {
            "settings": os_settings,
            "mappings": {
                "properties": {
                    "doc_id": {"type": "long"},
                    "cat_id": {"type": "keyword"},
                    "emb": emb_mapping,
                }
            },
        }
        r = http.request(
            "PUT",
            f"{base_url}/{collection}",
            body=json_dumps_bytes(os_mapping),
            headers={"Content-Type": "application/json"},
        )
        if r.status != 200:
            raise RuntimeError(f"OpenSearch create index failed ({r.status}): {r.data!r}")

    # 1. Phase 1: Bulk Ingest
    tasks: list[tuple[str, int, int, int]] = []
    for sh in meta["shards"]:
        mbin_path = os.path.join(args.staged_dir, sh["mbin_file"])
        nrows = int(sh["num_rows"])
        for start in range(0, nrows, args.slice_rows):
            tasks.append((mbin_path, start, min(nrows, start + args.slice_rows), dim))

    ingest_cfg = {
        "engine": args.engine,
        "url": base_url,
        "api_key": args.api_key,
        "tenant": args.tenant,
        "collection": collection,
        "batch_size": batch_size,
    }

    print(
        f"=== Phase 1: Bulk Ingesting {total_records:,} x {dim}-d vectors "
        f"({len(tasks)} slices, {args.ingest_workers} workers, batch={batch_size}) ===",
        flush=True,
    )
    t_ingest_0 = time.perf_counter()
    done_docs = 0
    total_retries = 0
    ctx = mp.get_context("spawn")
    with ctx.Pool(
        processes=args.ingest_workers,
        initializer=_init_ingest_worker,
        initargs=(ingest_cfg,),
    ) as pool:
        last_log = t_ingest_0
        for sent, retries in pool.imap_unordered(_ingest_slice_worker, tasks):
            done_docs += sent
            total_retries += retries
            now = time.perf_counter()
            if now - last_log >= 15.0 or done_docs == total_records:
                elapsed = now - t_ingest_0
                print(
                    f"  [ingest] {done_docs:,}/{total_records:,} docs "
                    f"({done_docs / max(0.001, elapsed):,.0f} docs/s, elapsed={elapsed:.1f}s, retries={total_retries})",
                    flush=True,
                )
                last_log = now
    t_ingest_1 = time.perf_counter()
    ingest_wall_sec = t_ingest_1 - t_ingest_0

    # Make searchable (Flush on MassEngine; enable 1s refresh + _refresh on ES/OS + k-NN warmup on OS)
    t_vis_0 = time.perf_counter()
    knn_warmup_post_ingest_sec = 0.0
    if args.engine == "massengine":
        r = http.request("POST", f"{base_url}/v1/flush", headers=headers)
        if r.status not in (200, 403):
            raise RuntimeError(f"MassEngine flush failed ({r.status}): {r.data!r}")
    else:
        r_set = http.request(
            "PUT",
            f"{base_url}/{collection}/_settings",
            body=json_dumps_bytes({"index.refresh_interval": "1s"}),
            headers={"Content-Type": "application/json"},
        )
        if r_set.status != 200:
            raise RuntimeError(f"{args.engine} update settings failed ({r_set.status}): {r_set.data!r}")
        r_ref = http.request("POST", f"{base_url}/{collection}/_refresh")
        if r_ref.status != 200:
            raise RuntimeError(f"{args.engine} refresh failed ({r_ref.status}): {r_ref.data!r}")
        r_cnt = http.request("GET", f"{base_url}/{collection}/_count")
        got_cnt = int(json_loads_bytes(r_cnt.data)["count"])
        if got_cnt != total_records:
            raise RuntimeError(
                f"{args.engine} doc count mismatch: expected {total_records}, got {got_cnt}"
            )
        if args.engine == "opensearch":
            tw0 = time.perf_counter()
            r_wu = http.request("GET", f"{base_url}/_plugins/_knn/warmup/{collection}")
            if r_wu.status != 200:
                raise RuntimeError(f"OpenSearch k-NN warmup failed ({r_wu.status}): {r_wu.data!r}")
            knn_warmup_post_ingest_sec = time.perf_counter() - tw0
    t_vis_1 = time.perf_counter()
    visibility_wall_sec = t_vis_1 - t_vis_0

    telemetry_post_ingest = collect_node_telemetry(
        args.engine,
        http,
        base_url,
        collection,
        args.api_key,
        args.ssh_host or None,
        args.ssh_key or None,
    )
    print(
        f"[Phase 1 Done] ingest={ingest_wall_sec:.2f}s + flush/refresh/warmup={visibility_wall_sec:.2f}s "
        f"({total_records / (ingest_wall_sec + visibility_wall_sec):,.0f} docs/s) | "
        f"telemetry={json.dumps(telemetry_post_ingest)}",
        flush=True,
    )

    # 2. Phase 2: Pre-ForceMerge Search Sweep (Realistic Post-Ingest Production State)
    sweep_post_ingest = run_full_sweep(
        "post_ingest",
        args.engine,
        http,
        base_url,
        collection,
        args.tenant,
        args.api_key,
        queries_f32,
        gt_map,
        args.es_index_type,
        args.warmup_sec,
        args.duration_sec,
        args.max_serial_queries,
        args.os_index_type,
    )

    # 3. Phase 3: Explicit ForceMerge (max_num_segments=1 on ES/OS, /v1/compact on MassEngine)
    print(f"\n=== Phase 3: Running Explicit Optimize / ForceMerge(1) on {args.engine} ===", flush=True)
    t_opt_0 = time.perf_counter()
    knn_warmup_post_optimize_sec = 0.0
    if args.engine == "massengine":
        r_cmp = http.request("POST", f"{base_url}/v1/compact", headers=headers)
        if r_cmp.status not in (200, 403):
            raise RuntimeError(f"MassEngine compact failed ({r_cmp.status}): {r_cmp.data!r}")
    else:
        if args.engine == "opensearch" and args.os_index_type == "faiss_fp16" and not os_mem_opt:
            # Evict pre-merge off-heap FAISS segment graphs before merging into 1 segment/shard
            http.request("POST", f"{base_url}/_plugins/_knn/clear_cache/{collection}")
        r_fm = http.request(
            "POST",
            f"{base_url}/{collection}/_forcemerge?max_num_segments=1&wait_for_completion=false",
        )
        if r_fm.status != 200:
            raise RuntimeError(f"{args.engine} forcemerge trigger failed ({r_fm.status}): {r_fm.data!r}")
        task_id = json_loads_bytes(r_fm.data)["task"]
        print(f"  [forcemerge] Started {args.engine} task {task_id}...", flush=True)
        last_fm_log = t_opt_0
        while True:
            r_tk = http.request("GET", f"{base_url}/_tasks/{task_id}")
            if r_tk.status != 200:
                raise RuntimeError(f"{args.engine} task poll failed ({r_tk.status}): {r_tk.data!r}")
            tk_body = json_loads_bytes(r_tk.data)
            if tk_body.get("completed"):
                if tk_body.get("error"):
                    raise RuntimeError(f"{args.engine} forcemerge task failed: {tk_body['error']}")
                break
            now = time.perf_counter()
            if now - last_fm_log >= 30.0:
                r_seg = http.request("GET", f"{base_url}/_cat/segments/{collection}?format=json")
                seg_n = len(json_loads_bytes(r_seg.data)) if r_seg.status == 200 else -1
                print(
                    f"  [forcemerge] Still merging... elapsed={now - t_opt_0:.1f}s, active_segments={seg_n}",
                    flush=True,
                )
                last_fm_log = now
            time.sleep(3.0)
        http.request("POST", f"{base_url}/{collection}/_refresh")
        if args.engine == "opensearch":
            tw1 = time.perf_counter()
            r_wu2 = http.request("GET", f"{base_url}/_plugins/_knn/warmup/{collection}")
            if r_wu2.status != 200:
                raise RuntimeError(
                    f"OpenSearch post-merge k-NN warmup failed ({r_wu2.status}): {r_wu2.data!r}"
                )
            knn_warmup_post_optimize_sec = time.perf_counter() - tw1
    t_opt_1 = time.perf_counter()
    optimize_wall_sec = t_opt_1 - t_opt_0

    telemetry_post_optimize = collect_node_telemetry(
        args.engine,
        http,
        base_url,
        collection,
        args.api_key,
        args.ssh_host or None,
        args.ssh_key or None,
    )
    print(
        f"[Phase 3 Optimize Done] optimize_wall_sec={optimize_wall_sec:.2f}s | "
        f"total_build_plus_merge_sec={ingest_wall_sec + visibility_wall_sec + optimize_wall_sec:.2f}s | "
        f"telemetry={json.dumps(telemetry_post_optimize)}",
        flush=True,
    )

    sweep_post_optimize = run_full_sweep(
        "post_optimize",
        args.engine,
        http,
        base_url,
        collection,
        args.tenant,
        args.api_key,
        queries_f32,
        gt_map,
        args.es_index_type,
        args.warmup_sec,
        args.duration_sec,
        args.max_serial_queries,
        args.os_index_type,
    )

    # 4. Phase 4: Live Streaming Read+Write (1,000 writes/s + 16 search workers)
    print(
        f"\n=== Phase 4: Running Live Streaming Read+Write ({args.stream_wps} writes/s + c=16 search) ===",
        flush=True,
    )
    streaming_results = run_streaming_phase(
        args.engine,
        base_url,
        collection,
        args.tenant,
        args.api_key,
        dim,
        total_records,
        queries_f32,
        args.es_index_type,
        target_wps=args.stream_wps,
        phase_half_sec=args.stream_half_sec,
        os_index_type=args.os_index_type,
    )
    telemetry_post_streaming = collect_node_telemetry(
        args.engine,
        http,
        base_url,
        collection,
        args.api_key,
        args.ssh_host or None,
        args.ssh_key or None,
    )
    print(
        f"[Phase 4 Done] achieved_wps={streaming_results['achieved_writes_per_sec']} | "
        f"live_unfiltered_qps={streaming_results['live_search_unfiltered_c16']['qps']} | "
        f"live_label_1p_qps={streaming_results['live_search_label_1p_c16']['qps']}",
        flush=True,
    )

    report = {
        "benchmark": "Cohere-10M Apples-to-Apples Head-to-Head",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "label": args.label,
        "engine": args.engine,
        "es_index_type": args.es_index_type if args.engine == "elasticsearch" else None,
        "os_index_type": args.os_index_type if args.engine == "opensearch" else None,
        "os_memory_optimized": os_mem_opt if args.engine == "opensearch" else None,
        "dataset": meta["dataset"],
        "total_records": total_records,
        "dim": dim,
        "ingest": {
            "ingest_wall_sec": round(ingest_wall_sec, 2),
            "visibility_wall_sec": round(visibility_wall_sec, 2),
            "knn_warmup_post_ingest_sec": round(knn_warmup_post_ingest_sec, 2),
            "searchable_wall_sec": round(ingest_wall_sec + visibility_wall_sec, 2),
            "searchable_docs_per_sec": round(
                total_records / max(0.001, ingest_wall_sec + visibility_wall_sec), 1
            ),
            "optimize_forcemerge_wall_sec": round(optimize_wall_sec, 2),
            "knn_warmup_post_optimize_sec": round(knn_warmup_post_optimize_sec, 2),
            "total_ready_merged_wall_sec": round(
                ingest_wall_sec + visibility_wall_sec + optimize_wall_sec, 2
            ),
            "total_ready_merged_docs_per_sec": round(
                total_records
                / max(0.001, ingest_wall_sec + visibility_wall_sec + optimize_wall_sec),
                1,
            ),
            "bulk_retries": total_retries,
        },
        "telemetry": {
            "post_ingest": telemetry_post_ingest,
            "post_optimize": telemetry_post_optimize,
            "post_streaming": telemetry_post_streaming,
        },
        "search_post_ingest": sweep_post_ingest,
        "search_post_optimize": sweep_post_optimize,
        "streaming_read_write": streaming_results,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    with open(args.out_json, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n=== Saved complete benchmark report to {args.out_json} ===", flush=True)
    http.clear()


if __name__ == "__main__":
    main()
