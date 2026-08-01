"""Private user-data storage and one-time legacy migration."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

def _default_user_data_dir() -> Path:
    """Use a per-user writable location for releases, never the app folder."""
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "BiliLearn"
    return Path.home() / "AppData" / "Local" / "BiliLearn"


_EXPLICIT_USER_DATA_DIR = bool(os.getenv("BILI_USER_DATA_DIR", "").strip())
USER_DATA_DIR = Path(os.getenv("BILI_USER_DATA_DIR", "")).expanduser() if _EXPLICIT_USER_DATA_DIR else _default_user_data_dir()
DATA_DIR = USER_DATA_DIR / "Data"
# A frozen app's resource directory is its distributable payload. Never write
# user-generated knowledge or exports there: someone may later share that
# application folder with another person.
if getattr(sys, "frozen", False):
    PROJECT_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    ARTIFACTS_DIR = USER_DATA_DIR
else:
    PROJECT_DIR = Path(__file__).resolve().parents[1]
    ARTIFACTS_DIR = PROJECT_DIR

# Private runtime data always lives under the user profile. Source checkouts
# retain portable project artifacts, while frozen releases keep every generated
# artifact in the current Windows user's BiliLearn directory.
KNOWLEDGE_BASE_DIR = ARTIFACTS_DIR / "KnowledgeBase"
HIGHLIGHTS_DIR = ARTIFACTS_DIR / "highlights"
HTML_EXPORTS_DIR = ARTIFACTS_DIR / "html_exports"
MINDMAPS_DIR = ARTIFACTS_DIR / "MindMaps"
WORD_DIR = ARTIFACTS_DIR / "Word"
QR_CODES_DIR = USER_DATA_DIR / "qr_codes"

_PRIVATE_DIRECTORIES = {
    "Data": DATA_DIR,
    "qr_codes": QR_CODES_DIR,
}
_PROJECT_DIRECTORIES = {
    "KnowledgeBase": KNOWLEDGE_BASE_DIR,
    "highlights": HIGHLIGHTS_DIR,
    "html_exports": HTML_EXPORTS_DIR,
    "MindMaps": MINDMAPS_DIR,
    "Word": WORD_DIR,
}
_LEGACY_FILES = (
    "bot_memory.json",
    "bot_journal.md",
    "knowledge_metadata.json",
    "learning_log.md",
    ".cipher_key",
)


def _copy_missing(source: Path, destination: Path) -> None:
    if source.is_dir():
        for item in source.rglob("*"):
            relative = item.relative_to(source)
            target = destination / relative
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    elif source.is_file() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _merge_legacy_api_settings(source: Path, destination: Path) -> None:
    """Preserve a local user's API setup when moving to LocalAppData."""
    try:
        old_config = json.loads(source.read_text(encoding="utf-8"))
        new_config = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    old_api = old_config.get("api") if isinstance(old_config, dict) else None
    new_api = new_config.get("api") if isinstance(new_config, dict) else None
    if not isinstance(old_api, dict):
        return
    if not isinstance(new_api, dict):
        new_api = {}
        new_config["api"] = new_api
    changed = False
    for key, value in old_api.items():
        if value and not new_api.get(key):
            new_api[key] = value
            changed = True
    if changed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(new_config, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_user_data_dir() -> Path:
    """Create storage and perform non-destructive compatibility migrations."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for directory in (*_PRIVATE_DIRECTORIES.values(), *_PROJECT_DIRECTORIES.values()):
        directory.mkdir(parents=True, exist_ok=True)

    # Releases before 3.1.2 stored runtime data directly under the user home.
    # Move it locally on this machine only; this never affects the distributable.
    old_user_root = Path.home() / "BiliLearn"
    local_migration_marker = USER_DATA_DIR / ".local_appdata_migration_v1_done"
    # An explicitly supplied directory is an isolated or portable profile.
    # Never import credentials or memories from the host profile into it.
    if (
        not _EXPLICIT_USER_DATA_DIR
        and not local_migration_marker.exists()
        and old_user_root.resolve() != USER_DATA_DIR.resolve()
        and old_user_root.exists()
    ):
        _copy_missing(old_user_root / "Data", DATA_DIR)
        for name in ("bilibili_cookies.json",):
            _copy_missing(old_user_root / "Data" / name, DATA_DIR / name)
        _merge_legacy_api_settings(old_user_root / "Data" / "config.json", DATA_DIR / "config.json")
        for name in (*_LEGACY_FILES, "KnowledgeBase", "highlights", "html_exports", "MindMaps", "Word", "qr_codes"):
            _copy_missing(old_user_root / name, USER_DATA_DIR / name)
        local_migration_marker.write_text("Legacy user data migrated to LocalAppData.\n", encoding="utf-8")

    marker = USER_DATA_DIR / ".legacy_migration_v1_done"
    if not marker.exists():
        for legacy_name, target_dir in _PRIVATE_DIRECTORIES.items():
            _copy_missing(PROJECT_DIR / legacy_name, target_dir)
        for legacy_name in _LEGACY_FILES:
            _copy_missing(PROJECT_DIR / legacy_name, USER_DATA_DIR / legacy_name)
        marker.write_text("Legacy private runtime data copied to user storage.\n", encoding="utf-8")

    # An earlier migration briefly placed knowledge and exports under
    # ~/BiliLearn. Restore any missing files to their project-owned defaults,
    # preserving both copies and never overwriting newer project files.
    layout_marker = USER_DATA_DIR / ".project_layout_v2_done"
    if not layout_marker.exists():
        for name, project_dir in _PROJECT_DIRECTORIES.items():
            _copy_missing(USER_DATA_DIR / name, project_dir)
        layout_marker.write_text("Project knowledge/export layout reconciled.\n", encoding="utf-8")

    # Earlier releases stored portable learning artifacts under the user-data
    # root.  Keep the project-owned library readable after that migration too;
    # copying only missing files is idempotent and never overwrites a note.
    for name, project_dir in _PROJECT_DIRECTORIES.items():
        _copy_missing(USER_DATA_DIR / name, project_dir)
    return USER_DATA_DIR


ensure_user_data_dir()
