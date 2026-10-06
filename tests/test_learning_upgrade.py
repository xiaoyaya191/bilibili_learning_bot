import asyncio
import io
import json
from pathlib import Path

import pytest

from services.interest_engine import InterestEngine
from services.semantic_vectors import encode, alignment
from services.subtitle_candidates import fetch_candidates
from services.vector_retrieval import retrieve
from core.config_schema import validate_config
from services.model_providers import register_provider, get_provider


def test_stale_worker_preserves_manual_edits_and_deletions(tmp_path):
    path = str(tmp_path / 'interest_engine.json')
    original = InterestEngine(path)
    original.add_interest('Python')
    stale = InterestEngine(path)
    editor = InterestEngine(path)
    editor.add_interest('历史')
    editor.remove_interest('Python')
    stale.record_watched(tags='coding')
    current = InterestEngine(path)
    assert current.get_keywords() == ['历史']
    assert current.config['videos_watched_count'] == 1


def test_unicode_duplicates_and_concurrent_additions(tmp_path):
    path = str(tmp_path / 'interest_engine.json')
    first = InterestEngine(path)
    second = InterestEngine(path)
    assert first.add_interest('ＰＹＴＨＯＮ')
    assert not second.add_interest('python')
    assert second.add_interest('历史')
    first.record_watched(tags='Python')
    assert set(InterestEngine(path).get_keywords()) == {'python', '历史'}


def test_automatic_interest_cap_and_manual_protection(tmp_path):
    engine = InterestEngine(str(tmp_path / 'interest_engine.json'))
    engine.settings.update(ai_suggest=True, ai_suggest_probability=1.0,
                           max_auto_interests=2, max_suggestions_per_batch=1)
    engine.save()
    engine.add_interest('Python', weight='high')
    assert engine.apply_ai_suggestions(['Python', 'AI']) == 0
    assert engine.apply_ai_suggestions(['AI', '历史']) == 1
    assert engine.add_interest('数学', auto_suggested=True)
    assert not engine.add_interest('物理', auto_suggested=True)
    assert engine.interests_list[0]['weight'] == 'high'


def test_corrupt_interests_not_replaced(tmp_path):
    path = tmp_path / 'interest_engine.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError):
        InterestEngine(str(path))
    assert path.read_text() == '{broken'


def test_worker_counters_accumulate(tmp_path):
    path = str(tmp_path / 'interest_engine.json')
    first = InterestEngine(path)
    second = InterestEngine(path)
    first.record_watched(tags='one')
    second.record_watched(tags='two')
    assert InterestEngine(path).config['videos_watched_count'] == 2


def test_vector_index_updates_removes_and_limits_context(tmp_path):
    root = tmp_path / 'kb'
    root.mkdir()
    note = root / 'python.md'
    note.write_text('Python 装饰器函数参数' * 250, encoding='utf-8')
    unrelated = root / 'music.md'
    unrelated.write_text('音乐歌唱钢琴', encoding='utf-8')
    options = {'_cache_dir': str(tmp_path), 'context_chars': 700, 'chunk_size': 200, 'chunk_overlap': 30}
    found = retrieve('Python 装饰器', root, options, 5)
    assert found[0]['path'] == 'python.md'
    assert found[0]['backend'] == 'lexical-hash-v1'
    assert sum(len(item['snippet']) for item in found) <= 700
    assert found[0]['reranker'] == 'lexical-frequency'
    note.unlink()
    assert all(item['path'] != 'python.md' for item in retrieve('Python', root, options))


def test_rag_selected_files_are_restricted(tmp_path):
    root = tmp_path / 'kb'
    root.mkdir()
    first = root / 'one.md'; second = root / 'two.md'
    first.write_text('Python 函数', encoding='utf-8')
    second.write_text('Python 函数参数教程', encoding='utf-8')
    found = retrieve('Python', root, {'_cache_dir': str(tmp_path)}, allowed_paths=[first])
    assert found and all(item['path'] == 'one.md' for item in found)


def test_semantic_alignment_uses_embedding_and_does_not_fake_lexical(monkeypatch):
    assert alignment('Title', '', 'Content', {})['status'] == 'unavailable'
    monkeypatch.setattr('services.semantic_vectors.encode', lambda texts, model: ([[1.0, 0.0], [0.0, 1.0]], 'semantic:mock'))
    assert alignment('Title', '', 'Content', {'embedding_model': 'mock'})['status'] == 'mismatch'


def test_subtitles_retry_empty_and_compare_coverage(monkeypatch):
    async def no_sleep(delay):
        pass
    monkeypatch.setattr('services.subtitle_candidates.asyncio.sleep', no_sleep)
    bodies = [[], [{'from': 0, 'to': 10, 'content': '短字幕'}],
              [{'from': 0, 'to': 60, 'content': '更完整的字幕'}]]
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'body': bodies.pop(0)}
    class Client:
        async def get(self, url):
            return Response()
    result = asyncio.run(fetch_candidates(Client(), 'https://example.test/subtitle', 3))
    assert result[0]['to'] == 60
    assert not bodies


