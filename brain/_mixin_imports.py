"""brain/_mixin_imports.py — 所有 AgentBrain mixin 模块的共享导入"""
import asyncio
import json
import os
import random
import re
import time
import sys
import shutil
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import httpx
from openai import OpenAI
from colorama import Fore, Style
from bilibili_api import Credential, user, homepage, comment, video, Danmaku, favorite_list
from bilibili_api.comment import CommentResourceType
from bilibili_api.video import Video
from bilibili_api.utils.network import Api

from core.config import *
from core.globals import *
from api.subtitles import SYSTEM_PROMPT_BRAIN, SYSTEM_PROMPT_VISION, SYSTEM_PROMPT_SUMMARY
from persona.managers import PersonaManager, MoodManager, UserProfileManager, BotDiaryManager, SelfEvolutionManager, PrivateContextDB
from security.guard import ReplySafetyGuard
from services.utils import InterestManager, BiliToolbox
from services.agent_service import AgentSkillRunner
from services.knowledge_tutor import KnowledgeTutor, scan_md_files, read_md_file, write_md_file
from utils.display import log, mask_secret
from utils.helpers import _mask_urls, sanitize_filename, ensure_ai_marker, human_reply_delay, _clean_ai_output, _load_json_file, _save_json_file, _safe_task_callback, find_ffmpeg, find_ffprobe
from utils.lock import _acquire_bot_lock, _release_bot_lock
from api.throttle import _bili_throttle, _bili_trigger_cooldown, _BILI_API_MIN_GAP
from api.client import BiliClient
from api.auth import login_bilibili, is_bili_logged_in, check_login_status, clear_login_info
from api.subtitles import fetch_bilibili_subtitles, _check_subtitle_mismatch
from brain.comment import CommentInteractionManager
from brain.private_msg import PrivateMessageManager
from knowledge.classifier import KnowledgeBaseClassifier
from knowledge.web_search import web_search, verify_knowledge_with_ai, backup_and_rewrite_knowledge
from knowledge.browse import count_knowledge_categories, browse_kb_structure, search_knowledge_content, cleanup_duplicates
from persona.psycho import PsychoProfile, RecommendationEngine, get_mode_emoji, get_mode_label
from utils.storage import get_backup_dir, sanitize_config_for_export

# Optional xingye_bot imports
try:
    from xingye_bot.llm import ModelClient
    from xingye_bot.settings import load_settings as load_modular_settings
    from xingye_bot.state import BotState
    from xingye_bot.video_modes import VideoUnderstanding, normalize_mode
    from xingye_bot.kb_search import KBSearchEngine
except ImportError:
    ModelClient = None
    load_modular_settings = None
    BotState = None
    VideoUnderstanding = None
    normalize_mode = None
    KBSearchEngine = None
