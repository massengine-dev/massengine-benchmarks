#!/usr/bin/env python3
"""Idempotently installs ONLY the MassEngine client plugin into an official
zilliztech/VectorDBBench checkout and verifies zero upstream runner/metric/dataset
files were modified.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ALLOWED_PATHS = {
    "vectordb_bench/backend/clients/__init__.py",
    "vectordb_bench/cli/vectordbbench.py",
    "vectordb_bench/backend/clients/massengine/",
}


def patch_clients_init(clients_init: Path) -> None:
    src = clients_init.read_text(encoding="utf-8")
    if 'MassEngine = "MassEngine"' not in src:
        anchor = '    HouyiDB = "HouyiDB"\n'
        if anchor not in src:
            raise RuntimeError(f"Could not locate DB enum anchor in {clients_init}")
        src = src.replace(anchor, anchor + '    MassEngine = "MassEngine"\n', 1)

    if "from .massengine.massengine import MassEngine" not in src:
        anchor = "            from .houyidb.houyidb import HouyiDB\n\n            return HouyiDB\n"
        addition = (
            anchor
            + "\n        if self == DB.MassEngine:\n"
            + "            from .massengine.massengine import MassEngine\n\n"
            + "            return MassEngine\n"
        )
        if anchor not in src:
            raise RuntimeError(f"Could not locate init_cls anchor in {clients_init}")
        src = src.replace(anchor, addition, 1)

    if "from .massengine.config import MassEngineConfig" not in src:
        anchor = "            from .houyidb.config import HouyiDBConfig\n\n            return HouyiDBConfig\n"
        addition = (
            anchor
            + "\n        if self == DB.MassEngine:\n"
            + "            from .massengine.config import MassEngineConfig\n\n"
            + "            return MassEngineConfig\n"
        )
        if anchor not in src:
            raise RuntimeError(f"Could not locate config_cls anchor in {clients_init}")
        src = src.replace(anchor, addition, 1)

    if "from .massengine.config import MassEngineIndexConfig" not in src:
        anchor = "            from .houyidb.config import HouyiDBIndexConfig\n\n            return HouyiDBIndexConfig\n"
        addition = (
            anchor
            + "\n        if self == DB.MassEngine:\n"
            + "            from .massengine.config import MassEngineIndexConfig\n\n"
            + "            return MassEngineIndexConfig\n"
        )
        if anchor not in src:
            raise RuntimeError(f"Could not locate case_config_cls anchor in {clients_init}")
        src = src.replace(anchor, addition, 1)

    clients_init.write_text(src, encoding="utf-8")


def patch_cli_entry(cli_file: Path) -> None:
    src = cli_file.read_text(encoding="utf-8")
    if "from ..backend.clients.massengine.cli import MassEngine" not in src:
        anchor = "from ..backend.clients.zvec.cli import Zvec\n"
        if anchor not in src:
            raise RuntimeError(f"Could not locate CLI import anchor in {cli_file}")
        src = src.replace(anchor, anchor + "from ..backend.clients.massengine.cli import MassEngine\n", 1)

    if "cli.add_command(MassEngine)" not in src:
        anchor = "cli.add_command(HouyiDB)\n"
        if anchor not in src:
            raise RuntimeError(f"Could not locate cli.add_command anchor in {cli_file}")
        src = src.replace(anchor, anchor + "cli.add_command(MassEngine)\n", 1)

    cli_file.write_text(src, encoding="utf-8")


def verify_upstream_untouched(repo_dir: Path) -> None:
    out = subprocess.check_output(
        ["git", "-C", str(repo_dir), "status", "--porcelain"],
        text=True,
    )
    unexpected: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        rel_path = line[3:].strip()
        if rel_path in ALLOWED_PATHS or rel_path.startswith("vectordb_bench/backend/clients/massengine/"):
            continue
        if rel_path.startswith("vectordb_bench/results/"):
            continue
        unexpected.append(line)
    if unexpected:
        raise RuntimeError(
            "ABORT: Upstream VectorDBBench files outside the MassEngine client plugin were modified:\n"
            + "\n".join(unexpected)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vdbbench-dir", type=Path, required=True, help="Path to zilliztech/VectorDBBench clone")
    args = parser.parse_args()

    plugin_src = Path(__file__).resolve().parent / "massengine"
    repo_dir = args.vdbbench_dir.resolve()
    dest_dir = repo_dir / "vectordb_bench" / "backend" / "clients" / "massengine"

    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "config.py", "massengine.py", "cli.py"):
        shutil.copy2(plugin_src / name, dest_dir / name)

    patch_clients_init(repo_dir / "vectordb_bench" / "backend" / "clients" / "__init__.py")
    patch_cli_entry(repo_dir / "vectordb_bench" / "cli" / "vectordbbench.py")
    verify_upstream_untouched(repo_dir)
    print(f"OK: Installed MassEngine client plugin into {repo_dir} (zero core VectorDBBench files modified).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
