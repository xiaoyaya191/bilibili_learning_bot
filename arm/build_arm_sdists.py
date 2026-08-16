#!/usr/bin/env python3
"""Check and download source sdists for every pinned ARM64 dependency.

Termux (Android/bionic) cannot use manylinux aarch64 wheels, so C/Rust
dependencies must be built from source. This script:

1. Reads arm/requirements-arm64-resolved.txt (exact pins).
2. Queries the Tsinghua PyPI simple index for each package.
3. Downloads the matching sdist (.tar.gz / .zip) into arm/wheelhouse-src/.
4. Writes arm/sdists-report.txt listing every package and its status.

Usage:
    python arm/build_arm_sdists.py
"""
from __future__ import annotations

import argparse
import re
import urllib.request
import subprocess
from urllib.parse import urljoin
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESOLVED = ROOT / "arm" / "requirements-arm64-resolved.txt"
OUT = ROOT / "arm" / "wheelhouse-src"
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
REPORT = ROOT / "arm" / "sdists-report.txt"


def _parse_requirements(path: Path) -> list[tuple[str, str]]:
    specs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match:
            specs.append((match.group(1), line[match.end():].strip()))
    return specs


def _simple_index(name: str) -> str:
    url = f"{MIRROR}/{name}/"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def _pick_sdist(name: str, spec: str, html: str) -> str | None:
    links = re.findall(r'href="([^"]+\.(?:tar\.gz|zip))(?:#[^"]*)?"', html)
    if not links:
        return None
    version_match = re.search(r"(==|>=|<=|~=)?\s*([0-9][A-Za-z0-9.+-]*)", spec)
    target = version_match.group(2) if version_match else ""
    if target:
        for link in links:
            filename = link.split("/")[-1]
            filename = filename.split("#")[0]
            if filename.startswith(f"{name}-{target}") or f"-{target}." in filename:
                return link
    return links[-1]


def _download(url: str, target: Path) -> None:
    # TUNA 对 urllib/requests 的 TLS 指纹返回 403，curl 可以正常下载。
    subprocess.run(["curl", "-sSL", "-o", str(target), url], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror", default=MIRROR)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    specs = _parse_requirements(RESOLVED)
    rows = []
    downloaded = 0
    missing = []
    for name, spec in specs:
        try:
            html = _simple_index(name)
            link = _pick_sdist(name, spec, html)
        except Exception as exc:
            rows.append((name, spec, "ERROR", str(exc)[:120]))
            missing.append(name)
            continue
        if not link:
            rows.append((name, spec, "NO_SDIST", ""))
            missing.append(name)
            continue
        filename = link.split("/")[-1].split("#")[0]
        target = out_dir / filename
        if not target.exists():
            try:
                url = urljoin(f"{args.mirror}/{name}/", link)
                _download(url, target)
            except Exception as exc:
                rows.append((name, spec, "DOWNLOAD_ERROR", str(exc)[:120]))
                missing.append(name)
                continue
        rows.append((name, spec, "OK", filename))
        downloaded += 1

    report_lines = []
    for name, spec, status, detail in rows:
        report_lines.append(f"{status:16} {name:30} {spec:20} {detail}")
    REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    total_mb = sum(item.stat().st_size for item in out_dir.iterdir() if item.is_file()) / 1024 / 1024
    print(f"\n检查 {len(specs)} 个依赖，可用 sdist {downloaded} 个，缺失 {len(missing)} 个")
    print(f"输出目录: {out_dir}（{total_mb:.1f} MB）")
    print(f"报告: {REPORT}")
    for name, spec, status, detail in rows:
        print(f"  {status:16} {name} {spec} {detail[:60]}")
    if missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
