#!/usr/bin/env python3
"""Build an aarch64 wheelhouse for bilibili_learning_bot on this machine.

Strategy:
1. Download every pinned package from arm/requirements-arm64-resolved.txt as a
   prebuilt manylinux aarch64 wheel (qrcode-terminal as sdist) from the
   Tsinghua mirror.
2. Parse every wheel's .dist-info/METADATA and verify the transitive closure
   is complete. A missing dependency fails the build instead of failing later
   on the ARM device.

Output: arm/wheelhouse/  (ready to commit)

Usage:
    python arm/build_arm_wheels.py [--python 314]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
RESOLVED = ROOT / "arm" / "requirements-arm64-resolved.txt"
SDIST_ONLY = {"qrcode-terminal"}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirements(path: Path) -> list[tuple[str, str]]:
    specs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match:
            specs.append((match.group(1), line))
    return specs


def _artifact_name(path: Path) -> str:
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*?)-\d", path.name)
    return _normalize(match.group(1)) if match else ""


def _wheel_requirements(path: Path) -> set[str]:
    requirements: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            metadata = next((n for n in archive.namelist() if n.endswith(".dist-info/METADATA")), None)
            if not metadata:
                return requirements
            text = archive.read(metadata).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError):
        return requirements
    for line in text.splitlines():
        if not line.lower().startswith("requires-dist:"):
            continue
        value = line.split(":", 1)[1].strip()
        if ";" in value:
            continue  # conditional marker, cannot be validated offline
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", value)
        if match:
            requirements.add(_normalize(match.group(1)))
    return requirements


def _run(cmd: list[str]) -> None:
    print("+ " + " ".join(str(part) for part in cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="314", help="Target CPython version, e.g. 312 or 314")
    parser.add_argument("--out", default=str(ROOT / "arm" / "wheelhouse"))
    parser.add_argument("--mirror", default=DEFAULT_MIRROR)
    parser.add_argument("--no-archive", action="store_true", help="Skip wheelhouse.tar.gz creation")
    args = parser.parse_args()

    py_version = args.python
    abi = f"cp{py_version}"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = [
        sys.executable, "-m", "pip", "download", "--no-deps",
        "--platform", "manylinux2014_aarch64",
        "--platform", "manylinux_2_17_aarch64",
        "--python-version", py_version,
        "--implementation", "cp",
        "--abi", abi,
        "-d", str(out_dir),
        "-i", args.mirror,
        "--disable-pip-version-check",
    ]

    specs = _parse_requirements(RESOLVED)
    for name, spec in specs:
        normalized = _normalize(name)
        if any(_artifact_name(artifact) == normalized for artifact in out_dir.iterdir()):
            print(f"skip existing: {spec}")
            continue
        if normalized in SDIST_ONLY:
            _run([
                sys.executable, "-m", "pip", "download", "--no-deps",
                "--no-binary", name, "-d", str(out_dir), "-i", args.mirror,
                "--disable-pip-version-check", spec,
            ])
        else:
            _run(base + [spec])

    artifacts = list(out_dir.iterdir())
    available = {_artifact_name(item) for item in artifacts}
    available.discard("")

    # Verify every non-conditional Requires-Dist is present in the wheelhouse.
    missing: set[str] = set()
    for artifact in artifacts:
        if artifact.suffix == ".whl":
            missing.update(_wheel_requirements(artifact) - available)
    if missing:
        print("\nMISSING TRANSITIVE DEPENDENCIES:", ", ".join(sorted(missing)), file=sys.stderr)
        print("Add them to requirements-arm64-resolved.txt and rerun.", file=sys.stderr)
        return 1

    missing_top = [name for name, _spec in specs if _normalize(name) not in available]
    if missing_top:
        print("MISSING TOP-LEVEL ARTIFACTS:", ", ".join(missing_top), file=sys.stderr)
        return 1

    total_mb = sum(artifact.stat().st_size for artifact in artifacts) / 1024 / 1024
    print(f"\nARM64 wheelhouse ready: {out_dir}")
    print(f"artifacts={len(artifacts)} size={total_mb:.1f} MB python=cp{py_version}")
    print("transitive closure check: OK")

    if not args.no_archive:
        archive = out_dir.with_suffix(out_dir.suffix + ".tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            for artifact in artifacts:
                tar.add(artifact, arcname=f"wheelhouse/{artifact.name}")
        print(f"archive={archive} size={archive.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
