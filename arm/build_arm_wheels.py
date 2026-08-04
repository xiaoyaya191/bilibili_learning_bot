#!/usr/bin/env python3
"""Build an aarch64 wheelhouse for bilibili_learning_bot on this machine.

Strategy:
1. Read arm/requirements-arm64-resolved.txt (exact pins).
2. Download every package (except qrcode-terminal) as a prebuilt
   manylinux aarch64 wheel from the Tsinghua PyPI mirror. These are the
   "compiled ARM artifacts" and need no ARM toolchain on this host.
3. qrcode-terminal only ships an sdist (pure Python), so it is downloaded
   as source and built by pip on the ARM device during install.

Output: arm/wheelhouse/  (ready to commit to the repository)

Usage:
    python arm/build_arm_wheels.py [--python 312] [--out arm/wheelhouse]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESOLVED = ROOT / "arm" / "requirements-arm64-resolved.txt"
DEFAULT_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
SDIST_ONLY = {"qrcode-terminal"}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _run(cmd: list[str]) -> None:
    print("+", " ".join(str(part) for part in cmd), flush=True)
    subprocess.run(cmd, check=True)


def _parse_requirements(path: Path) -> list[tuple[str, str]]:
    specs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        specs.append(tuple(part.strip() for part in line.split("==", 1)))
    return specs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="312", help="Target CPython version, e.g. 312 or 313")
    parser.add_argument("--out", default=str(ROOT / "arm" / "wheelhouse"))
    parser.add_argument("--mirror", default=DEFAULT_MIRROR)
    args = parser.parse_args()

    py_version = args.python
    abi = f"cp{py_version}"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    specs = _parse_requirements(RESOLVED)
    if not specs:
        print("no requirements parsed", file=sys.stderr)
        return 1

    downloaded: dict[str, str] = {}
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

    for name, version in specs:
        normalized = _normalize(name)
        if normalized in SDIST_ONLY:
            # Pure-Python sdist: pip builds it on the ARM device.
            cmd = [
                sys.executable, "-m", "pip", "download", "--no-deps",
                "--no-binary", name,
                "-d", str(out_dir),
                "-i", args.mirror,
                "--disable-pip-version-check",
                f"{name}=={version}",
            ]
            _run(cmd)
            downloaded[normalized] = f"{name}-{version}.tar.gz"
            continue
        spec = f"{name}=={version}"
        _run(base + [spec])
        downloaded[normalized] = spec

    # Verify every pinned package produced an artifact.
    artifacts = list(out_dir.iterdir())
    missing = []
    for name, _version in specs:
        normalized = _normalize(name)
        if not any(_normalize(artifact.name).startswith(normalized + "-") for artifact in artifacts):
            missing.append(name)
    if missing:
        print("MISSING ARM64 ARTIFACTS:", ", ".join(missing), file=sys.stderr)
        print("These packages have no manylinux aarch64 wheel. Options:", file=sys.stderr)
        print("  1. Use Docker buildx: docker buildx build --platform linux/arm64 .", file=sys.stderr)
        print("  2. Remove the optional dependency from requirements-arm64-resolved.txt", file=sys.stderr)
        return 1

    total_mb = sum(artifact.stat().st_size for artifact in artifacts) / 1024 / 1024
    print(f"\nARM64 wheelhouse ready: {out_dir}")
    print(f"artifacts={len(artifacts)} size={total_mb:.1f} MB python=cp{py_version}")
    print("Commit arm/wheelhouse and run install_arm.sh on the ARM device.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
