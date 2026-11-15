# Cohere-10M Benchmark Summary: MassEngine vs. Elasticsearch 9.5.6 vs. OpenSearch 3.9.0 (FAISS)

## 1. Ingest, ForceMerge / Optimize Time & Resource Footprint

| Run Label | Ingest + Refresh | Optimize / ForceMerge(1) | Total Ready (1 seg/shard) | Process RSS | OS Page Cache | NVMe Disk |
|---|---:|---:|---:|---:|---:|---:|
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | 1321.2s (22.0m) | 549.5s (9.2m) | **31.2 min** (5,346 docs/s) | 11.35 GiB | 12.64 GiB | 30.58 GiB |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | 1425.0s (23.8m) | 1711.2s (28.5m) | **52.3 min** (3,189 docs/s) | 17.40 GiB | 8.06 GiB | 36.75 GiB |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | 93.5s (1.6m) | 110.4s (1.8m) | **3.4 min** (49,047 docs/s) | 12.57 GiB | 10.85 GiB | 11.78 GiB |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | 87.3s (1.5m) | 119.7s (2.0m) | **3.5 min** (48,292 docs/s) | 1.43 GiB | 11.97 GiB | 11.78 GiB |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | 1905.7s (31.8m) | 1973.1s (32.9m) | **64.6 min** (2,578 docs/s) | 12.93 GiB | 5.78 GiB | 44.70 GiB |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | 1405.2s (23.4m) | 1592.7s (26.5m) | **50.0 min** (3,336 docs/s) | 29.05 GiB | 17.73 GiB | 31.44 GiB |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | 1331.8s (22.2m) | 618.6s (10.3m) | **32.5 min** (5,127 docs/s) | 19.89 GiB | 30.99 GiB | 30.58 GiB |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | 1609.3s (26.8m) | 1318.0s (22.0m) | **48.8 min** (3,416 docs/s) | 26.21 GiB | 23.80 GiB | 36.75 GiB |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | 89.7s (1.5m) | 115.2s (1.9m) | **3.4 min** (48,799 docs/s) | 12.54 GiB | 12.81 GiB | 11.78 GiB |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | 2137.0s (35.6m) | 1895.2s (31.6m) | **67.2 min** (2,480 docs/s) | 38.96 GiB | 21.34 GiB | 44.70 GiB |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | 1226.2s (20.4m) | 1146.8s (19.1m) | **39.5 min** (4,214 docs/s) | 48.41 GiB | 31.88 GiB | 31.44 GiB |

## 2. Selectivity Sweep @ k=10 — Pre-ForceMerge (Post-Ingest Production State)

