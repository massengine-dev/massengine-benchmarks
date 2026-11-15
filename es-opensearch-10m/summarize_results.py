#!/usr/bin/env python3
"""
Generates a Markdown comparison summary from all completed JSON reports in a results directory.
"""

from __future__ import annotations

import argparse
import glob
import json
import os


def fmt_gib(b: int | float | None) -> str:
    if not b:
        return "-"
    return f"{float(b) / (1024**3):.2f} GiB"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--out-md", default="")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.results_dir, "*.json")))
    if not files:
        print(f"No JSON reports found in {args.results_dir}")
        return

    reports = [json.load(open(f)) for f in files]

    lines: list[str] = []
    lines.append(
        "# Cohere-10M Benchmark Summary: MassEngine vs. Elasticsearch 9.5.6 vs. OpenSearch 3.9.0 (FAISS)\n"
    )
    lines.append("## 1. Ingest, ForceMerge / Optimize Time & Resource Footprint\n")
    lines.append(
        "| Run Label | Ingest + Refresh | Optimize / ForceMerge(1) | Total Ready (1 seg/shard) | Process RSS | OS Page Cache | NVMe Disk |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|")

    for r in reports:
        lbl = r.get("label") or r["engine"]
        ing = r["ingest"]
        tel = r["telemetry"].get("post_optimize") or r["telemetry"].get("post_ingest") or {}
        lines.append(
            f"| `{lbl}` | {ing['searchable_wall_sec']:.1f}s ({ing['searchable_wall_sec']/60.0:.1f}m) "
            f"| {ing['optimize_forcemerge_wall_sec']:.1f}s ({ing['optimize_forcemerge_wall_sec']/60.0:.1f}m) "
            f"| **{ing['total_ready_merged_wall_sec']/60.0:.1f} min** ({ing['total_ready_merged_docs_per_sec']:,.0f} docs/s) "
            f"| {fmt_gib(tel.get('proc_rss_bytes'))} "
            f"| {fmt_gib(tel.get('page_cache_bytes'))} "
            f"| {fmt_gib(tel.get('nvme_data_bytes') or tel.get('store_bytes'))} |"
        )

    for state_key, state_title in (
        ("search_post_ingest", "2. Selectivity Sweep @ k=10 — Pre-ForceMerge (Post-Ingest Production State)"),
        ("search_post_optimize", "3. Selectivity Sweep @ k=10 — Post-ForceMerge (`max_num_segments=1` / Compacted)"),
    ):
        lines.append(f"\n## {state_title}\n")
        lines.append(
            "| Run Label | Case (Selectivity) | Recall@10 | Serial p50 / p95 (ms) | c=16 QPS | c=32 QPS |"
        )
        lines.append("|---|---|---:|---:|---:|---:|")
        for r in reports:
            lbl = r.get("label") or r["engine"]
            sel = r.get(state_key, {}).get("selectivity_k10", {})
            for cname, cdata in sel.items():
                s1 = cdata["serial_c1"]
                c16 = cdata["concurrent_c16"]
                c32 = cdata["concurrent_c32"]
                lines.append(
                    f"| `{lbl}` | `{cname}` ({cdata['selectivity']}) "
                    f"| {s1['recall_at_10']:.4f} "
                    f"| {s1['p50_ms']:.2f} / {s1['p95_ms']:.2f} "
                    f"| {c16['qps']:,.1f} "
                    f"| **{c32['qps']:,.1f}** |"
                )

    lines.append("\n## 3b. High-Recall & Out-of-Box Operating Points @ k=10 (Post-ForceMerge / Compacted)\n")
    lines.append(
        "| Run Label | Operating Point / Case | Profile | Recall@10 | Serial p50 / p95 (ms) | c=32 QPS |"
    )
    lines.append("|---|---|---|---:|---:|---:|")
    for r in reports:
        lbl = r.get("label") or r["engine"]
        hi = r.get("search_post_optimize", {}).get("high_recall_k10", {})
        for cname, cdata in hi.items():
            s1 = cdata["serial_c1"]
            c32 = cdata["concurrent_c32"]
            prof = json.dumps(cdata.get("profile", {}), separators=(",", ":"))
            lines.append(
                f"| `{lbl}` | `{cname}` | `{prof}` "
                f"| {s1['recall_at_10']:.4f} "
                f"| {s1['p50_ms']:.2f} / {s1['p95_ms']:.2f} "
                f"| **{c32['qps']:,.1f}** |"
            )

    lines.append("\n## 4. VectorDBBench Parity Cases @ k=100 (Post-ForceMerge / Compacted)\n")
    lines.append("| Run Label | Case | Recall@100 | Serial p95 / p99 (ms) | c=32 QPS |")
    lines.append("|---|---|---:|---:|---:|")
    for r in reports:
        lbl = r.get("label") or r["engine"]
        vdb = r.get("search_post_optimize", {}).get("vdbbench_k100", {})
        for cname, cdata in vdb.items():
            k_eff = cdata["k"]
            s1 = cdata["serial_c1"]
            c32 = cdata["concurrent_c32"]
            lines.append(
                f"| `{lbl}` | `{cname}` "
                f"| {s1[f'recall_at_{k_eff}']:.4f} "
                f"| {s1['p95_ms']:.2f} / {s1['p99_ms']:.2f} "
                f"| **{c32['qps']:,.1f}** |"
            )

    lines.append("\n## 5. Live Streaming Writes (1,000 writes/s on 10M Index) + Concurrent c=16 Search\n")
    lines.append(
        "| Run Label | Achieved Writes/s | Write Batch p99 | Live Unfiltered QPS (p95) | Live 1% Filtered QPS (p95) | Post-Stream Segments |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for r in reports:
        lbl = r.get("label") or r["engine"]
        st = r.get("streaming_read_write", {})
        u = st.get("live_search_unfiltered_c16", {})
        f1 = st.get("live_search_label_1p_c16", {})
        segs = r.get("telemetry", {}).get("post_streaming", {}).get("segment_count", "-")
        lines.append(
            f"| `{lbl}` | {st.get('achieved_writes_per_sec', 0):,.1f}/s "
            f"| {st.get('write_batch_p99_ms', 0):.1f} ms "
            f"| **{u.get('qps', 0):,.1f} QPS** ({u.get('p95_ms', 0):.2f} ms) "
            f"| **{f1.get('qps', 0):,.1f} QPS** ({f1.get('p95_ms', 0):.2f} ms) "
            f"| {segs} |"
        )

    md_text = "\n".join(lines) + "\n"
    print(md_text)
    if args.out_md:
        with open(args.out_md, "w") as f:
            f.write(md_text)


if __name__ == "__main__":
    main()
