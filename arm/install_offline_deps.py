#!/usr/bin/env python3
"""Version-aware offline dependency installer with Tsinghua fallback.

Rules (same as the .deb installer):
- If the installed version already satisfies the requirement -> skip.
- If it does not (missing or older), try the local wheelhouse first.
- If the wheelhouse has no usable wheel for this Python, install from the
  Tsinghua mirror instead of failing.

Run inside the project .venv:
    .venv/bin/python arm/install_offline_deps.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "arm" / "requirements-arm64.txt"
WHEELHOUSE = ROOT / "arm" / "wheelhouse"
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def installed_version(python: str, name: str) -> str | None:
    try:
        result = subprocess.run(
            [python, "-m", "pip", "show", name],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return None
    for line in result.stdout.splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return None


def should_skip(installed: str | None, spec: str) -> bool:
    if not installed:
        return False
    if not spec:
        return True
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
        if Version(installed) in SpecifierSet(spec):
            return True
        # Never downgrade an exact == pin when the installed version is newer.
        match = re.match(r"==\s*(.+)$", spec.strip())
        if match:
            return Version(installed) > Version(match.group(1))
    except Exception:
        return False
    return False


def pip_install(python: str, args: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        [python, "-m", "pip", "install", *args],
        capture_output=True, text=True, timeout=900,
    )
    return result.returncode, result.stdout + "\n" + result.stderr


def _print_pip_tail(output: str, limit: int = 25) -> None:
    lines = [line for line in output.splitlines() if line.strip()]
    for line in lines[-limit:]:
        print("      | " + line)


def main() -> int:
    python = sys.executable
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    lines = [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    skipped = 0
    installed_count = 0
    fallback_count = 0

    for line in lines:
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not match:
            continue
        name = match.group(1)
        spec = line[match.end():].strip()
        current = installed_version(python, name)
        if should_skip(current, spec):
            print(f"  skip {name}（已安装 {current} 满足 {spec or '>=0'}）")
            skipped += 1
            continue

        print(f"  安装 {line} ...")
        offline = [
            "--no-index", "--find-links", str(WHEELHOUSE),
            "--no-build-isolation", line,
        ]
        code, output = pip_install(python, offline)
        if code == 0:
            installed_count += 1
            continue

        print(f"  wheelhouse 无可用 {name} 轮子，改用清华源安装依赖后重装...")
        print("  离线 pip 输出（末尾）:")
        _print_pip_tail(output)
        online = ["--no-build-isolation", "-i", MIRROR, line]
        code, output = pip_install(python, online)
        if code != 0:
            print(f"  ERROR 安装 {line} 失败", file=sys.stderr)
            print("  清华源 pip 输出（末尾）:")
            _print_pip_tail(output)
            return 1
        installed_count += 1
        fallback_count += 1

    print(f"依赖处理完成：跳过 {skipped}，安装 {installed_count}，清华源回退 {fallback_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