| Run Label | Case (Selectivity) | Recall@10 | Serial p50 / p95 (ms) | c=16 QPS | c=32 QPS |
|---|---|---:|---:|---:|---:|
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `unfiltered_100p` (100%) | 0.9194 | 23.41 / 45.70 | 163.7 | **185.4** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_50p` (50%) | 0.9108 | 29.58 / 47.86 | 122.8 | **129.4** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_10p` (10%) | 0.9128 | 32.68 / 51.70 | 107.4 | **112.2** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_5p` (5%) | 0.8796 | 31.33 / 50.62 | 108.6 | **110.3** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p` (1%) | 0.8558 | 42.05 / 112.78 | 111.1 | **114.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_0_1p` (0.1%) | 1.0000 | 25.05 / 37.99 | 129.9 | **131.1** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `int_range_1p` (1% (range)) | 0.8614 | 28.54 / 60.99 | 105.9 | **107.3** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `unfiltered_100p` (100%) | 0.8378 | 29.10 / 115.65 | 176.7 | **182.0** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_50p` (50%) | 0.8316 | 22.92 / 62.66 | 136.1 | **140.4** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_10p` (10%) | 0.8408 | 22.80 / 37.98 | 130.0 | **128.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_5p` (5%) | 0.8236 | 23.02 / 39.23 | 134.2 | **130.5** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p` (1%) | 0.7554 | 23.99 / 45.48 | 111.5 | **113.1** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_0_1p` (0.1%) | 0.9222 | 17.51 / 26.21 | 208.0 | **209.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `int_range_1p` (1% (range)) | 0.7458 | 24.16 / 43.91 | 119.9 | **113.4** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p` (100%) | 0.9824 | 3.28 / 4.26 | 526.2 | **527.1** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_50p` (50%) | 0.9818 | 2.37 / 2.92 | 857.2 | **861.3** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_10p` (10%) | 0.9716 | 1.44 / 1.60 | 2,072.7 | **2,077.8** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_5p` (5%) | 0.9712 | 1.28 / 1.37 | 2,667.1 | **2,680.8** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_1p` (1%) | 0.9596 | 1.12 / 1.19 | 3,688.1 | **3,770.1** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_0_1p` (0.1%) | 0.9776 | 1.49 / 1.60 | 2,183.9 | **2,194.2** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `int_range_1p` (1% (range)) | 0.9596 | 2.02 / 4.88 | 376.0 | **376.2** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `unfiltered_100p` (100%) | 0.9822 | 9.10 / 18.93 | 456.5 | **464.3** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_50p` (50%) | 0.9842 | 3.87 / 4.86 | 760.0 | **762.7** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_10p` (10%) | 0.9748 | 2.37 / 3.75 | 1,886.8 | **1,889.7** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_5p` (5%) | 0.9726 | 1.71 / 3.03 | 2,448.7 | **2,473.6** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_1p` (1%) | 0.9656 | 1.24 / 1.83 | 3,327.2 | **3,490.6** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_0_1p` (0.1%) | 0.9762 | 1.57 / 1.75 | 2,089.2 | **2,095.2** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `int_range_1p` (1% (range)) | 0.9608 | 2.76 / 5.45 | 327.5 | **326.8** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `unfiltered_100p` (100%) | 0.8900 | 453.01 / 1162.92 | 8.0 | **8.2** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_50p` (50%) | 0.9327 | 440.42 / 860.59 | 4.2 | **3.7** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_10p` (10%) | 0.9700 | 1650.91 / 2370.12 | 0.0 | **0.0** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_5p` (5%) | 0.9913 | 2468.26 / 3741.53 | 0.0 | **0.0** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p` (1%) | 1.0000 | 128.28 / 351.79 | 137.5 | **138.5** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_0_1p` (0.1%) | 1.0000 | 1.61 / 1.87 | 2,036.5 | **2,081.5** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `int_range_1p` (1% (range)) | 1.0000 | 14.37 / 15.70 | 140.7 | **141.1** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `unfiltered_100p` (100%) | 0.9530 | 20.96 / 35.08 | 130.7 | **134.8** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_50p` (50%) | 0.9772 | 38.65 / 58.00 | 45.7 | **44.3** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_10p` (10%) | 0.9942 | 89.32 / 122.89 | 17.5 | **18.2** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_5p` (5%) | 0.9982 | 132.55 / 180.17 | 19.8 | **19.8** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p` (1%) | 0.9978 | 36.91 / 48.27 | 122.4 | **140.4** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_0_1p` (0.1%) | 1.0000 | 8.90 / 11.99 | 555.2 | **570.1** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `int_range_1p` (1% (range)) | 0.9990 | 30.34 / 43.36 | 205.5 | **209.9** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `unfiltered_100p` (100%) | 0.9200 | 20.40 / 46.81 | 166.7 | **168.7** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_50p` (50%) | 0.9172 | 17.96 / 45.99 | 118.2 | **123.4** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_10p` (10%) | 0.9149 | 25.98 / 234.08 | 86.2 | **92.9** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_5p` (5%) | 0.8862 | 29.96 / 49.85 | 132.9 | **134.9** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p` (1%) | 0.8182 | 23.07 / 42.34 | 115.1 | **115.5** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_0_1p` (0.1%) | 1.0000 | 16.13 / 25.24 | 184.5 | **187.1** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `int_range_1p` (1% (range)) | 0.8102 | 23.85 / 42.66 | 109.4 | **105.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `unfiltered_100p` (100%) | 0.8398 | 37.42 / 76.97 | 90.6 | **119.2** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_50p` (50%) | 0.8304 | 31.85 / 53.95 | 86.5 | **93.2** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_10p` (10%) | 0.8448 | 31.30 / 58.66 | 87.3 | **85.7** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_5p` (5%) | 0.8214 | 30.59 / 77.99 | 80.0 | **81.5** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p` (1%) | 0.7620 | 25.97 / 91.87 | 69.1 | **67.6** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_0_1p` (0.1%) | 0.9226 | 24.96 / 49.00 | 117.2 | **116.6** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `int_range_1p` (1% (range)) | 0.7518 | 24.97 / 86.00 | 68.4 | **73.1** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p` (100%) | 0.9836 | 3.74 / 4.75 | 462.9 | **479.2** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_50p` (50%) | 0.9824 | 2.59 / 3.14 | 764.7 | **756.9** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_10p` (10%) | 0.9760 | 1.52 / 1.68 | 1,903.2 | **1,905.9** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_5p` (5%) | 0.9748 | 1.32 / 1.47 | 2,424.2 | **2,481.6** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_1p` (1%) | 0.9624 | 1.14 / 1.22 | 3,509.6 | **3,634.8** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_0_1p` (0.1%) | 0.9758 | 1.56 / 1.79 | 2,143.7 | **2,168.5** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `int_range_1p` (1% (range)) | 0.9632 | 2.18 / 4.89 | 356.8 | **355.9** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `unfiltered_100p` (100%) | 0.9471 | 83.48 / 109.90 | 51.4 | **49.5** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_50p` (50%) | 0.9587 | 229.39 / 333.08 | 24.6 | **27.0** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_10p` (10%) | 0.9620 | 163.39 / 211.78 | 35.7 | **37.5** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_5p` (5%) | 0.9587 | 146.07 / 185.44 | 48.2 | **41.8** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p` (1%) | 0.9924 | 66.26 / 87.42 | 92.7 | **88.6** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_0_1p` (0.1%) | 1.0000 | 13.45 / 20.25 | 639.9 | **508.1** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `int_range_1p` (1% (range)) | 0.9729 | 58.41 / 71.56 | 151.5 | **153.2** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `unfiltered_100p` (100%) | 0.9412 | 29.62 / 43.92 | 95.8 | **78.9** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_50p` (50%) | 0.9581 | 58.73 / 89.00 | 33.9 | **34.6** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_10p` (10%) | 0.9802 | 108.20 / 172.54 | 12.4 | **14.2** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_5p` (5%) | 0.9840 | 124.46 / 202.65 | 17.1 | **17.8** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p` (1%) | 0.9978 | 38.30 / 50.04 | 112.0 | **113.7** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_0_1p` (0.1%) | 1.0000 | 12.60 / 18.26 | 558.7 | **599.1** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `int_range_1p` (1% (range)) | 0.9990 | 30.68 / 42.95 | 144.7 | **220.2** |

## 3. Selectivity Sweep @ k=10 — Post-ForceMerge (`max_num_segments=1` / Compacted)

| Run Label | Case (Selectivity) | Recall@10 | Serial p50 / p95 (ms) | c=16 QPS | c=32 QPS |
|---|---|---:|---:|---:|---:|
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `unfiltered_100p` (100%) | 0.9274 | 5.85 / 10.00 | 2,394.9 | **2,578.6** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_50p` (50%) | 0.9028 | 8.57 / 10.23 | 1,427.9 | **1,462.2** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_10p` (10%) | 0.8884 | 10.64 / 13.95 | 1,077.7 | **1,090.7** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_5p` (5%) | 0.8280 | 9.26 / 13.29 | 1,028.3 | **1,039.2** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p` (1%) | 0.6764 | 6.33 / 10.29 | 830.4 | **834.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_0_1p` (0.1%) | 1.0000 | 10.10 / 25.81 | 161.8 | **162.3** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `int_range_1p` (1% (range)) | 0.6880 | 6.03 / 9.78 | 837.2 | **843.6** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `unfiltered_100p` (100%) | 0.8520 | 1.87 / 3.37 | 3,396.9 | **3,732.9** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_50p` (50%) | 0.8440 | 2.14 / 2.58 | 2,171.7 | **2,253.0** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_10p` (10%) | 0.8190 | 3.00 / 3.79 | 1,430.7 | **1,457.9** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_5p` (5%) | 0.7744 | 2.26 / 2.75 | 1,853.4 | **1,894.9** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p` (1%) | 0.5876 | 2.82 / 4.90 | 1,408.9 | **1,435.9** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_0_1p` (0.1%) | 0.9234 | 1.47 / 1.71 | 3,794.9 | **4,009.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `int_range_1p` (1% (range)) | 0.5688 | 2.86 / 5.23 | 1,362.1 | **1,340.9** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p` (100%) | 0.9790 | 2.16 / 2.72 | 972.3 | **975.6** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_50p` (50%) | 0.9768 | 1.72 / 2.07 | 1,519.3 | **1,522.5** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_10p` (10%) | 0.9624 | 1.15 / 1.26 | 3,547.0 | **3,788.2** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_5p` (5%) | 0.9584 | 1.03 / 1.13 | 4,462.6 | **5,074.8** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_1p` (1%) | 0.9304 | 0.88 / 0.96 | 6,440.6 | **7,238.1** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_0_1p` (0.1%) | 0.9774 | 1.42 / 1.54 | 2,505.6 | **2,535.6** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `int_range_1p` (1% (range)) | 0.9388 | 1.28 / 1.41 | 1,040.8 | **1,046.0** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `unfiltered_100p` (100%) | 0.9790 | 2.33 / 2.95 | 914.0 | **921.1** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_50p` (50%) | 0.9768 | 1.78 / 2.17 | 1,454.5 | **1,477.3** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_10p` (10%) | 0.9624 | 1.15 / 1.32 | 3,343.8 | **3,687.8** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_5p` (5%) | 0.9584 | 1.03 / 1.15 | 4,308.5 | **4,991.8** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_1p` (1%) | 0.9304 | 0.90 / 1.02 | 6,161.8 | **7,120.2** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_0_1p` (0.1%) | 0.9774 | 1.42 / 1.56 | 2,487.2 | **2,563.7** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `int_range_1p` (1% (range)) | 0.9388 | 1.28 / 1.45 | 1,049.2 | **1,053.8** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `unfiltered_100p` (100%) | 0.8605 | 123.59 / 207.94 | 1,478.3 | **2,700.4** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_50p` (50%) | 0.8956 | 30.58 / 42.97 | 178.2 | **179.6** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_10p` (10%) | 0.9130 | 103.38 / 174.46 | 78.8 | **119.4** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_5p` (5%) | 0.9161 | 132.22 / 219.69 | 51.2 | **57.4** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p` (1%) | 1.0000 | 502.56 / 891.66 | 11.0 | **25.2** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_0_1p` (0.1%) | 1.0000 | 1.64 / 1.80 | 3,349.7 | **3,530.8** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `int_range_1p` (1% (range)) | 1.0000 | 167.91 / 268.16 | 18.2 | **28.1** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `unfiltered_100p` (100%) | 0.9154 | 13.83 / 27.52 | 1,470.3 | **1,499.0** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_50p` (50%) | 0.9300 | 19.61 / 26.37 | 209.0 | **209.9** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_10p` (10%) | 0.9494 | 22.49 / 30.43 | 201.0 | **202.2** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_5p` (5%) | 0.9564 | 30.68 / 41.85 | 121.4 | **123.6** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p` (1%) | 0.9978 | 20.46 / 25.55 | 204.5 | **204.3** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_0_1p` (0.1%) | 1.0000 | 1.99 / 3.14 | 3,137.0 | **3,266.4** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `int_range_1p` (1% (range)) | 0.9990 | 19.74 / 24.57 | 210.0 | **206.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `unfiltered_100p` (100%) | 0.9250 | 2.21 / 2.81 | 2,288.2 | **2,358.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_50p` (50%) | 0.9040 | 3.16 / 4.03 | 1,341.3 | **1,360.9** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_10p` (10%) | 0.8740 | 3.97 / 5.18 | 1,016.9 | **1,026.6** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_5p` (5%) | 0.8274 | 3.95 / 5.04 | 971.4 | **955.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p` (1%) | 0.6670 | 4.62 / 5.96 | 788.6 | **801.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_0_1p` (0.1%) | 1.0000 | 6.52 / 15.07 | 281.6 | **281.1** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `int_range_1p` (1% (range)) | 0.6758 | 4.52 / 5.91 | 793.5 | **791.2** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `unfiltered_100p` (100%) | 0.8600 | 1.91 / 3.14 | 3,128.0 | **3,327.3** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_50p` (50%) | 0.8424 | 2.41 / 2.94 | 1,853.4 | **1,930.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_10p` (10%) | 0.8158 | 3.38 / 4.30 | 1,229.7 | **1,242.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_5p` (5%) | 0.7798 | 2.50 / 3.15 | 1,578.0 | **1,620.4** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p` (1%) | 0.5716 | 3.01 / 5.70 | 1,263.0 | **1,267.3** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_0_1p` (0.1%) | 0.9238 | 1.56 / 1.94 | 3,509.2 | **3,848.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `int_range_1p` (1% (range)) | 0.5720 | 3.03 / 5.55 | 1,290.2 | **1,294.0** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p` (100%) | 0.9790 | 2.21 / 2.80 | 953.2 | **954.7** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_50p` (50%) | 0.9768 | 1.74 / 2.07 | 1,479.7 | **1,499.1** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_10p` (10%) | 0.9624 | 1.14 / 1.27 | 3,520.5 | **3,746.0** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_5p` (5%) | 0.9584 | 1.00 / 1.11 | 4,418.7 | **5,016.8** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_1p` (1%) | 0.9304 | 0.86 / 0.94 | 6,364.8 | **7,221.1** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_0_1p` (0.1%) | 0.9774 | 1.46 / 1.69 | 2,479.1 | **2,518.5** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `int_range_1p` (1% (range)) | 0.9388 | 1.28 / 1.44 | 1,006.8 | **1,005.7** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `unfiltered_100p` (100%) | 0.8526 | 2.23 / 2.65 | 1,947.7 | **1,983.2** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_50p` (50%) | 0.8492 | 10.73 / 17.50 | 249.3 | **249.0** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_10p` (10%) | 0.8368 | 4.48 / 5.30 | 930.8 | **934.0** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_5p` (5%) | 0.8066 | 3.57 / 4.09 | 1,207.4 | **1,224.4** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p` (1%) | 0.6520 | 2.78 / 9.76 | 1,343.2 | **1,359.8** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_0_1p` (0.1%) | 1.0000 | 1.55 / 1.67 | 3,578.8 | **3,829.4** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `int_range_1p` (1% (range)) | 0.6504 | 2.77 / 9.56 | 1,399.1 | **1,424.8** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `unfiltered_100p` (100%) | 0.8786 | 3.26 / 3.77 | 1,473.6 | **1,494.9** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_50p` (50%) | 0.8934 | 23.43 / 25.32 | 167.2 | **166.3** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_10p` (10%) | 0.9162 | 18.87 / 24.52 | 188.4 | **188.5** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_5p` (5%) | 0.9152 | 25.16 / 37.46 | 119.1 | **118.6** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p` (1%) | 0.9978 | 16.63 / 20.95 | 204.6 | **204.9** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_0_1p` (0.1%) | 1.0000 | 1.91 / 2.57 | 3,123.1 | **3,271.6** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `int_range_1p` (1% (range)) | 0.9990 | 16.55 / 21.02 | 207.9 | **207.4** |