def test_configuration_rejects_bad_types_preserves_unknown():
    from core.config import DEFAULT_CONFIG
    value = validate_config({'rag_qa': {'enabled': True}, 'custom_extension': {'hello': 1}}, DEFAULT_CONFIG)
    assert value['custom_extension'] == {'hello': 1}
    with pytest.raises(ValueError):
        validate_config({'rag_qa': {'enabled': 'false'}}, DEFAULT_CONFIG)
    with pytest.raises(ValueError):
        validate_config({'rag_qa': {'chunk_size': 200, 'chunk_overlap': 500}}, DEFAULT_CONFIG)


def test_provider_registration_interface():
    class Plugin:
        async def chat(self, *args, **kwargs):
            return {'content': 'ok'}
    plugin = Plugin()
    identifier = 'learning-upgrade-test'
    import services.model_providers as registry
    registry._PROVIDERS.pop(identifier, None)
    try:
        register_provider(identifier, plugin)
        assert get_provider(identifier) is plugin
        assert asyncio.run(get_provider(identifier).chat()) == {'content': 'ok'}
        with pytest.raises(ValueError):
            register_provider(identifier, plugin)
    finally:
        registry._PROVIDERS.pop(identifier, None)


def test_image_export_returns_real_pages_and_custom_background(tmp_path):
    from PIL import Image
    from services.image_export import render_images
    background = tmp_path / 'bg.png'
    Image.new('RGB', (400, 600), '#ccaa88').save(background)
    result = render_images('知识内容：Python 函数的参数与返回值。\n' * 70,
                           '视频学习笔记', tmp_path / 'exports', {'background': str(background)})
    assert result['pages'] > 1
    assert Path(result['path']).is_dir()
    assert all(Path(path).is_file() for path in result['paths'])
    with Image.open(result['paths'][0]) as image:
        assert image.size == (1200, 1600)
    with pytest.raises(ValueError):
        render_images('', 'Empty', tmp_path)


def test_image_export_uses_project_watermark():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / 'services' / 'image_export.py').read_text(encoding='utf-8')
    assert "'BILIBILI_LEARNING_BOT'" in source
    assert "'BILIBILI  /  LEARNING NOTES'" not in source


def test_learning_routes_account_background_and_zip(tmp_path, monkeypatch):
    import web_panel
    path = tmp_path / 'config.json'
    path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel, 'CONFIG_FILE', path)
    monkeypatch.setattr(web_panel.app, 'testing', True)
    client = web_panel.app.test_client()
    with client.session_transaction() as session:
        session['disclaimer_agreed'] = True
        session['panel_authenticated'] = True
    loaded = client.get('/api/learning/settings')
    assert loaded.status_code == 200
    assert loaded.get_json()['settings']['subtitle_alignment']['fetch_attempts'] == 3
    assert client.post('/api/learning/settings', json={'rag_qa': {'enabled': 'false'}}).status_code == 400
    assert client.post('/api/learning/settings', json={'image_export': {'background': str(tmp_path.parent / 'other.png')}}).status_code == 400
    result = client.post('/api/learning/export-images', json={'title': '视频笔记', 'content': 'Python 函数基础知识'})
    assert result.status_code == 200
    assert result.data.startswith(b'PK')


def test_semantic_candidate_preferred_over_longer_wrong_track(monkeypatch):
    async def no_sleep(delay):
        pass
    monkeypatch.setattr('services.subtitle_candidates.asyncio.sleep', no_sleep)
    bodies = [[{'from': 0, 'to': 600, 'content': '错误缓存'}],
              [{'from': 0, 'to': 120, 'content': '正确字幕'}]]
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'body': bodies.pop(0)}
    class Client:
        async def get(self, url):
            return Response()
    found = asyncio.run(fetch_candidates(Client(), 'https://example.test/subtitle', 2,
                        lambda text: {'status': 'match' if '正确' in text else 'mismatch'}))
    assert found[0]['content'] == '正确字幕'


def test_whisper_fallback_respects_live_asr_setting(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import brain._brain_video as module
    import xingye_bot.asr_engine as asr_module
    from brain._brain_video import BrainVideoMixin
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'fake')
    captured = []
    async def subtitle(*args, **kwargs):
        return False, '[字幕语义不匹配:WHISPER_FALLBACK]', '简介', False
    class ASR:
        def __init__(self, config):
            captured.append(config)
        @staticmethod
        def should_skip_asr(**kwargs):
            return True, 'short video'
        def is_available(self):
            return True
        def has_ffmpeg(self):
            return True
        async def process_video(self, path, title):
            return SimpleNamespace(success=True, text='Python 讲解', segments=[], timing={})
        @staticmethod
        def format_result(result):
            return result.text
        @staticmethod
        def timing_summary(result, **kwargs):
            return 'timing'
    class Brain(BrainVideoMixin):
        cookies = {}
        @staticmethod
        def _is_vision_globally_disabled():
            return True
        async def _download_video_for_asr(self, *args, **kwargs):
            return str(video), 0, 1
    monkeypatch.setattr(module, 'fetch_bilibili_subtitles', subtitle)
    monkeypatch.setattr(module, 'config', {'subtitle_alignment': {'whisper_fallback': True}, 'vision': {'frames_enabled': False}})
    monkeypatch.setattr(module, 'ASR_ENABLED', False)
    monkeypatch.setattr('core.config.load_config', lambda: {'asr': {'enabled': True}, 'subtitles': {'enabled': True}})
    monkeypatch.setattr(module, 'SUBTITLE_STRICT_CHECK', False)
    monkeypatch.setattr(asr_module, 'ASREngine', ASR)
    ok, content = asyncio.run(Brain()._understand_super_smart('BV1ab411c7mD', 'Python'))
    assert ok and 'Python 讲解' in content
    assert captured == [{'backend': 'whisper', 'enabled': True, 'local_only': True}]
    assert not video.exists()


