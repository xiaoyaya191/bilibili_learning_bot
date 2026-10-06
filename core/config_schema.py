"""Typed validation preserving legacy and installed-plugin configuration."""
from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, create_model, ValidationError


class Section(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True, allow_inf_nan=False)


class RagSettings(Section):
    enabled: bool = False
    embedding_model: str = ''
    reranker_model: str = ''
    allow_lexical_fallback: bool = True
    chunk_size: int = Field(default=900, ge=200, le=3000)
    chunk_overlap: int = Field(default=120, ge=0, le=1500)
    candidate_count: int = Field(default=30, ge=1, le=200)
    max_context_chunks: int = Field(default=5, ge=1, le=20)
    context_chars: int = Field(default=6000, ge=500, le=30000)
    enable_function_calling: bool = True


class AlignmentSettings(Section):
    enabled: bool = True
    embedding_model: str = ''
    threshold: float = Field(default=0.25, ge=-1, le=1)
    chunk_size: int = Field(default=900, ge=200, le=3000)
    fetch_attempts: int = Field(default=3, ge=1, le=5)
    whisper_fallback: bool = True


class ImageSettings(Section):
    width: int = Field(default=1200, ge=600, le=2400)
    height: int = Field(default=1600, ge=800, le=3200)
    font_size: int = Field(default=32, ge=18, le=72)
    background: str = ''
    overlay: float = Field(default=0.9, ge=0.6, le=1)


class ProviderSettings(Section):
    plugin: str = 'openai-compatible'


class PermissionSettings(Section):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = False
    actions: dict[str, bool] = Field(default_factory=dict)


class FavoriteSettings(Section):
    destination: Literal['local', 'platform'] = 'local'
    auto_collect_enabled: bool = True
    min_score: float = Field(default=8.0, ge=0, le=10)
    folder_name: str = 'AI 精选'
    require_interest_match: bool = True


class SubtitleSettings(Section):
    enabled: bool = True


def validate_config(value, defaults):
    if not isinstance(value, dict):
        raise ValueError('配置根节点必须为对象')
    fields = {}
    for name, default in defaults.items():
        if isinstance(default, dict):
            members = {key: (type(item), Field(default_factory=lambda item=item: deepcopy(item)) if isinstance(item, (dict, list)) else item)
                       for key, item in default.items() if item is not None}
            section = create_model(name + 'Section', __base__=Section, **members)
            fields[name] = (section, Field(default_factory=section))
        elif default is not None:
            fields[name] = (type(default), Field(default_factory=lambda default=default: deepcopy(default)) if isinstance(default, list) else default)
    for name, section in {'rag_qa': RagSettings, 'subtitle_alignment': AlignmentSettings,
                          'image_export': ImageSettings, 'model_provider': ProviderSettings,
                          'ai_permissions': PermissionSettings, 'local_favorites': FavoriteSettings,
                          'subtitles': SubtitleSettings}.items():
        fields[name] = (section, Field(default_factory=section))
    schema = create_model('ProjectConfig', __base__=Section, **fields)
    try:
        checked = schema.model_validate(value).model_dump()
    except ValidationError as error:
        messages = ['.'.join(str(part) for part in issue['loc']) + ': ' + issue['msg']
                    for issue in error.errors(include_input=False, include_url=False)]
        raise ValueError('配置格式无效: ' + '; '.join(messages)) from None
    if checked['rag_qa']['chunk_overlap'] >= checked['rag_qa']['chunk_size']:
        raise ValueError('RAG 分块重叠必须小于分块长度')
    from services.action_permissions import ACTIONS
    if set(checked['ai_permissions']['actions']) - set(ACTIONS):
        raise ValueError('未知 AI 操作权限')
    from services.model_providers import get_provider
    get_provider(checked['model_provider']['plugin'])
    return checked