## 3b. High-Recall & Out-of-Box Operating Points @ k=10 (Post-ForceMerge / Compacted)

| Run Label | Operating Point / Case | Profile | Recall@10 | Serial p50 / p95 (ms) | c=32 QPS |
|---|---|---|---:|---:|---:|
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `unfiltered_100p` | `{"num_candidates":500,"oversample":20.0}` | 0.9450 | 6.65 / 8.47 | **1,736.0** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_10p` | `{"num_candidates":500,"oversample":20.0}` | 0.9120 | 8.94 / 11.75 | **715.9** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p` | `{"num_candidates":500,"oversample":20.0}` | 0.7682 | 8.37 / 11.14 | **439.2** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `es_default_unfiltered_100p` | `{"num_candidates":100,"oversample":3.0}` | 0.8858 | 1.38 / 1.59 | **4,481.7** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `es_default_label_1p` | `{"num_candidates":100,"oversample":3.0}` | 0.5354 | 2.63 / 3.32 | **1,675.7** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p_nc1000` | `{"num_candidates":1000,"oversample":20.0}` | 0.8290 | 16.01 / 21.63 | **216.5** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `unfiltered_100p` | `{"num_candidates":250}` | 0.8786 | 2.20 / 2.94 | **2,142.9** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_10p` | `{"num_candidates":250}` | 0.8492 | 4.33 / 5.94 | **928.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p` | `{"num_candidates":250}` | 0.7078 | 5.00 / 6.58 | **710.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p_nc1000` | `{"num_candidates":1000}` | 0.8164 | 17.38 / 22.95 | **203.5** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p` | `{"nprobe":36,"rerank_pool":256}` | 0.9838 | 3.37 / 4.26 | **554.4** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_10p` | `{"nprobe":36,"rerank_pool":256}` | 0.9756 | 1.45 / 1.62 | **2,193.6** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_1p` | `{"nprobe":36,"rerank_pool":256}` | 0.9634 | 1.09 / 1.17 | **4,691.2** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `unfiltered_100p` | `{"nprobe":36,"rerank_pool":256}` | 0.9838 | 3.35 / 4.30 | **561.9** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_10p` | `{"nprobe":36,"rerank_pool":256}` | 0.9756 | 1.44 / 1.63 | **2,199.2** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_1p` | `{"nprobe":36,"rerank_pool":256}` | 0.9634 | 1.10 / 1.23 | **4,695.9** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `unfiltered_100p` | `{"ef_search":250}` | 0.8948 | 38.77 / 59.53 | **790.6** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_10p` | `{"ef_search":250}` | 0.9118 | 116.31 / 192.88 | **41.0** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p` | `{"ef_search":250}` | 1.0000 | 215.09 / 308.79 | **21.5** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p_nc1000` | `{"ef_search":1000}` | 1.0000 | 252.21 / 356.40 | **18.4** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `unfiltered_100p` | `{"ef_search":500,"oversample":20.0}` | 0.9270 | 10.95 / 13.36 | **843.1** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_10p` | `{"ef_search":500,"oversample":20.0}` | 0.9538 | 30.22 / 43.06 | **117.6** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p` | `{"ef_search":500,"oversample":20.0}` | 0.9994 | 19.21 / 23.93 | **204.0** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `os_default_unfiltered_100p` | `{"ef_search":100,"oversample":3.0}` | 0.8800 | 2.73 / 3.58 | **2,809.2** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `os_default_label_1p` | `{"ef_search":100,"oversample":3.0}` | 0.9862 | 14.19 / 19.81 | **213.3** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p_nc1000` | `{"ef_search":1000,"oversample":20.0}` | 0.9994 | 17.96 / 23.23 | **195.3** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `unfiltered_100p` | `{"num_candidates":500,"oversample":20.0}` | 0.9444 | 2.76 / 3.68 | **1,598.2** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_10p` | `{"num_candidates":500,"oversample":20.0}` | 0.8980 | 5.93 / 7.99 | **659.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p` | `{"num_candidates":500,"oversample":20.0}` | 0.7552 | 8.54 / 11.12 | **410.9** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `es_default_unfiltered_100p` | `{"num_candidates":100,"oversample":3.0}` | 0.8782 | 1.50 / 1.74 | **3,987.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `es_default_label_1p` | `{"num_candidates":100,"oversample":3.0}` | 0.5254 | 2.85 / 3.87 | **1,513.2** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p_nc1000` | `{"num_candidates":1000,"oversample":20.0}` | 0.8274 | 17.30 / 23.00 | **208.9** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `unfiltered_100p` | `{"num_candidates":250}` | 0.8776 | 2.21 / 2.87 | **2,119.0** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_10p` | `{"num_candidates":250}` | 0.8504 | 4.61 / 6.01 | **892.9** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p` | `{"num_candidates":250}` | 0.6982 | 5.18 / 6.92 | **685.1** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p_nc1000` | `{"num_candidates":1000}` | 0.8188 | 18.57 / 24.13 | **196.2** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p` | `{"nprobe":36,"rerank_pool":256}` | 0.9838 | 3.45 / 4.41 | **539.7** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_10p` | `{"nprobe":36,"rerank_pool":256}` | 0.9756 | 1.46 / 1.64 | **2,161.0** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_1p` | `{"nprobe":36,"rerank_pool":256}` | 0.9634 | 1.07 / 1.16 | **4,649.7** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `unfiltered_100p` | `{"ef_search":250}` | 0.8762 | 3.29 / 4.11 | **1,122.2** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_10p` | `{"ef_search":250}` | 0.8740 | 4.94 / 7.20 | **664.2** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p` | `{"ef_search":250}` | 0.7782 | 4.16 / 5.18 | **909.3** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p_nc1000` | `{"ef_search":1000}` | 0.8708 | 9.53 / 13.59 | **328.1** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `unfiltered_100p` | `{"ef_search":500,"oversample":20.0}` | 0.8946 | 4.22 / 5.92 | **848.8** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_10p` | `{"ef_search":500,"oversample":20.0}` | 0.9186 | 24.92 / 39.34 | **113.6** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p` | `{"ef_search":500,"oversample":20.0}` | 0.9994 | 14.17 / 21.02 | **199.7** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `os_default_unfiltered_100p` | `{"ef_search":100,"oversample":3.0}` | 0.8496 | 2.09 / 2.72 | **2,792.8** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `os_default_label_1p` | `{"ef_search":100,"oversample":3.0}` | 0.9978 | 13.26 / 20.17 | **210.6** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p_nc1000` | `{"ef_search":1000,"oversample":20.0}` | 0.9994 | 17.00 / 21.64 | **198.1** |

