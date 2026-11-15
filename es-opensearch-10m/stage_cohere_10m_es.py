#!/usr/bin/env python3
"""
Stages Zilliz's official VectorDBBench Cohere-10M (cohere_large_10m, 10,000,000 x 768-d)
dataset from https://assets.zilliz.com/benchmark/cohere_large_10m/ onto local NVMe:
  1. 10 binary shard files (shard_00.mbin .. shard_09.mbin) containing L2-normalized
     768-d float32 vectors, doc_id (1..10,000,000), and scalar category tag (1..10).
  2. ground_truth_cohere_10m_full.json containing:
     - 1,000 L2-normalized 768-d query vectors from test.parquet
     - Official Top-100 ground-truth neighbor doc_ids across 7 selectivity levels:
       * unfiltered_100p : neighbors.parquet (100% = 10,000,000 docs)
       * label_50p       : neighbors_labels_label_50p.parquet (50% = ~5,000,000 docs, cat_id == 1)
       * label_10p       : neighbors_labels_label_10p.parquet (10% = ~1,000,000 docs, cat_id == 3)
       * label_5p        : neighbors_labels_label_5p.parquet (5% = ~500,000 docs, cat_id == 4)
       * label_1p        : neighbors_labels_label_1p.parquet (1% = ~100,000 docs, cat_id == 6)
       * label_0_1p      : neighbors_labels_label_0.1p.parquet (0.1% = ~10,000 docs, cat_id == 9)
       * int_range_1p    : neighbors_int_99p.parquet (1% range = 100,000 docs, doc_id >= 9,900,001)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import struct
import subprocess
import time

import numpy as np
import pyarrow.parquet as pq

HTTPS_BASE = "https://assets.zilliz.com/benchmark/cohere_large_10m"
MAGIC_MBIN = b"MBIN\x01\x00\x00\x00"

LABEL_TO_CAT = {
    "label_50p": 1,
    "label_20p": 2,
    "label_10p": 3,
    "label_5p": 4,
    "label_2p": 5,
    "label_1p": 6,
    "label_0.5p": 7,
    "label_0.2p": 8,
    "label_0.1p": 9,
}


def download_asset(remote_name: str, local_path: str) -> None:
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return
    tmp_path = local_path + ".part"
    cmd = [
        "curl",
        "-fsSL",
        "--retry",
        "5",
        "--retry-delay",
        "2",
        "-o",
        tmp_path,
        f"{HTTPS_BASE}/{remote_name}",
    ]
    subprocess.run(cmd, check=True)
    os.replace(tmp_path, local_path)


def convert_shard(idx: int, raw_dir: str, out_dir: str, label_cats: np.ndarray) -> dict:
    mbin_name = f"shard_{idx:02d}.mbin"
    mbin_path = os.path.join(out_dir, mbin_name)
    pq_name = f"shuffle_train-{idx:02d}-of-10.parquet"
    pq_path = os.path.join(raw_dir, pq_name)

    if not os.path.exists(mbin_path) or os.path.getsize(mbin_path) == 0:
        t0 = time.time()
        print(f"[shard {idx:02d}] Downloading {pq_name}...", flush=True)
        download_asset(pq_name, pq_path)
        print(f"[shard {idx:02d}] Streaming & L2-normalizing {pq_name}...", flush=True)

        pf = pq.ParquetFile(pq_path)
        num_rows = int(pf.metadata.num_rows)
        rec_dtype = np.dtype(
            [
                ("doc_id", "<u8"),
                ("cat_id", "<u2"),
                ("vdb_id", "<i8"),
                ("vec", "<f4", (768,)),
            ]
        )

        tmp_mbin = mbin_path + ".tmp"
        written = 0
        with open(tmp_mbin, "wb") as f:
            f.write(MAGIC_MBIN)
            f.write(struct.pack("<II", num_rows, 768))
            for batch in pf.iter_batches(batch_size=100_000, columns=["id", "emb"]):
                b_len = batch.num_rows
                ids = batch.column(0).to_numpy(zero_copy_only=False).astype(np.int64, copy=False)
                flat_vals = (
                    batch.column(1)
                    .values.to_numpy(zero_copy_only=False)
                    .astype(np.float32, copy=False)
                )
                vecs = flat_vals.reshape((b_len, 768))
                norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                norms = np.maximum(norms, 1e-12)

                recs = np.empty(b_len, dtype=rec_dtype)
                recs["doc_id"] = (ids + 1).astype(np.uint64)
                recs["cat_id"] = label_cats[ids]
                recs["vdb_id"] = ids
                np.divide(vecs, norms, out=recs["vec"])
                f.write(recs.tobytes())
                written += b_len

        if written != num_rows:
            raise RuntimeError(f"Row count mismatch on {pq_name}: {written} != {num_rows}")
        os.replace(tmp_mbin, mbin_path)
        os.remove(pq_path)
        print(
            f"[shard {idx:02d}] Wrote {mbin_name} ({num_rows:,} rows) in {time.time() - t0:.1f}s",
            flush=True,
        )
    else:
        with open(mbin_path, "rb") as f:
            hdr = f.read(16)
            num_rows, _ = struct.unpack("<II", hdr[8:16])
        print(f"[shard {idx:02d}] Reusing existing {mbin_name} ({num_rows:,} rows)", flush=True)

    return {
        "shard_idx": idx,
        "num_rows": int(num_rows),
        "mbin_file": mbin_name,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    raw_dir = os.path.join(args.out_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    gt_json_path = os.path.join(args.out_dir, "ground_truth_cohere_10m_full.json")

    if os.path.exists(gt_json_path) and all(
        os.path.exists(os.path.join(args.out_dir, f"shard_{i:02d}.mbin")) for i in range(10)
    ):
        print(f"[stage] All 10 shards and {gt_json_path} already staged.", flush=True)
        return

    print("[stage] Downloading metadata, queries, and 7 ground-truth files...", flush=True)
    meta_files = [
        "scalar_labels.parquet",
        "test.parquet",
        "neighbors.parquet",
        "neighbors_labels_label_50p.parquet",
        "neighbors_labels_label_10p.parquet",
        "neighbors_labels_label_5p.parquet",
        "neighbors_labels_label_1p.parquet",
        "neighbors_labels_label_0.1p.parquet",
        "neighbors_int_99p.parquet",
    ]
    for mf in meta_files:
        download_asset(mf, os.path.join(raw_dir, mf))

    print("[stage] Parsing scalar_labels.parquet (10,000,000 rows)...", flush=True)
    lbl_tbl = pq.read_table(os.path.join(raw_dir, "scalar_labels.parquet"))
    lbl_ids = lbl_tbl["id"].to_numpy()
    lbl_strs = lbl_tbl["labels"].to_pylist()
    label_cats = np.full(10_000_000, 10, dtype=np.uint16)
    for row_id, s in zip(lbl_ids, lbl_strs):
        label_cats[row_id] = LABEL_TO_CAT.get(s, 10)
    del lbl_tbl, lbl_ids, lbl_strs

    cat_counts = {k: int(np.sum(label_cats == v)) for k, v in LABEL_TO_CAT.items()}
    print("[stage] Label counts:", cat_counts, flush=True)

    print(f"[stage] Staging 10 Cohere-10M shards with {args.workers} workers...", flush=True)
    shards_meta = [None] * 10
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(convert_shard, i, raw_dir, args.out_dir, label_cats): i for i in range(10)
        }
        for fut in concurrent.futures.as_completed(futs):
            i = futs[fut]
            shards_meta[i] = fut.result()

    print("[stage] Building ground_truth_cohere_10m_full.json...", flush=True)
    test_tbl = pq.read_table(os.path.join(raw_dir, "test.parquet"))
    q_ids = test_tbl["id"].to_pylist()
    q_embs_raw = test_tbl["emb"].to_pylist()
    queries = []
    for qid, qvec in zip(q_ids, q_embs_raw):
        arr = np.asarray(qvec, dtype=np.float32)
        arr = arr / max(float(np.linalg.norm(arr)), 1e-12)
        queries.append({"query_id": int(qid), "vec": [round(float(x), 7) for x in arr.tolist()]})

    def load_gt(fn: str) -> list[list[int]]:
        t = pq.read_table(os.path.join(raw_dir, fn))
        col = "neighbors_id" if "neighbors_id" in t.schema.names else t.schema.names[-1]
        rows = t[col].to_pylist()
        return [[int(x) + 1 for x in r[:100]] for r in rows]

    gt_int_1p = load_gt("neighbors_int_99p.parquet")
    if not gt_int_1p or not all(v >= 9_900_001 for v in gt_int_1p[0]):
        raise RuntimeError(
            f"Unexpected neighbors_int_99p.parquet IDs (expected >= 9,900,001): {gt_int_1p[0][:5]}"
        )

    gt_obj = {
        "dataset": "Cohere-10M (cohere_large_10m)",
        "total_records": 10_000_000,
        "dim": 768,
        "metric": "COSINE (L2-normalized dot_product)",
        "label_to_cat": LABEL_TO_CAT,
        "label_counts": cat_counts,
        "shards": shards_meta,
        "queries": queries,
        "ground_truth": {
            "unfiltered_100p": load_gt("neighbors.parquet"),
            "label_50p": load_gt("neighbors_labels_label_50p.parquet"),
            "label_10p": load_gt("neighbors_labels_label_10p.parquet"),
            "label_5p": load_gt("neighbors_labels_label_5p.parquet"),
            "label_1p": load_gt("neighbors_labels_label_1p.parquet"),
            "label_0_1p": load_gt("neighbors_labels_label_0.1p.parquet"),
            "int_range_1p": gt_int_1p,
        },
    }
    tmp_gt = gt_json_path + ".tmp"
    with open(tmp_gt, "w") as f:
        json.dump(gt_obj, f)
    os.replace(tmp_gt, gt_json_path)
    print(f"[stage] Saved {gt_json_path} successfully.", flush=True)


if __name__ == "__main__":
    main()
