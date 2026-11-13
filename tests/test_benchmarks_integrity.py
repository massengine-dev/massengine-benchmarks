import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BenchmarkIntegrityTests(unittest.TestCase):
    def test_vectordbbench_plugin_syntax(self) -> None:
        py_files = list((ROOT / "vectordbbench").rglob("*.py"))
        self.assertGreaterEqual(len(py_files), 5)
        for path in py_files:
            compile(path.read_text(encoding="utf-8"), path.name, "exec")

    def test_shell_scripts_syntax(self) -> None:
        sh_files = list((ROOT / "vectordbbench").glob("*.sh"))
        self.assertEqual(len(sh_files), 2)
        for path in sh_files:
            subprocess.run(["bash", "-n", str(path)], check=True)

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

    def test_wikipedia_144m_results(self) -> None:
        base = ROOT / "results" / "wikipedia-144m-aws"
        for fn in ("report_tier1_in_memory.json", "report_tier2_nvme.json"):
            data = json.loads((base / fn).read_text(encoding="utf-8"))
            self.assertEqual(data["ingestion"]["total_unique_records"], 144_137_311)
            self.assertEqual(data["ingestion"]["total_replicated_vectors"], 288_274_622)
            self.assertGreater(data["ingestion"]["effective_docs_per_sec"], 100_000)


if __name__ == "__main__":
    unittest.main()
