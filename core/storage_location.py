"""用户数据目录（存储位置）的解析、校验与迁移。

面板「系统设置 → 数据目录」、启动流程和 CLI 共用这里的实现，避免多处逻辑漂移。

设计要点：
- 指针文件固定在默认位置 ``<默认根>/Data/storage_location.json``，里面只有一行路径，
  不含任何凭据。数据目录换到别的盘之后，下次启动仍然读得到这个指针。
- 校验在真正落盘前完成（磁盘根目录、系统目录、程序目录、可写性、递归复制），
  校验不通过就不写指针，避免面板下次启动指向一个不可用的目录。
- 迁移只补充目标目录缺失的文件，不覆盖已有文件，因此重复执行是幂等的。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

POINTER_NAME = "storage_location.json"
#: 路径长度下限：拦掉 "C:\\"、"D:" 这类磁盘根目录。
MIN_PATH_LENGTH = 4
#: 迁移时跳过的运行态文件（拷贝过去会误导新实例）。
_SKIP_ON_MIGRATE = {POINTER_NAME, "bot.lock", ".accounts.lock"}
#: 锁文件统一跳过：新实例应当自己重新创建，复制过去只会带来“被占用”的假象。
_SKIP_ON_MIGRATE_SUFFIXES = (".lock",)
_WRITE_PROBE = ".bililearn_write_test"


class StoragePathError(ValueError):
    """目录不合法；调用方应转成 400 而不是 500。"""


def default_root() -> Path:
    """默认数据根：与历史版本保持一致（LOCALAPPDATA\\BiliLearn）。"""
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "BiliLearn"
    return Path.home() / "AppData" / "Local" / "BiliLearn"


def pointer_path() -> Path:
    return default_root() / "Data" / POINTER_NAME


def read_pointer() -> Path | None:
    """读取已保存的数据目录；没有配置或配置非法时返回 None。"""
    try:
        payload = json.loads(pointer_path().read_text(encoding="utf-8-sig"))
        target = str(payload.get("path") or "").strip()
        if not target:
            return None
        candidate = Path(target).expanduser().resolve()
        if candidate == candidate.anchor or len(str(candidate)) <= 3:
            return None
        return candidate
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def save_pointer(target: Path) -> Path:
    path = pointer_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "path": str(Path(target).expanduser().resolve()),
        "updated_at": _now_iso(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def clear_pointer() -> bool:
    """删除指针（恢复默认目录）。返回是否真的删掉了文件。"""
    try:
        pointer_path().unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StoragePathError(f"删除存储位置记录失败：{exc}") from exc


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def program_dirs() -> list[Path]:
    """不应被当作数据目录的程序目录（重装/升级会被覆盖）。"""
    dirs: list[Path] = [Path(__file__).resolve().parents[1]]
    if getattr(sys, "frozen", False):
        try:
            dirs.append(Path(sys.executable).resolve().parent)
        except OSError:
            pass
    return dirs


def _system_dirs() -> list[Path]:
    candidates = [
        os.getenv("SystemRoot", ""),
        os.getenv("WINDIR", ""),
        os.getenv("ProgramFiles", ""),
        os.getenv("ProgramFiles(x86)", ""),
        os.getenv("ProgramData", ""),
    ]
    result: list[Path] = []
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            result.append(Path(text).resolve())
        except OSError:
            continue
    return result


def is_inside(child: Path, parent: Path) -> bool:
    """child 是否位于 parent 之内（含相等）。按大小写不敏感比较，兼容 Windows。"""
    try:
        child_resolved = Path(child).resolve()
        parent_resolved = Path(parent).resolve()
    except OSError:
        return False
    if child_resolved == parent_resolved:
        return True
    try:
        child_resolved.relative_to(parent_resolved)
        return True
    except ValueError:
        return False


def normalize(raw: str | os.PathLike[str]) -> Path:
    """把用户输入变成绝对路径，并拒绝相对路径。"""
    text = str(raw or "").strip().strip('"').strip("'")
    if not text:
        raise StoragePathError("请填写数据目录")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise StoragePathError("请填写绝对路径，例如 D:\\BiliLearnData")
    try:
        return candidate.resolve()
    except OSError as exc:
        raise StoragePathError(f"路径无法解析：{exc}") from exc


def validate_target(raw: str | os.PathLike[str], *, current_root: Path | None = None) -> Path:
    """校验候选数据目录；不合法时抛 StoragePathError，合法时返回绝对路径。

    只做检查与必要的目录创建，不改指针，方便前端先校验再确认。
    """
    target = normalize(raw)
    text = str(target)

    if len(text) < MIN_PATH_LENGTH or target == target.anchor or target.parent == target:
        raise StoragePathError("不能使用磁盘根目录，请选择具体文件夹")

    for system_dir in _system_dirs():
        if is_inside(target, system_dir):
            raise StoragePathError(f"不能使用系统目录：{system_dir}")

    for program_dir in program_dirs():
        if is_inside(target, program_dir):
            raise StoragePathError("不能使用程序所在目录，升级或重装会覆盖其中的数据")

    if current_root is not None and is_inside(target, Path(current_root)):
        raise StoragePathError("新目录不能位于当前数据目录内部")

    if target.exists() and not target.is_dir():
        raise StoragePathError("该路径已存在且不是文件夹")

    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / _WRITE_PROBE
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise StoragePathError(f"目录不可写：{exc}") from exc

    return target


def migrate_contents(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> dict:
    """把旧目录里目标缺失的文件补到新目录（不覆盖、不删除源文件）。"""
    source_path = Path(source).expanduser().resolve()
    target_path = Path(target).expanduser().resolve()
    stats = {"copied_files": 0, "copied_bytes": 0, "skipped_files": 0, "source": str(source_path), "target": str(target_path)}
    if source_path == target_path:
        stats["skipped"] = True
        return stats
    if is_inside(target_path, source_path):
        raise StoragePathError("新目录不能位于当前数据目录内部")
    if not source_path.is_dir():
        stats["skipped"] = True
        return stats

    target_path.mkdir(parents=True, exist_ok=True)
    for item in source_path.rglob("*"):
        relative = item.relative_to(source_path)
        destination = target_path / relative
        try:
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not item.is_file():
                continue
            if item.name in _SKIP_ON_MIGRATE or item.name.endswith(_SKIP_ON_MIGRATE_SUFFIXES):
                continue
            if destination.exists():
                stats["skipped_files"] += 1
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            stats["copied_files"] += 1
            stats["copied_bytes"] += item.stat().st_size
        except OSError:
            # 单个文件被占用（例如运行中的日志）时跳过，不中断整体迁移。
            stats["skipped_files"] += 1
    return stats


def disk_stats(path: str | os.PathLike[str]) -> dict:
    """返回目录所在磁盘的容量信息；不可用时返回空字典。"""
    try:
        usage = shutil.disk_usage(str(path))
    except OSError:
        return {}
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def describe(raw: str | os.PathLike[str]) -> dict:
    """给面板用的只读信息（是否存在、文件数、占用、剩余空间）。"""
    path = Path(raw).expanduser()
    files = 0
    size = 0
    if path.is_dir():
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    files += 1
                    size += item.stat().st_size
        except OSError:
            pass
    return {
        "path": str(path),
        "exists": path.is_dir(),
        "files": files,
        "bytes": size,
        "disk": disk_stats(path if path.is_dir() else path.parent),
    }
