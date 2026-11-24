#!/usr/bin/env python3
import argparse
import heapq
import json
import os
import struct
import subprocess
import time

import h5py
import numpy as np


def download_file(url: str, dst: str) -> None:
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return
    tmp = dst + ".part"
    cmd = ["curl", "-fL", "--retry", "5", "--retry-delay", "2", "-o", tmp, url]
    subprocess.run(cmd, check=True)
    os.replace(tmp, dst)


def normalize_rows(arr: np.ndarray) -> np.ndarray:
    x = np.asarray(arr, dtype=np.float32)
    if not np.all(np.isfinite(x)):
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms = np.maximum(norms, np.float32(1e-12))
    return np.ascontiguousarray(x / norms, dtype="<f4")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--max-queries", type=int, default=1000)
    args = ap.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)
    hdf5_path = os.path.join(args.work_dir, f"{args.name}.hdf5")
    fbin_path = os.path.join(args.work_dir, "base.fbin")
    gt_path = os.path.join(args.work_dir, "gt.json")

    if os.path.exists(fbin_path) and os.path.exists(gt_path):
        print(f"[stage] Reusing staged {args.name} in {args.work_dir}")
        return

    t0 = time.time()
    print(f"[stage] Downloading {args.name} from {args.url}...")
    download_file(args.url, hdf5_path)
    print(f"[stage] Downloaded {hdf5_path} ({os.path.getsize(hdf5_path)/(1<<30):.2f} GiB) in {time.time()-t0:.1f}s")

    with h5py.File(hdf5_path, "r") as f:
        train_ds = f["train"]
        n_docs, dim = train_ds.shape
        test_raw = f["test"][: args.max_queries]
        neighbors_raw = f["neighbors"][: args.max_queries]

        queries = normalize_rows(test_raw)
        num_q = queries.shape[0]
        q_t = np.ascontiguousarray(queries.T, dtype=np.float32)
        q0 = np.ascontiguousarray(queries[0], dtype=np.float32)

        # Accumulate exact brute-force top-10 for cat_id == 1 (row_idx % 100 == 0)
        cat1p_top = [([], []) for _ in range(num_q)]  # list of (scores, ids) kept at top-10
        cat1p_scores = np.full((num_q, 10), -1e9, dtype=np.float32)
        cat1p_ids = np.zeros((num_q, 10), dtype=np.uint64)

        # Exact brute-force top-10 for query 0 across all unfiltered docs (ground-truth sanity check)
        q0_scores = np.full(10, -1e9, dtype=np.float32)
        q0_ids = np.zeros(10, dtype=np.uint64)

        chunk_size = 250_000
        tmp_fbin = fbin_path + ".tmp"
        with open(tmp_fbin, "wb") as out:
            out.write(struct.pack("<II", n_docs, dim))
            for lo in range(0, n_docs, chunk_size):
                hi = min(lo + chunk_size, n_docs)
                vecs = normalize_rows(train_ds[lo:hi])
                out.write(vecs.tobytes())

                # Verify unfiltered query 0 exact inner products
                s0 = vecs @ q0
                k_take = min(10, s0.shape[0])
                top_local = np.argpartition(s0, -k_take)[-k_take:]
                cand_scores = np.concatenate([q0_scores, s0[top_local]])
                cand_ids = np.concatenate([q0_ids, (lo + top_local + 1).astype(np.uint64)])
                keep = np.argpartition(cand_scores, -10)[-10:]
                order = keep[np.argsort(-cand_scores[keep])]
                q0_scores = cand_scores[order]
                q0_ids = cand_ids[order]

                # Exact 1% filtered top-10 (row_idx % 100 == 0 => cat_id == 1)
                first_mod = (100 - (lo % 100)) % 100
                filt_local = np.arange(first_mod, hi - lo, 100, dtype=np.int64)
                if filt_local.size > 0:
                    fvecs = vecs[filt_local]
                    fids = (lo + filt_local + 1).astype(np.uint64)
                    # scores shape: (num_q, n_filt)
                    sim = (fvecs @ q_t).T
                    k_f = min(10, sim.shape[1])
                    if k_f == sim.shape[1]:
                        merged_s = np.concatenate([cat1p_scores, sim], axis=1)
                        merged_id = np.concatenate(
                            [cat1p_ids, np.broadcast_to(fids, (num_q, k_f))], axis=1
                        )
                    else:
                        part = np.argpartition(sim, -k_f, axis=1)[:, -k_f:]
                        rows_ix = np.arange(num_q)[:, None]
                        merged_s = np.concatenate([cat1p_scores, sim[rows_ix, part]], axis=1)
                        merged_id = np.concatenate([cat1p_ids, fids[part]], axis=1)
                    top10_ix = np.argpartition(merged_s, -10, axis=1)[:, -10:]
                    rows_ix = np.arange(num_q)[:, None]
                    cat1p_scores = merged_s[rows_ix, top10_ix]
                    cat1p_ids = merged_id[rows_ix, top10_ix]

        os.replace(tmp_fbin, fbin_path)

        # Sort cat1p_ids descending by score
        order_all = np.argsort(-cat1p_scores, axis=1)
        rows_ix = np.arange(num_q)[:, None]
        cat1p_ids = cat1p_ids[rows_ix, order_all]

        gt_q0 = set(int(x) + 1 for x in neighbors_raw[0, :10])
        bf_q0 = set(int(x) for x in q0_ids)
        overlap = len(gt_q0 & bf_q0) / 10.0
        print(f"[stage] {args.name}: N={n_docs:,} D={dim} Q={num_q} | Q0 brute-force vs HDF5 GT@10 overlap={overlap:.2f}")
        if overlap < 0.90:
            raise RuntimeError(f"Ground-truth overlap check failed for {args.name}: overlap={overlap:.2f} < 0.90 (gt={sorted(gt_q0)}, bf={sorted(bf_q0)})")

        gt_unfiltered = (neighbors_raw[:, :100].astype(np.int64) + 1).tolist()
        gt_obj = {
            "dataset": args.name,
            "num_vectors": int(n_docs),
            "dim": int(dim),
            "num_queries": int(num_q),
            "queries": queries.tolist(),
            "gt_unfiltered_top100": gt_unfiltered,
            "gt_cat1p_top10": cat1p_ids.tolist(),
        }
        tmp_gt = gt_path + ".tmp"
        with open(tmp_gt, "w", encoding="utf-8") as gf:
            json.dump(gt_obj, gf)
        os.replace(tmp_gt, gt_path)

    os.remove(hdf5_path)
    print(f"[stage] Staged {args.name} cleanly (removed raw HDF5) in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
