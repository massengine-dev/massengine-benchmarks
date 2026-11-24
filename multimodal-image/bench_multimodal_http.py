#!/usr/bin/env python3
"""Reproducible HTTP driver for multimodal/visual embedding datasets staged by stage_hdf5.py.

Benchmarks MassEngine over POST /v1/ingest (MEB1 binary framing) and POST /v1/search
(MES1 binary framing) across int8, float16, and int4 precision tiers, computing exact
Recall@10, NDCG@10, serial p50/p95/p99 latency, and multi-client QPS sweeps.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import statistics
import struct
import time
import urllib.request
from typing import Any

import numpy as np
import urllib3

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

_MEB1_HEADER = struct.Struct("<4sHHHII")
_MES1_HEADER = struct.Struct("<4sHHHHIIIII")
_MESR_HEADER = struct.Struct("<4sHHII")
_U16 = struct.Struct("<H")

PROFILES = [
    ("fast", 12, 48, 0, True),
    ("balanced", 24, 96, 0, True),
    ("high_1", 48, 192, 0, True),
    ("high_2", 96, 384, 0, True),
    ("ultra_1", 160, 640, 0, False),
    ("ultra_2", 256, 1024, 0, True),
    ("filt_1p_1", 64, 256, 1, True),
    ("filt_1p_2", 128, 512, 1, True),
]


def pack_meb1(
    tenant_b: bytes,
    db_b: bytes,
    vecs_f32: np.ndarray,
    ids_u64: np.ndarray,
    cats_u16: np.ndarray,
) -> bytes:
    count, dim = vecs_f32.shape
    flags = 1 | (1 << 2)
    hdr = _MEB1_HEADER.pack(b"MEB1", flags, len(tenant_b), len(db_b), count, dim)
    return b"".join(
        [
            hdr,
            tenant_b,
            db_b,
            np.ascontiguousarray(vecs_f32, dtype="<f4").tobytes(),
            np.ascontiguousarray(ids_u64, dtype="<u8").tobytes(),
            np.ascontiguousarray(cats_u16, dtype="<u2").tobytes(),
        ]
    )


def pack_mes1(
    tenant_b: bytes,
    db_b: bytes,
    qvec: np.ndarray,
    k: int,
    nprobe: int,
    rerank_pool: int,
    category: int = 0,
) -> bytes:
    flags = (1 << 0) | (1 << 1) | (1 << 8)
    trailer = b""
    if category > 0:
        flags |= 1 << 4
        trailer = _U16.pack(category)
    hdr = _MES1_HEADER.pack(
        b"MES1",
        flags,
        len(tenant_b),
        len(db_b),
        0,
        int(qvec.shape[0]),
        k,
        nprobe,
        rerank_pool,
        0,
    )
    return hdr + tenant_b + db_b + np.ascontiguousarray(qvec, dtype="<f4").tobytes() + trailer


def unpack_mesr_ids(raw: bytes) -> list[int]:
    magic, _, _, cnt, _ = _MESR_HEADER.unpack_from(raw, 0)
    if magic != b"MESR":
        raise RuntimeError(f"Unexpected MESR magic: {magic!r}")
    if cnt == 0:
        return []
    return np.frombuffer(raw, dtype="<u8", count=cnt, offset=16).tolist()


def calc_metrics10(hits: list[int], gt: list[int]) -> tuple[float, float]:
    k = min(10, len(gt))
    if k == 0:
        return 0.0, 0.0
    gt_set = set(gt[:k])
    idcg = sum(1.0 / math.log2(i + 2) for i in range(k))
    match = 0
    dcg = 0.0
    for i, hid in enumerate(hits[:k]):
        if hid in gt_set:
            match += 1
            dcg += 1.0 / math.log2(i + 2)
    return match / float(k), (dcg / idcg if idcg > 0 else 0.0)


def pct(sorted_ms: list[float], q: float) -> float:
    if not sorted_ms:
        return 0.0
    idx = min(len(sorted_ms) - 1, max(0, int(math.ceil(q * len(sorted_ms))) - 1))
    return round(sorted_ms[idx], 2)


def http_json(http: urllib3.PoolManager, base_url: str, api_key: str, method: str, path: str, body: Any = None) -> Any:
    headers = {"Authorization": f"Bearer {api_key}"}
    raw = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        raw = json.dumps(body).encode("utf-8")
    resp = http.request(method, f"{base_url}{path}", body=raw, headers=headers)
    if resp.status >= 400:
        raise RuntimeError(f"{method} {path} -> HTTP {resp.status}: {resp.data[:250]!r}")
    return json.loads(resp.data.decode("utf-8")) if resp.data else {}


def run_dtype(
    base_url: str,
    api_key: str,
    stage_dir: str,
    gt: dict[str, Any],
    dtype: str,
    shards: int,
    rf: int,
    workers: int,
    batch_size: int,
    sweep_sec: float,
) -> dict[str, Any]:
    tenant = "imgbench"
    db_name = f"{gt['dataset'].replace('-', '_')}_{dtype}"
    tenant_b = tenant.encode("utf-8")
    db_b = db_name.encode("utf-8")

    http = urllib3.PoolManager(
        num_pools=4,
        maxsize=max(64, workers * 2),
        timeout=urllib3.Timeout(connect=10.0, read=600.0),
    )

    try:
        http_json(http, base_url, api_key, "DELETE", f"/v1/tenants/{tenant}/databases/{db_name}")
    except RuntimeError:
        pass

    http_json(
        http,
        base_url,
        api_key,
        "POST",
        "/v1/databases",
        {
            "tenant": tenant,
            "database": db_name,
            "num_shards": shards,
            "rf": rf,
            "data_type": dtype,
            "append_only": True,
        },
    )

    fbin_path = os.path.join(stage_dir, "base.fbin")
    with open(fbin_path, "rb") as f:
        n_docs, raw_dim = struct.unpack("<II", f.read(8))
    vecs_mm = np.memmap(fbin_path, dtype="<f4", mode="r", offset=8, shape=(n_docs, raw_dim))

    pad_dim = raw_dim if raw_dim % 64 == 0 else ((raw_dim + 63) // 64) * 64
    queries_np = np.asarray(gt["queries"], dtype="<f4")
    if pad_dim != raw_dim:
        q_pad = np.zeros((queries_np.shape[0], pad_dim), dtype="<f4")
        q_pad[:, :raw_dim] = queries_np
        queries_np = q_pad

    ranges = [(lo, min(lo + 50_000, n_docs)) for lo in range(0, n_docs, 50_000)]

    def _send_range(r: tuple[int, int]) -> int:
        lo, hi = r
        h = urllib3.PoolManager(num_pools=2, maxsize=4, timeout=urllib3.Timeout(connect=10.0, read=600.0))
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/octet-stream"}
        try:
            for s in range(lo, hi, batch_size):
                e = min(s + batch_size, hi)
                sub = np.asarray(vecs_mm[s:e], dtype="<f4")
                if pad_dim != raw_dim:
                    padded = np.zeros((e - s, pad_dim), dtype="<f4")
                    padded[:, :raw_dim] = sub
                    sub = padded
                idx_arr = np.arange(s, e, dtype=np.uint64)
                ids_u64 = idx_arr + 1
                cats_u16 = np.where((idx_arr % 100) == 0, 1, (idx_arr % 99) + 2).astype("<u2")
                payload = pack_meb1(tenant_b, db_b, sub, ids_u64, cats_u16)
                resp = h.request("POST", f"{base_url}/v1/ingest", body=payload, headers=headers)
                if resp.status != 200:
                    raise RuntimeError(f"MEB1 ingest error {resp.status}: {resp.data[:200]!r}")
        finally:
            h.clear()
        return hi - lo

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        sum(pool.map(_send_range, ranges))
    pure_sec = round(time.perf_counter() - t0, 2)

    tf = time.perf_counter()
    http_json(http, base_url, api_key, "POST", "/v1/flush", {})
    flush_sec = round(time.perf_counter() - tf, 2)

    tc = time.perf_counter()
    http_json(http, base_url, api_key, "POST", "/v1/compact", {})
    compact_sec = round(time.perf_counter() - tc, 2)
    total_sec = round(pure_sec + flush_sec + compact_sec, 2)

    profiles_out: list[dict[str, Any]] = []
    search_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/octet-stream"}
    gt_unf = gt["gt_unfiltered_top100"]
    gt_cat1 = gt["gt_cat1p_top10"]
    nq = len(queries_np)

    for pname, nprobe, rr, cat_id, run_sweep in PROFILES:
        if cat_id > 0 and dtype != "int8":
            continue
        payloads = [pack_mes1(tenant_b, db_b, queries_np[i], 10, nprobe, rr, cat_id) for i in range(nq)]
        for i in range(min(50, nq)):
            http.request("POST", f"{base_url}/v1/search", body=payloads[i], headers=search_headers)

        serial_ms: list[float] = []
        r_sum = 0.0
        n_sum = 0.0
        cur_gt = gt_cat1 if cat_id > 0 else gt_unf
        for i in range(nq):
            q0 = time.perf_counter()
            resp = http.request("POST", f"{base_url}/v1/search", body=payloads[i], headers=search_headers)
            serial_ms.append((time.perf_counter() - q0) * 1000.0)
            if resp.status != 200:
                raise RuntimeError(f"MES1 search error {resp.status}: {resp.data[:200]!r}")
            hits = unpack_mesr_ids(resp.data)
            r10, n10 = calc_metrics10(hits, cur_gt[i])
            r_sum += r10
            n_sum += n10

        serial_sorted = sorted(serial_ms)
        prof: dict[str, Any] = {
            "name": pname,
            "nprobe": nprobe,
            "rerank_pool": rr,
            "filter": "cat_1p" if cat_id > 0 else "unfiltered",
            "recall_at_10": round(r_sum / nq, 4),
            "ndcg_at_10": round(n_sum / nq, 4),
            "serial_p50_ms": pct(serial_sorted, 0.50),
            "serial_p95_ms": pct(serial_sorted, 0.95),
            "serial_p99_ms": pct(serial_sorted, 0.99),
        }

        if run_sweep:
            sweep: list[dict[str, Any]] = []
            peak_qps = 0.0
            for conc in (1, 8, 16, 32, 64):
                stop_at = time.perf_counter() + sweep_sec

                def _sw(wid: int) -> list[float]:
                    local: list[float] = []
                    seq = wid * 97
                    while time.perf_counter() < stop_at:
                        p = payloads[seq % nq]
                        seq += 1
                        s0 = time.perf_counter()
                        r = http.request("POST", f"{base_url}/v1/search", body=p, headers=search_headers)
                        if r.status == 200:
                            local.append((time.perf_counter() - s0) * 1000.0)
                    return local

                t_s = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as pool:
                    all_lats = [x for sub in pool.map(_sw, range(conc)) for x in sub]
                wall = max(time.perf_counter() - t_s, 1e-6)
                all_lats.sort()
                qps = round(len(all_lats) / wall, 1)
                if qps > peak_qps:
                    peak_qps = qps
                    prof["peak_qps"] = qps
                    prof["peak_p50_ms"] = pct(all_lats, 0.50)
                    prof["peak_p95_ms"] = pct(all_lats, 0.95)
                    prof["peak_p99_ms"] = pct(all_lats, 0.99)
                sweep.append(
                    {
                        "concurrency": conc,
                        "qps": qps,
                        "p50_ms": pct(all_lats, 0.50),
                        "p95_ms": pct(all_lats, 0.95),
                        "p99_ms": pct(all_lats, 0.99),
                    }
                )
            prof["conc_sweep"] = sweep
        profiles_out.append(prof)

    http.clear()
    return {
        "data_type": dtype,
        "num_shards": shards,
        "pure_ingest_sec": pure_sec,
        "flush_sec": flush_sec,
        "compact_sec": compact_sec,
        "total_load_sec": total_sec,
        "pure_ingest_docs_per_sec": round(n_docs / max(pure_sec, 1e-6)),
        "effective_docs_per_sec": round(n_docs / max(total_sec, 1e-6)),
        "profiles": profiles_out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Multimodal / CLIP HTTP Benchmark for MassEngine")
    ap.add_argument("--url", default=os.environ.get("MASSENGINE_URL", "http://127.0.0.1:8080"))
    ap.add_argument("--api-key", default=os.environ.get("MASSENGINE_API_KEY", ""))
    ap.add_argument("--stage-dir", required=True)
    ap.add_argument("--data-types", default="int8,float16,int4")
    ap.add_argument("--shards", type=int, default=8)
    ap.add_argument("--rf", type=int, default=1)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=2000)
    ap.add_argument("--sweep-sec", type=float, default=2.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not args.api_key:
        raise SystemExit("ERROR: --api-key or MASSENGINE_API_KEY is required.")

    base_url = args.url.rstrip("/")
    gt = json.loads(open(os.path.join(args.stage_dir, "gt.json"), encoding="utf-8").read())
    results = [
        run_dtype(
            base_url,
            args.api_key,
            args.stage_dir,
            gt,
            dt.strip(),
            args.shards,
            args.rf,
            args.workers,
            args.batch_size,
            args.sweep_sec,
        )
        for dt in args.data_types.split(",")
        if dt.strip()
    ]
    report = {
        "dataset": gt["dataset"],
        "num_vectors": gt["num_vectors"],
        "dim": gt["dim"],
        "num_queries": gt["num_queries"],
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Saved multimodal HTTP report to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