def test_configuration_failure_does_not_encrypt_caller_or_overwrite(tmp_path, monkeypatch):
    import core.config as module
    path = tmp_path / 'config.json'
    path.write_text('{broken', encoding='utf-8')
    monkeypatch.setattr(module, 'CONFIG_FILE', str(path))
    with pytest.raises(ValueError):
        module.load_config()
    assert path.read_text() == '{broken'
    config = {'reply_safety': {'blocked_keywords': ['敏感测试词']}}
    monkeypatch.setattr(module.JsonStore, 'write', lambda self, value: False)
    assert module.save_config(config) is False
    assert config['reply_safety']['blocked_keywords'] == ['敏感测试词']


def test_provider_transport_dispatch_removes_old_content_length():
    import services.model_providers as module
    captured = []
    class Provider:
        async def chat(self, client, url, payload, **kwargs):
            captured.append((payload, kwargs))
            return 'response'
    identifier = 'learning-transport-test'
    module._PROVIDERS.pop(identifier, None)
    module.register_provider(identifier, Provider())
    try:
        result = asyncio.run(module.provider_post(None, 'https://api.example.test/chat/completions',
                              provider=identifier, content=b'{"model":"mock","messages":[]}', model='mock',
                              source='test', headers={'Content-Length': '100', 'Authorization': 'Bearer mock'}))
        assert result == 'response'
        assert captured[0][0]['model'] == 'mock'
        assert 'Content-Length' not in captured[0][1]['headers']
    finally:
        module._PROVIDERS.pop(identifier, None)


def test_rag_function_tools_use_chunks_and_return_sources(tmp_path, monkeypatch):
    import services.rag_qa as module
    from core.user_data import DATA_DIR
    root = tmp_path / 'kb'
    root.mkdir()
    (root / 'python.md').write_text('Python 参数和函数。' * 1000, encoding='utf-8')
    monkeypatch.setattr(module, 'resolve_knowledge_base_dir', lambda cfg: str(root))
    captured = []
    async def call(**kwargs):
        result = await kwargs['tool_handler']('open_note', {'path': 'python.md'})
        captured.append(result)
        assert len(result) < 10000
        return '函数的知识见 python.md'
    monkeypatch.setattr('services._services_ai.call_ai_with_tools', call)
    result = asyncio.run(module.answer_question('Python 参数', {'rag_qa': {
        'enabled': True, 'enable_function_calling': True, '_cache_dir': str(tmp_path), 'context_chars': 1200}}))
    assert result['ok'] and result['sources']
    assert all('chunk' in source for source in result['sources'])
    assert captured and '来源：python.md' in captured[0]


def test_background_upload_saved_and_used_by_export(tmp_path, monkeypatch):
    import web_panel
    from PIL import Image
    config = tmp_path / 'config.json'
    config.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel, 'CONFIG_FILE', config)
    monkeypatch.setattr(web_panel.app, 'testing', True)
    client = web_panel.app.test_client()
    image = io.BytesIO()
    Image.new('RGB', (300, 500), '#778899').save(image, 'JPEG')
    image.seek(0)
    response = client.post('/api/learning/background', data={'file': (image, 'background.jpg')})
    assert response.status_code == 200
    path = Path(response.get_json()['path'])
    assert path.parent == tmp_path / 'image_backgrounds'
    assert path.suffix == '.png'
    with Image.open(path) as converted:
        assert converted.format == 'PNG'
    saved = client.post('/api/learning/settings', json={'image_export': {'background': str(path)}})
    assert saved.status_code == 200
    result = client.post('/api/learning/export-images', json={'content': '背景图片测试', 'title': '知识笔记'})
    assert result.status_code == 200 and result.data.startswith(b'PK')
    invalid = client.post('/api/learning/background', data={'file': (io.BytesIO(b'not an image'), 'bad.png')})
    assert invalid.status_code == 400


def test_interest_caps_round_trip_and_invalid_configuration_rejected(tmp_path, monkeypatch):
    import web_panel
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel.app, 'testing', True)
    client = web_panel.app.test_client()
    response = client.post('/api/interest-engine', json={'max_auto_interests': 7, 'max_suggestions_per_batch': 2})
    assert response.status_code == 200
    assert response.get_json()['settings']['max_auto_interests'] == 7
    assert client.get('/api/interest-engine').get_json()['settings']['max_suggestions_per_batch'] == 2
    assert client.post('/api/interest-engine', json={'max_auto_interests': -1}).status_code == 400
