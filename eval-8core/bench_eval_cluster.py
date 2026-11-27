#!/usr/bin/env python3
"""Self-contained 8-core MassEngine cluster evaluation benchmark.

Generates deterministic clustered unit vectors + structured JSON metadata with
exact brute-force Recall@10 verification, runs bulk ingest, compaction, serial and
concurrent unfiltered / 1%-filtered / hybrid-BM25 search sweeps, and optional
zero-downtime RF>=2 node drain/uncordon verification.

Requires only Python 3.9+ stdlib (uses NumPy if available for faster vector math).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def api_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: Any = None,
    timeout: float = 120.0,
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {api_key}"}
    data: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise HttpError(exc.code, err_body) from exc


def generate_dataset(
    num_vectors: int, dim: int, num_queries: int, seed: int = 42
) -> tuple[list[list[float]], list[list[float]], list[list[int]], list[list[int]]]:
    """Generate deterministic clustered L2-normalized vectors + exact top-10 GT."""
    num_clusters = 64
    if np is not None:
        rng = np.random.default_rng(seed)
        centroids = rng.standard_normal((num_clusters, dim), dtype=np.float32)
        centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-12)

        cluster_ids = np.arange(num_vectors) % num_clusters
        noise = rng.standard_normal((num_vectors, dim), dtype=np.float32) * 0.18
        vecs = centroids[cluster_ids] + noise
        vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)

        q_cids = np.arange(num_queries) % num_clusters
        q_noise = rng.standard_normal((num_queries, dim), dtype=np.float32) * 0.18
        queries = centroids[q_cids] + q_noise
        queries /= np.maximum(np.linalg.norm(queries, axis=1, keepdims=True), 1e-12)

        # Compute exact ground truth on up to first 50 queries for Recall@10 verification
        gt_count = min(50, num_queries)
        q_gt = queries[:gt_count]
        sims = q_gt @ vecs.T  # (gt_count, num_vectors)
        k_eval = min(10, num_vectors)
        unf_idx = np.argsort(-sims, axis=1)[:, :k_eval]

        cat1_mask = (np.arange(num_vectors) % 100) == 0
        cat1_indices = np.flatnonzero(cat1_mask)
        if cat1_indices.size > 0:
            sims_f = sims[:, cat1_indices]
            kf = min(10, cat1_indices.size)
            f_local = np.argsort(-sims_f, axis=1)[:, :kf]
            f_idx = cat1_indices[f_local]
        else:
            f_idx = np.zeros((gt_count, 0), dtype=np.int64)

        return (
            vecs.tolist(),
            queries.tolist(),
            (unf_idx + 1).tolist(),
            (f_idx + 1).tolist(),
        )

    # Pure-Python fallback when NumPy is unavailable
    py_rng = random.Random(seed)

    def _norm(v: list[float]) -> list[float]:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        inv = 1.0 / n
        return [round(x * inv, 6) for x in v]

    centroids = [
        _norm([py_rng.gauss(0.0, 1.0) for _ in range(dim)])
        for _ in range(num_clusters)
    ]
    vecs = [
        _norm([centroids[i % num_clusters][d] + py_rng.gauss(0.0, 0.18) for d in range(dim)])
        for i in range(num_vectors)
    ]
    queries = [
        _norm([centroids[i % num_clusters][d] + py_rng.gauss(0.0, 0.18) for d in range(dim)])
        for i in range(num_queries)
    ]
    gt_count = min(50, num_queries)
    gt_unf: list[list[int]] = []
    gt_cat1: list[list[int]] = []
    for q in queries[:gt_count]:
        scored = []
        scored_f = []
        for idx, v in enumerate(vecs):
            dot = sum(a * b for a, b in zip(q, v))
            scored.append((dot, idx + 1))
            if idx % 100 == 0:
                scored_f.append((dot, idx + 1))
        scored.sort(key=lambda t: -t[0])
        scored_f.sort(key=lambda t: -t[0])
        gt_unf.append([doc for _, doc in scored[:10]])
        gt_cat1.append([doc for _, doc in scored_f[:10]])
    return vecs, queries, gt_unf, gt_cat1


def percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(math.ceil(pct * len(sorted_vals))) - 1))
    return round(sorted_vals[idx], 3)


def summarize_ms(vals: list[float]) -> dict[str, float]:
    s = sorted(vals)
    return {
        "p50_ms": percentile(s, 0.50),
        "p95_ms": percentile(s, 0.95),
        "p99_ms": percentile(s, 0.99),
        "mean_ms": round(statistics.mean(s), 3) if s else 0.0,
    }


def extract_hit_int_ids(hits: list[dict[str, Any]]) -> list[int]:
    out: list[int] = []
    for h in hits:
        raw_id = h.get("id", "")
        if isinstance(raw_id, str) and raw_id.startswith("eval-"):
            try:
                out.append(int(raw_id.split("-", 1)[1]))
                continue
            except ValueError:
                pass
        if isinstance(h.get("doc_id"), int):
            out.append(int(h["doc_id"]))
    return out


def run_search_phase(
    base_url: str,
    api_key: str,
    tenant: str,
    database: str,
    queries: list[list[float]],
    gt_top10: list[list[int]] | None,
    nprobe: int,
    rerank_pool: int,
    conc_list: list[int],
    duration_sec: float,
    category: int | None = None,
    query_text: str | None = None,
    hybrid_alpha: float | None = None,
) -> dict[str, Any]:
    def _build_req(qvec: list[float]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "tenant": tenant,
            "database": database,
            "vector": qvec,
            "k": 10,
            "nprobe": nprobe,
            "rerank_pool": rerank_pool,
            "skip_meta": True,
        }
        if category is not None:
            body["category"] = category
        if query_text is not None:
            body["query_text"] = query_text
        if hybrid_alpha is not None:
            body["hybrid_alpha"] = hybrid_alpha
        return body

    # Warmup (20 queries)
    for qi in range(min(20, len(queries))):
        api_json(base_url, api_key, "POST", "/v1/search", _build_req(queries[qi]))

    # Serial latency + Recall@10 verification
    serial_ms: list[float] = []
    recalls: list[float] = []
    for qi, qvec in enumerate(queries):
        t0 = time.perf_counter()
        resp = api_json(base_url, api_key, "POST", "/v1/search", _build_req(qvec))
        elapsed = (time.perf_counter() - t0) * 1000.0
        serial_ms.append(float(resp.get("took_ms", elapsed)) if resp.get("took_ms") is not None else elapsed)
        if gt_top10 is not None and qi < len(gt_top10) and gt_top10[qi]:
            got = set(extract_hit_int_ids(resp.get("hits", []))[:10])
            exp = set(gt_top10[qi][:10])
            recalls.append(len(got & exp) / float(len(exp)))

    sweep: list[dict[str, Any]] = []
    peak_qps = 0.0
    for conc in conc_list:
        stop_at = time.perf_counter() + duration_sec
        per_worker_lat: list[list[float]] = [[] for _ in range(conc)]
        errors = 0
        err_lock = threading.Lock()

        def _worker(wid: int) -> None:
            nonlocal errors
            local: list[float] = []
            seq = wid * 31
            nq = len(queries)
            while time.perf_counter() < stop_at:
                qvec = queries[seq % nq]
                seq += 1
                q0 = time.perf_counter()
                try:
                    api_json(base_url, api_key, "POST", "/v1/search", _build_req(qvec))
                    local.append((time.perf_counter() - q0) * 1000.0)
                except Exception:
                    with err_lock:
                        errors += 1
            per_worker_lat[wid] = local

        t_start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as pool:
            futs = [pool.submit(_worker, w) for w in range(conc)]
            for fut in futs:
                fut.result()
        wall = max(time.perf_counter() - t_start, 1e-6)
        all_lats = [x for sub in per_worker_lat for x in sub]
        qps = round(len(all_lats) / wall, 1)
        if qps > peak_qps:
            peak_qps = qps
        sweep.append(
            {
                "concurrency": conc,
                "qps": qps,
                "errors": errors,
                **summarize_ms(all_lats),
            }
        )

    out: dict[str, Any] = {
        "serial": summarize_ms(serial_ms),
        "peak_qps": peak_qps,
        "conc_sweep": sweep,
    }
    if recalls:
        out["recall_at_10"] = round(statistics.mean(recalls), 4)
    return out


def verify_ha_drain(
    base_url: str,
    api_key: str,
    tenant: str,
    database: str,
    queries: list[list[float]],
    nprobe: int,
    rerank_pool: int,
) -> dict[str, Any]:
    """Drain node-0 while running live traffic, verify 0 errors, then uncordon + reconcile."""
    stop_flag = threading.Event()
    in_drain = threading.Event()
    total_ok = 0
    total_err = 0
    during_drain_ok = 0
    count_lock = threading.Lock()

    def _traffic() -> None:
        nonlocal total_ok, total_err, during_drain_ok
        seq = 0
        while not stop_flag.is_set():
            qvec = queries[seq % len(queries)]
            seq += 1
            try:
                api_json(
                    base_url,
                    api_key,
                    "POST",
                    "/v1/search",
                    {
                        "tenant": tenant,
                        "database": database,
                        "vector": qvec,
                        "k": 10,
                        "nprobe": nprobe,
                        "rerank_pool": rerank_pool,
                        "skip_meta": True,
                    },
                )
                with count_lock:
                    total_ok += 1
                    if in_drain.is_set():
                        during_drain_ok += 1
            except Exception:
                with count_lock:
                    total_err += 1
            time.sleep(0.001)

    workers = [threading.Thread(target=_traffic, daemon=True) for _ in range(4)]
    for t in workers:
        t.start()

    time.sleep(0.15)
    drain_resp = api_json(base_url, api_key, "POST", "/v1/nodes/0/drain", {})
    in_drain.set()
    time.sleep(0.4)
    in_drain.clear()
    uncordon_resp = api_json(base_url, api_key, "POST", "/v1/nodes/0/uncordon", {})
    reconcile_resp = api_json(base_url, api_key, "POST", "/v1/reconcile", {})

    stop_flag.set()
    for t in workers:
        t.join(timeout=10.0)

    nodes_after = api_json(base_url, api_key, "GET", "/v1/nodes")
    all_healthy = bool(nodes_after.get("ready")) and all(
        n.get("status") == "healthy" and not n.get("fenced_shards")
        for n in nodes_after.get("nodes", [])
    )
    return {
        "drained": bool(drain_resp.get("drained")),
        "uncordoned": bool(uncordon_resp.get("uncordoned")),
        "repaired_replicas": int(reconcile_resp.get("repaired_replicas", 0)),
        "queries_succeeded": total_ok,
        "queries_during_drain": during_drain_ok,
        "queries_failed": total_err,
        "cluster_healthy_after": all_healthy,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="MassEngine 8-Core Evaluation Cluster Benchmark")
    ap.add_argument("--url", default=os.environ.get("MASSENGINE_URL", "http://127.0.0.1:8080"))
    ap.add_argument("--api-key", default=os.environ.get("MASSENGINE_API_KEY", ""))
    ap.add_argument("--tenant", default="eval-bench")
    ap.add_argument("--database", default="eval_1024d")
    ap.add_argument("--dim", type=int, default=1024)
    ap.add_argument("--vectors", type=int, default=100_000)
    ap.add_argument("--queries", type=int, default=200)
    ap.add_argument("--shards", type=int, default=8)
    ap.add_argument("--rf", type=int, default=0, help="0 = auto min(2, node_count)")
    ap.add_argument("--data-type", default="int8")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--nprobe", type=int, default=24)
    ap.add_argument("--rerank-pool", type=int, default=96)
    ap.add_argument("--conc-list", default="1,8,16")
    ap.add_argument("--conc-duration", type=float, default=5.0)
    ap.add_argument("--verify-ha-drain", action="store_true")
    ap.add_argument("--keep-db", action="store_true")
    ap.add_argument("--out", default="eval_report.json")
    args = ap.parse_args()

    if not args.api_key:
        print("ERROR: --api-key or MASSENGINE_API_KEY is required.", file=sys.stderr)
        return 2

    conc_list = [int(x.strip()) for x in args.conc_list.split(",") if x.strip()]
    health = api_json(args.url, args.api_key, "GET", "/v1/health")
    nodes_info = api_json(args.url, args.api_key, "GET", "/v1/nodes")
    lic_info = api_json(args.url, args.api_key, "GET", "/v1/license")

    node_count = max(1, len(nodes_info.get("nodes", [])))
    rf = args.rf if args.rf > 0 else min(2, node_count)
    print(
        f"Cluster ready={nodes_info.get('ready')} health={health.get('status')} "
        f"version={nodes_info.get('coordinator_version')} nodes={node_count} "
        f"licensed_cores={lic_info.get('licensed_cores')} tier={lic_info.get('tier')} "
        f"-> using shards={args.shards} rf={rf}"
    )

    print(f"Generating {args.vectors:,} x {args.dim}-d vectors + exact ground truth...")
    vecs, queries, gt_unf, gt_cat1 = generate_dataset(args.vectors, args.dim, args.queries)

    try:
        api_json(
            args.url,
            args.api_key,
            "DELETE",
            f"/v1/tenants/{args.tenant}/databases/{args.database}",
        )
    except HttpError:
        pass

    api_json(
        args.url,
        args.api_key,
        "POST",
        "/v1/databases",
        {
            "tenant": args.tenant,
            "database": args.database,
            "num_shards": args.shards,
            "rf": rf,
            "data_type": args.data_type,
        },
    )

    # Parallel batch ingest
    epoch_day = max(1, min(65535, int(time.time() // 86400)))
    batches: list[list[dict[str, Any]]] = []
    for start in range(0, args.vectors, args.batch_size):
        end = min(start + args.batch_size, args.vectors)
        docs = [
            {
                "id": f"eval-{i + 1}",
                "category": (i % 100) + 1,
                "date": epoch_day,
                "vector": vecs[i],
                "metadata": {
                    "env": "prod" if i % 2 == 0 else "staging",
                    "group": i % 20,
                    "summary": f"vector benchmark record {i + 1} cluster node storage",
                },
            }
            for i in range(start, end)
        ]
        batches.append(docs)

    def _send_batch(docs: list[dict[str, Any]]) -> int:
        api_json(
            args.url,
            args.api_key,
            "POST",
            "/v1/ingest",
            {"tenant": args.tenant, "database": args.database, "docs": docs},
            timeout=180.0,
        )
        return len(docs)

    t_ing0 = time.perf_counter()
    ingested = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for count in pool.map(_send_batch, batches):
            ingested += count
    pure_ingest_sec = max(time.perf_counter() - t_ing0, 1e-6)

    t_flush0 = time.perf_counter()
    api_json(args.url, args.api_key, "POST", "/v1/flush", {}, timeout=300.0)
    flush_sec = time.perf_counter() - t_flush0

    t_cmp0 = time.perf_counter()
    api_json(args.url, args.api_key, "POST", "/v1/compact", {}, timeout=600.0)
    compact_sec = time.perf_counter() - t_cmp0
    total_load_sec = pure_ingest_sec + flush_sec + compact_sec

    unf = run_search_phase(
        args.url,
        args.api_key,
        args.tenant,
        args.database,
        queries,
        gt_unf,
        args.nprobe,
        args.rerank_pool,
        conc_list,
        args.conc_duration,
    )
    cat1 = run_search_phase(
        args.url,
        args.api_key,
        args.tenant,
        args.database,
        queries,
        gt_cat1,
        args.nprobe,
        args.rerank_pool,
        conc_list,
        args.conc_duration,
        category=1,
    )
    hybrid = run_search_phase(
        args.url,
        args.api_key,
        args.tenant,
        args.database,
        queries,
        None,
        args.nprobe,
        args.rerank_pool,
        conc_list,
        args.conc_duration,
        query_text="storage cluster",
        hybrid_alpha=0.65,
    )

    ha_result: dict[str, Any] | None = None
    if args.verify_ha_drain:
        if node_count < 2 or rf < 2:
            print("WARNING: Skipping --verify-ha-drain (requires >= 2 nodes and RF >= 2).")
        else:
            ha_result = verify_ha_drain(
                args.url,
                args.api_key,
                args.tenant,
                args.database,
                queries,
                args.nprobe,
                args.rerank_pool,
            )

    if not args.keep_db:
        try:
            api_json(
                args.url,
                args.api_key,
                "DELETE",
                f"/v1/tenants/{args.tenant}/databases/{args.database}",
            )
        except HttpError:
            pass

    report: dict[str, Any] = {
        "cluster_version": nodes_info.get("coordinator_version", ""),
        "nodes": node_count,
        "shards": args.shards,
        "rf": rf,
        "licensed_cores": lic_info.get("licensed_cores", 0),
        "data_type": args.data_type,
        "vectors": ingested,
        "dim": args.dim,
        "ingest": {
            "pure_ingest_sec": round(pure_ingest_sec, 2),
            "flush_sec": round(flush_sec, 2),
            "compact_sec": round(compact_sec, 2),
            "total_load_sec": round(total_load_sec, 2),
            "pure_docs_per_sec": round(ingested / pure_ingest_sec, 1),
            "effective_docs_per_sec": round(ingested / total_load_sec, 1),
        },
        "search_unfiltered": unf,
        "search_filtered_1pct": cat1,
        "search_hybrid_bm25": hybrid,
    }
    if ha_result is not None:
        report["ha_drain_verification"] = ha_result

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    print("\n=== MassEngine 8-Core Evaluation Summary ===")
    print(
        f"Ingest: {ingested:,} x {args.dim}-d ({args.data_type}) | "
        f"pure={report['ingest']['pure_docs_per_sec']:.0f} docs/s | "
        f"total(flush+compact)={report['ingest']['effective_docs_per_sec']:.0f} docs/s"
    )
    print(
        f"Unfiltered kNN: Recall@10={unf.get('recall_at_10')} | "
        f"serial p50={unf['serial']['p50_ms']}ms p99={unf['serial']['p99_ms']}ms | "
        f"peak={unf['peak_qps']} QPS"
    )
    print(
        f"1% Filtered kNN: Recall@10={cat1.get('recall_at_10')} | "
        f"serial p50={cat1['serial']['p50_ms']}ms p99={cat1['serial']['p99_ms']}ms | "
        f"peak={cat1['peak_qps']} QPS"
    )
    print(
        f"Hybrid RRF+BM25: serial p50={hybrid['serial']['p50_ms']}ms p99={hybrid['serial']['p99_ms']}ms | "
        f"peak={hybrid['peak_qps']} QPS"
    )
    if ha_result is not None:
        print(
            f"HA Drain Check: ok={ha_result['queries_succeeded']} "
            f"failed={ha_result['queries_failed']} healthy_after={ha_result['cluster_healthy_after']}"
        )
    if args.out:
        print(f"Saved JSON report to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
