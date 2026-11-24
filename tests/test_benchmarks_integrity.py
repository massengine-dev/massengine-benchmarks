import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BenchmarkIntegrityTests(unittest.TestCase):
    def test_vectordbbench_plugin_syntax(self) -> None:
        py_files = list((ROOT / "vectordbbench").rglob("*.py"))
        self.assertGreaterEqual(len(py_files), 5)
        for path in py_files:
            compile(path.read_text(encoding="utf-8"), path.name, "exec")

    def test_shell_scripts_syntax(self) -> None:
        sh_files = sorted((ROOT / "vectordbbench").glob("*.sh"))
        self.assertEqual(len(sh_files), 3)
        for path in sh_files:
            subprocess.run(["bash", "-n", str(path)], check=True)
        install_txt = (ROOT / "vectordbbench" / "install_server_node.sh").read_text(encoding="utf-8")
        self.assertIn("Authorization: Bearer", install_txt)

    def test_eval_and_multimodal_python_syntax(self) -> None:
        py_files = list((ROOT / "eval-8core").glob("*.py")) + list((ROOT / "multimodal-image").glob("*.py"))
        self.assertEqual(len(py_files), 3)
        for path in py_files:
            compile(path.read_text(encoding="utf-8"), path.name, "exec")

    def test_eval_8core_runner_against_mock_server(self) -> None:
        state_lock = threading.Lock()
        store: list[dict] = []
        nodes_state = {
            "ready": True,
            "coordinator_version": "v0.11.8",
            "nodes": [
                {"node_id": 0, "status": "healthy", "fenced_shards": []},
                {"node_id": 1, "status": "healthy", "fenced_shards": []},
            ],
        }

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args) -> None:
                return

            def _send(self, code: int, obj: dict) -> None:
                raw = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if self.path == "/v1/health":
                    self._send(200, {"status": "ok"})
                elif self.path == "/v1/nodes":
                    with state_lock:
                        self._send(200, nodes_state)
                elif self.path == "/v1/license":
                    self._send(200, {"licensed_cores": 8, "tier": "eval"})
                else:
                    self._send(404, {"error": "not found"})

            def do_DELETE(self) -> None:
                with state_lock:
                    store.clear()
                self._send(200, {"deleted": True})

            def do_POST(self) -> None:
                ln = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(ln).decode("utf-8")) if ln > 0 else {}
                if self.path == "/v1/databases":
                    self._send(200, {"ok": True})
                elif self.path == "/v1/ingest":
                    with state_lock:
                        store.extend(body.get("docs", []))
                    self._send(200, {"ingested": len(body.get("docs", []))})
                elif self.path in ("/v1/flush", "/v1/compact", "/v1/reconcile"):
                    self._send(200, {"ok": True, "repaired_replicas": 0})
                elif self.path == "/v1/nodes/0/drain":
                    self._send(200, {"drained": True})
                elif self.path == "/v1/nodes/0/uncordon":
                    self._send(200, {"uncordoned": True})
                elif self.path == "/v1/search":
                    q = body.get("vector", [])
                    cat = body.get("category")
                    k = int(body.get("k", 10))
                    with state_lock:
                        snapshot = list(store)
                    scored = []
                    for d in snapshot:
                        if cat is not None and d.get("category") != cat:
                            continue
                        v = d.get("vector", [])
                        dot = sum(a * b for a, b in zip(q, v))
                        scored.append((dot, d["id"]))
                    scored.sort(key=lambda t: -t[0])
                    hits = [{"id": did, "score": sc} for sc, did in scored[:k]]
                    self._send(200, {"hits": hits, "took_ms": 0.4})
                else:
                    self._send(404, {"error": "not found"})

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "eval_out.json")
                env = os.environ.copy()
                env["PYTHONPATH"] = ""
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "eval-8core" / "bench_eval_cluster.py"),
                        "--url",
                        f"http://127.0.0.1:{srv.server_port}",
                        "--api-key",
                        "meadm_test_token",
                        "--dim",
                        "32",
                        "--vectors",
                        "120",
                        "--queries",
                        "12",
                        "--workers",
                        "2",
                        "--batch-size",
                        "40",
                        "--conc-list",
                        "1,2",
                        "--conc-duration",
                        "0.15",
                        "--verify-ha-drain",
                        "--out",
                        out_path,
                    ],
                    check=True,
                    env=env,
                )
                rep = json.loads(Path(out_path).read_text(encoding="utf-8"))
                self.assertEqual(rep["vectors"], 120)
                self.assertGreaterEqual(rep["search_unfiltered"]["recall_at_10"], 0.99)
                self.assertGreaterEqual(rep["search_filtered_1pct"]["recall_at_10"], 0.99)
                self.assertEqual(rep["ha_drain_verification"]["queries_failed"], 0)
                self.assertTrue(rep["ha_drain_verification"]["cluster_healthy_after"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_multimodal_image_results(self) -> None:
        base = ROOT / "results" / "multimodal-image"
        expected = {
            "results_imagenet_clip_512.json": (1_281_167, 512),
            "results_laion_clip_512_ood.json": (1_000_448, 512),
            "results_deep_image_96_10m.json": (9_990_000, 96),
        }
        for fn, (n_vecs, dim) in expected.items():
            data = json.loads((base / fn).read_text(encoding="utf-8"))
            self.assertEqual(data["num_vectors"], n_vecs)
            self.assertEqual(data["dim"], dim)
            dtypes = {r["data_type"]: r for r in data["results"]}
            self.assertEqual(set(dtypes.keys()), {"int8", "float16", "int4"})
            self.assertGreater(dtypes["float16"]["profiles"][1]["recall_at_10"], 0.94)

    def test_cohere_10m_v0919_results(self) -> None:
        base = ROOT / "results" / "vectordbbench-cohere-10m" / "v0.9.19"
        for tier in ("16c64g-in-memory", "16c32g-nvme"):
            files = sorted((base / tier).glob("result_*.json"))
            self.assertEqual(len(files), 5, f"expected 5 VectorDBBench suites in {tier}")
            for fp in files:
                data = json.loads(fp.read_text(encoding="utf-8"))
                self.assertTrue(data.get("results"), f"empty results in {fp.name}")
                entry = data["results"][0]
                cfg = entry["task_config"]
                self.assertEqual(cfg["db"], "MassEngine")
                self.assertEqual(cfg["db_config"]["version"], "v0.9.19")
                self.assertEqual(cfg["db_config"]["url"], "**********")
                self.assertEqual(cfg["db_config"]["api_key"], "**********")
                metrics = entry["metrics"]
                if metrics.get("st_recall_list"):
                    self.assertGreaterEqual(metrics["st_recall_list"][-1], 0.95, f"low streaming recall in {fp.name}")
                    self.assertGreater(max(metrics["st_max_qps_list_list"]), 1000.0, f"low streaming qps in {fp.name}")
                else:
                    self.assertGreaterEqual(metrics["recall"], 0.95, f"low recall in {fp.name}")
                    self.assertGreater(metrics["qps"], 0.0, f"zero qps in {fp.name}")

    def test_cohere_10m_v0112_results(self) -> None:
        base = ROOT / "results" / "vectordbbench-cohere-10m" / "v0.11.2"
        for tier in ("16c64g-in-memory", "16c32g-nvme"):
            files = sorted((base / tier).glob("result_*.json"))
            self.assertEqual(len(files), 5, f"expected 5 VectorDBBench suites in {tier}")
            for fp in files:
                data = json.loads(fp.read_text(encoding="utf-8"))
                self.assertTrue(data.get("results"), f"empty results in {fp.name}")
                entry = data["results"][0]
                cfg = entry["task_config"]
                self.assertEqual(cfg["db"], "MassEngine")
                self.assertEqual(cfg["db_config"]["version"], "v0.11.2")
                self.assertEqual(cfg["db_config"]["url"], "**********")
                self.assertEqual(cfg["db_config"]["api_key"], "**********")
                metrics = entry["metrics"]
                if metrics.get("st_recall_list"):
                    self.assertGreaterEqual(metrics["st_recall_list"][-1], 0.96, f"low streaming recall in {fp.name}")
                    self.assertGreater(max(metrics["st_max_qps_list_list"]), 1000.0, f"low streaming qps in {fp.name}")
                else:
                    self.assertGreaterEqual(metrics["recall"], 0.96, f"low recall in {fp.name}")
                    self.assertGreater(metrics["qps"], 0.0, f"zero qps in {fp.name}")

    def test_wikipedia_144m_results(self) -> None:
        base = ROOT / "results" / "wikipedia-144m-aws"
        for fn in ("report_tier1_in_memory.json", "report_tier2_nvme.json"):
            data = json.loads((base / fn).read_text(encoding="utf-8"))
            self.assertEqual(data["ingestion"]["total_unique_records"], 144_137_311)
            self.assertEqual(data["ingestion"]["total_replicated_vectors"], 288_274_622)
            self.assertGreater(data["ingestion"]["effective_docs_per_sec"], 100_000)

    def test_es_os_faiss_10m_driver_and_results(self) -> None:
        py_files = list((ROOT / "es-opensearch-10m").glob("*.py"))
        self.assertEqual(len(py_files), 3)
        for path in py_files:
            compile(path.read_text(encoding="utf-8"), path.name, "exec")

        res_dir = ROOT / "results" / "cohere-10m-es-os-faiss"
        json_files = sorted(res_dir.glob("*.json"))
        self.assertEqual(len(json_files), 11, "expected 11 EC2 head-to-head JSON reports")
        for fp in json_files:
            data = json.loads(fp.read_text(encoding="utf-8"))
            self.assertEqual(data["total_records"], 10_000_000)
            self.assertEqual(data["dim"], 768)
            self.assertIn("ingest", data)
            self.assertIn("search_post_ingest", data)
            self.assertIn("search_post_optimize", data)
            self.assertIn("streaming_read_write", data)
            self.assertGreater(data["streaming_read_write"]["achieved_writes_per_sec"], 950.0)


if __name__ == "__main__":
    unittest.main()
