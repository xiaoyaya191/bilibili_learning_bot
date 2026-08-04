#!/usr/bin/env python3
"""Download the Termux aarch64 .deb closure for offline installation.

What this does:
1. Reads the Termux stable aarch64 package index from the Tsinghua mirror.
2. Resolves the dependency closure for python / python-pip / libyaml.
3. Downloads every .deb (dependency first), verifies SHA256 when available.
4. Writes arm/termux-debs-order.txt so the device can run `dpkg -i` offline.

The Python project wheels are handled separately by build_arm_wheels.py.

Usage:
    python arm/build_termux_offline.py [--packages python,python-pip,libyaml]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIRROR = "https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main"
INDEX_URL = "{mirror}/dists/stable/main/binary-{arch}/Packages"


def _download(url: str, target: Path, expected_sha256: str = "") -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(tmp, "wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
    if expected_sha256:
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if digest != expected_sha256.lower():
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"SHA256 mismatch for {target.name}")
    tmp.replace(target)


def _parse_packages(text: str) -> dict[str, dict]:
    packages: dict[str, dict] = {}
    for stanza in text.split("\n\n"):
        fields: dict[str, str] = {}
        for line in stanza.splitlines():
            if line.startswith(" ") or not line.strip():
                continue
            key, _, value = line.partition(":")
            fields[key] = value.strip()
        name = fields.get("Package")
        if not name or "Filename" not in fields:
            continue
        current = packages.get(name)
        if current is None or _version_gt(fields.get("Version", ""), current.get("Version", "")):
            packages[name] = fields
    return packages


def _version_gt(left: str, right: str) -> bool:
    try:
        from packaging.version import parse
        return parse(left) > parse(right)
    except Exception:
        return left > right


def _direct_dependencies(depends: str, packages: dict[str, dict]) -> list[str]:
    result = []
    for group in (depends or "").split(","):
        group = group.strip()
        if not group:
            continue
        picked = None
        for alternative in group.split("|"):
            name = re.split(r"\s*[\(\[]", alternative.strip(), maxsplit=1)[0].strip()
            if name and name in packages:
                picked = name
                break
        if picked:
            result.append(picked)
    return result


def _resolve_closure(roots: list[str], packages: dict[str, dict]) -> list[str]:
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        info = packages.get(name)
        if info is None:
            raise RuntimeError(f"package not found in index: {name}")
        for dep in _direct_dependencies(info.get("Depends", ""), packages):
            visit(dep)
        ordered.append(name)

    for root in roots:
        visit(root)
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", default="python,python-pip,libyaml")
    parser.add_argument("--arch", default="aarch64")
    parser.add_argument("--mirror", default=DEFAULT_MIRROR)
    parser.add_argument("--out", default=str(ROOT / "arm" / "termux-debs"))
    args = parser.parse_args()

    index_url = INDEX_URL.format(mirror=args.mirror.rstrip("/"), arch=args.arch)
    print(f"fetching index: {index_url}")
    with urllib.request.urlopen(index_url, timeout=180) as response:
        index_text = response.read().decode("utf-8", errors="replace")
    packages = _parse_packages(index_text)
    print(f"index packages: {len(packages)}")

    roots = [name.strip() for name in args.packages.split(",") if name.strip()]
    ordered = _resolve_closure(roots, packages)
    print(f"closure packages: {len(ordered)}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    order_path = out_dir / "termux-debs-order.txt"
    order_lines: list[str] = []
    total_bytes = 0

    for name in ordered:
        info = packages[name]
        filename = info["Filename"]
        url = f"{args.mirror.rstrip('/')}/{filename.lstrip('/')}"
        # Windows 不允许文件名带冒号（deb 版本 epoch 如 1:2026...），改名不影响 dpkg 安装
        deb_name = Path(filename).name.replace(":", "_")
        sha256 = info.get("SHA256", "")
        target = out_dir / deb_name
        if not target.exists():
            print(f"download {deb_name} ({info.get('Size', '?')} B)")
            _download(url, target, sha256)
        elif sha256:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != sha256.lower():
                target.unlink(missing_ok=True)
                print(f"re-download {deb_name} (checksum changed)")
                _download(url, target, sha256)
        order_lines.append(deb_name)
        total_bytes += target.stat().st_size

    order_path.write_text("\n".join(order_lines) + "\n", encoding="utf-8")
    print(f"\ntermux debs ready: {out_dir}")
    print(f"packages={len(order_lines)} size={total_bytes / 1024 / 1024:.1f} MB")
    print("install order file:", order_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