## 4. VectorDBBench Parity Cases @ k=100 (Post-ForceMerge / Compacted)

| Run Label | Case | Recall@100 | Serial p95 / p99 (ms) | c=32 QPS |
|---|---|---:|---:|---:|
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `unfiltered_100p` | 0.9392 | 26.92 / 29.10 | **1,498.9** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p` | 0.7250 | 11.54 / 12.14 | **420.1** |
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | `int_range_1p` | 0.7222 | 12.44 / 13.34 | **418.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `unfiltered_100p` | 0.8949 | 2.83 / 3.03 | **2,225.2** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p` | 0.6314 | 6.34 / 6.84 | **813.8** |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | `int_range_1p` | 0.6157 | 6.12 / 6.62 | **832.8** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p` | 0.9769 | 3.43 / 3.69 | **770.0** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_1p` | 0.9027 | 1.30 / 1.45 | **5,471.5** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `int_range_1p` | 0.9022 | 2.03 / 2.77 | **589.8** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p_hi98` | 0.9831 | 4.81 / 5.11 | **462.9** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | `label_1p_hi98` | 0.9549 | 1.51 / 1.72 | **3,930.8** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `unfiltered_100p` | 0.9769 | 3.42 / 3.70 | **778.6** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_1p` | 0.9027 | 1.42 / 1.54 | **5,363.2** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `int_range_1p` | 0.9022 | 2.07 / 2.69 | **594.3** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `unfiltered_100p_hi98` | 0.9831 | 4.79 / 5.22 | **471.1** |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | `label_1p_hi98` | 0.9549 | 1.60 / 1.74 | **3,935.8** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `unfiltered_100p` | 0.8903 | 52.51 / 65.17 | **420.8** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p` | 1.0000 | 376.94 / 958.42 | **24.3** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | `int_range_1p` | 1.0000 | 342.54 / 422.59 | **17.4** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `unfiltered_100p` | 0.9271 | 31.00 / 33.61 | **770.8** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p` | 0.9990 | 24.58 / 27.13 | **195.9** |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | `int_range_1p` | 0.9988 | 25.81 / 30.36 | **198.4** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `unfiltered_100p` | 0.9404 | 4.21 / 4.48 | **1,422.8** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `label_1p` | 0.7227 | 11.57 / 11.96 | **404.3** |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | `int_range_1p` | 0.7210 | 11.76 / 12.45 | **402.4** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `unfiltered_100p` | 0.8939 | 2.92 / 3.07 | **2,198.6** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `label_1p` | 0.6239 | 6.62 / 7.19 | **778.5** |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | `int_range_1p` | 0.6158 | 6.50 / 7.05 | **800.9** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p` | 0.9769 | 3.49 / 3.75 | **736.8** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_1p` | 0.9027 | 1.29 / 1.50 | **5,410.8** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `int_range_1p` | 0.9022 | 2.02 / 2.60 | **572.0** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `unfiltered_100p_hi98` | 0.9831 | 5.02 / 5.36 | **454.2** |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | `label_1p_hi98` | 0.9549 | 1.49 / 1.67 | **3,893.9** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `unfiltered_100p` | 0.8640 | 3.88 / 4.04 | **1,246.2** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `label_1p` | 1.0000 | 18.10 / 18.43 | **222.0** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | `int_range_1p` | 1.0000 | 17.94 / 18.28 | **224.7** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `unfiltered_100p` | 0.8962 | 6.33 / 6.57 | **790.2** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `label_1p` | 0.9990 | 21.65 / 22.66 | **199.6** |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | `int_range_1p` | 0.9988 | 21.51 / 22.21 | **200.3** |

