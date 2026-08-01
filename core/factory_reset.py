"""Privacy-safe deletion of all generated BiliLearn user data.

This module deliberately has no dependency on the CLI or the Web panel so both
entry points remove exactly the same private data and generated artifacts.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable


_PROJECT_ARTIFACT_DIRS = (
    "Data", "KnowledgeBase", "highlights", "html_exports", "MindMaps",
    "Word", "qr_codes",
)
_PROJECT_ARTIFACT_FILES = (
    ".cipher_key", "data.json", "knowledge_metadata.json", "learning_log.md",
    "bot_memory.json", "bot_journal.md", "web_panel_stdout.log",
)
_USER_ROOT_FILES = (
    "bot_memory.json", "bot_journal.md", "knowledge_metadata.json",
    "learning_log.md", ".cipher_key", ".legacy_migration_v1_done",
    ".project_layout_v2_done",
)

# The web panel and CLI expose only these fixed group ids. This prevents a
# malformed request from ever expanding a reset into an arbitrary drive path.
RESET_GROUPS = {
    "credentials_runtime": {
        "label": "登录凭证与运行数据",
        "description": "Cookie、二维码、API 配置、网页密码、会话、日志和互动记录",
    },
    "knowledge_generated": {
        "label": "知识库与生成内容",
        "description": "知识库、HTML、思维导图、Word、亮点归档和自定义导出目录",
    },
    "local_models": {
        "label": "本地 ASR 模型",
        "description": "项目 model 目录及配置指定的 ASR 模型目录，之后需要重新下载",
    },
    "project_docs": {
        "label": "项目 docs 内容",
        "description": "项目 docs 目录。确认其中没有要保留的源码文档后再删除",
    },
    "backup_files": {
        "label": "配置备份（默认保留）",
        "description": "手动导出的配置备份。仅在明确勾选后删除，便于恢复出厂后重新导入",
    },
}

# A factory reset should remove live private data, but leave an explicitly
# created backup available for a later import. Selecting ALL still includes it.
DEFAULT_RESET_GROUP_IDS = tuple(group_id for group_id in RESET_GROUPS if group_id != "backup_files")


def _configured_path(value: Any, project_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_dir / path


def _is_safe_target(path: Path, protected: Iterable[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved == Path(resolved.anchor):
        return False
    return all(resolved != item.resolve() for item in protected)

def collect_reset_target_groups(**kwargs: Any) -> dict[str, list[Path]]:
    """Return reset paths grouped by purpose without ever using a drive root."""
    data_dir = Path(kwargs["data_dir"])
    user_data_dir = Path(kwargs["user_data_dir"])
    project_dir = Path(kwargs["project_dir"])
    backup_dir = Path(kwargs["backup_dir"])
    cipher_key_file = Path(kwargs["cipher_key_file"])
    cfg = kwargs.get("config") if isinstance(kwargs.get("config"), dict) else {}
    protected = (project_dir, user_data_dir)

    runtime = [data_dir, cipher_key_file]
    runtime.extend(project_dir / name for name in ("Data", "qr_codes"))
    runtime.extend(project_dir / name for name in _PROJECT_ARTIFACT_FILES)
    runtime.extend(user_data_dir / name for name in _USER_ROOT_FILES)
    runtime.extend(user_data_dir / name for name in ("Data", "qr_codes"))
    runtime.append(user_data_dir / "\u8d26\u53f7\u6062\u590d")
    generated_names = ("KnowledgeBase", "highlights", "html_exports", "MindMaps", "Word")
    generated = [project_dir / name for name in generated_names]
    generated.extend(user_data_dir / name for name in generated_names)
    models = [project_dir / "model"]
    docs = [project_dir / "docs"]
    custom_values = (
        cfg.get("knowledge_base_dir"),
        (cfg.get("knowledge") or {}).get("base_dir") if isinstance(cfg.get("knowledge"), dict) else None,
        (cfg.get("document_export") or {}).get("output_dir") if isinstance(cfg.get("document_export"), dict) else None,
        (cfg.get("document_export") or {}).get("folder_name") if isinstance(cfg.get("document_export"), dict) else None,
        (cfg.get("mindmap") or {}).get("output_dir") if isinstance(cfg.get("mindmap"), dict) else None,
        (cfg.get("dry_goods") or {}).get("folder_name") if isinstance(cfg.get("dry_goods"), dict) else None,
    )
    for value in custom_values:
        path = _configured_path(value, project_dir)
        if path and _is_safe_target(path, protected):
            generated.append(path)
    asr_cfg = cfg.get("asr") if isinstance(cfg.get("asr"), dict) else {}
    model_path = _configured_path(asr_cfg.get("funasr_model_dir"), project_dir)
    if model_path and _is_safe_target(model_path, protected):
        models.append(model_path)

    def unique(paths: Iterable[Path]) -> list[Path]:
        seen: set[Path] = set()
        output: list[Path] = []
        for path in paths:
            try:
                key = path.resolve()
            except OSError:
                key = path.absolute()
            if key not in seen and _is_safe_target(path, protected):
                seen.add(key)
                output.append(path)
        return output

    return {
        "credentials_runtime": unique(runtime),
        "knowledge_generated": unique(generated),
        "local_models": unique(models),
        "project_docs": unique(docs),
        "backup_files": unique([backup_dir]),
    }


def _path_usage(path: Path) -> tuple[int, int]:
    if not path.exists() or path.is_symlink():
        return 0, 0
    if path.is_file():
        try:
            return 1, path.stat().st_size
        except OSError:
            return 0, 0
    files = total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file() and not child.is_symlink():
                try:
                    files += 1
                    total += child.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return files, total


def preview_reset_targets(*, selected_groups: Iterable[str] | None = None, **kwargs: Any) -> dict[str, Any]:
    selected = set(selected_groups or DEFAULT_RESET_GROUP_IDS)
    unknown = selected.difference(RESET_GROUPS)
    if unknown:
        raise ValueError(f"Unknown reset groups: {', '.join(sorted(unknown))}")
    grouped = collect_reset_target_groups(**kwargs)
    groups = []
    for group_id, meta in RESET_GROUPS.items():
        files = total = 0
        paths = grouped[group_id]
        for path in paths:
            count, size = _path_usage(path)
            files += count
            total += size
        groups.append({"id": group_id, **meta, "selected": group_id in selected,
                       "paths": [str(path) for path in paths], "files": files, "bytes": total})
    return {"groups": groups, "selected_groups": [key for key in RESET_GROUPS if key in selected]}


def collect_reset_targets(**kwargs: Any) -> list[Path]:
    """Return every selectable target, including the opt-in backup folder."""
    grouped = collect_reset_target_groups(**kwargs)
    return [path for group_id in RESET_GROUPS for path in grouped[group_id]]


def erase_all_user_data(**kwargs: Any) -> dict[str, Any]:
    """Delete all reset targets and recreate only the empty runtime data dir."""
    data_dir = Path(kwargs["data_dir"])
    selected = set(kwargs.pop("selected_groups", None) or DEFAULT_RESET_GROUP_IDS)
    unknown = selected.difference(RESET_GROUPS)
    if unknown:
        raise ValueError(f"Unknown reset groups: {', '.join(sorted(unknown))}")
    grouped = collect_reset_target_groups(**kwargs)
    targets = [path for group_id in RESET_GROUPS if group_id in selected for path in grouped[group_id]]
    deleted: list[str] = []
    failures: list[str] = []
    for target in targets:
        try:
            if target.is_dir():
                shutil.rmtree(target)
                deleted.append(str(target))
            elif target.exists():
                target.unlink()
                deleted.append(str(target))
        except OSError as exc:
            failures.append(f"{target}: {exc}")
    if "credentials_runtime" in selected:
        data_dir.mkdir(parents=True, exist_ok=True)
    return {"deleted": deleted, "failures": failures, "selected_groups": sorted(selected)}