## 5. Live Streaming Writes (1,000 writes/s on 10M Index) + Concurrent c=16 Search

| Run Label | Achieved Writes/s | Write Batch p99 | Live Unfiltered QPS (p95) | Live 1% Filtered QPS (p95) | Post-Stream Segments |
|---|---:|---:|---:|---:|---:|
| `16c32g_c6id.4xlarge_es_9.5.6_bbq_hnsw` | 1,003.7/s | 88.4 ms | **1,957.3 QPS** (14.15 ms) | **629.9 QPS** (39.17 ms) | 36 |
| `16c32g_c6id.4xlarge_es_9.5.6_int8_hnsw` | 1,003.6/s | 106.1 ms | **2,143.0 QPS** (13.65 ms) | **867.4 QPS** (29.97 ms) | 43 |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_mem` | 1,004.0/s | 34.2 ms | **711.5 QPS** (39.74 ms) | **3,748.9 QPS** (6.67 ms) | 8 |
| `16c32g_c6id.4xlarge_massengine_v0.9.21_nvme` | 1,004.0/s | 38.1 ms | **710.8 QPS** (40.01 ms) | **3,653.3 QPS** (6.97 ms) | 8 |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_fp16` | 1,000.6/s | 225.7 ms | **793.3 QPS** (47.72 ms) | **9.8 QPS** (2051.81 ms) | 40 |
| `16c32g_c6id.4xlarge_os_3.9.0_faiss_on_disk` | 1,003.1/s | 272.6 ms | **953.7 QPS** (28.53 ms) | **162.2 QPS** (147.48 ms) | 52 |
| `16c64g_m6id.4xlarge_es_9.5.6_bbq_hnsw` | 1,003.6/s | 91.5 ms | **1,742.7 QPS** (15.06 ms) | **570.3 QPS** (42.42 ms) | 33 |
| `16c64g_m6id.4xlarge_es_9.5.6_int8_hnsw` | 1,003.5/s | 99.9 ms | **2,145.5 QPS** (13.24 ms) | **840.0 QPS** (30.21 ms) | 49 |
| `16c64g_m6id.4xlarge_massengine_v0.9.21_mem` | 1,004.0/s | 37.3 ms | **692.5 QPS** (40.67 ms) | **3,764.1 QPS** (6.68 ms) | 8 |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_fp16` | 1,003.5/s | 262.4 ms | **1,129.1 QPS** (23.26 ms) | **933.1 QPS** (34.60 ms) | 46 |
| `16c64g_m6id.4xlarge_os_3.9.0_faiss_on_disk` | 1,003.4/s | 277.7 ms | **974.9 QPS** (28.02 ms) | **162.2 QPS** (150.55 ms) | 32 |
