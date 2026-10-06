import asyncio
import json
import httpx
import pytest
from services import direct_video
from services.direct_video import settings, encode_video, analyze
from xingye_bot import visual_preview


def preferences(**values):
    return settings({'enabled': True, 'capability_confirmed': True, 'model': 'video-model', **values})


@pytest.fixture
def video(tmp_path):
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'\x00\x00\x00\x18ftypisom' + b'\x00' * 20)
    return path


def test_default_off_and_capability_required():
    assert not settings({})['enabled']
    with pytest.raises(ValueError):
        settings({'enabled': True})


@pytest.mark.parametrize('values', [{'enabled': 'true'}, {'max_size_mb': 129}, {'max_duration_seconds': 0},
                                     {'timeout_seconds': 1}, {'max_tokens': 99}, {'model': None}, {'unknown': True}, {'max_size_mb': True}])
def test_invalid_settings(values):
    with pytest.raises(ValueError):
        settings(values)


@pytest.mark.parametrize('duration', [0, 301, float('nan'), True])
def test_duration_budget(video, duration):
    with pytest.raises(ValueError):
        encode_video(video, preferences(), duration)


def test_size_format_and_missing_file(video):
    assert encode_video(video, preferences(), 30).startswith('data:video/mp4;base64,')
    video.write_bytes(b'\x00\x00\x00\x18ftypisom' + b'\x00' * (1024 * 1024))
    with pytest.raises(ValueError, match='大小'):
        encode_video(video, preferences(max_size_mb=1), 30)
    video.write_bytes(b'fake video')
    with pytest.raises(ValueError, match='容器'):
        encode_video(video, preferences(), 30)
    with pytest.raises(ValueError):
        encode_video(video.with_suffix('.m4s'), preferences(), 30)


def test_direct_transport_uses_dedicated_model_without_pool(video, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body['model'] == 'video-model'
        part = body['messages'][1]['content'][1]
        assert part['type'] == 'video_url'
        assert part['video_url']['url'].startswith('data:video/mp4;base64,')
        assert '凭据' in body['messages'][0]['content']
        assert request.headers['Authorization'] == 'Bearer video-key'
        return httpx.Response(200, json={'choices': [{'message': {'content': '视频分析'}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(direct_video.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    config = {'api': {'vision_base_url': 'https://video.example/v1', 'vision_api_key': 'video-key'}, 'api_pool': {'enabled': True}}
    assert asyncio.run(analyze(video, '标题', 30, preferences=preferences(), config_data=config)) == '视频分析'
    assert len(calls) == 1 and str(calls[0].url) == 'https://video.example/v1/chat/completions'


@pytest.mark.parametrize('code', [400, 402, 413, 429, 500, 307])
def test_provider_errors_never_retry_or_expose_credentials(video, monkeypatch, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(code, json={'error': 'key=secret'}, headers={'Location': 'https://other.example'})
    original = httpx.AsyncClient
    monkeypatch.setattr(direct_video.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ValueError) as failure:
        asyncio.run(analyze(video, '标题', 30, preferences=preferences(use_vision_endpoint=False), config_data={'api': {'unified_base_url': 'https://api.example/v1', 'unified_api_key': 'secret'}}))
    assert 'secret' not in str(failure.value)
    assert len(calls) == 1


def test_native_video_precedes_frames_and_uses_metadata_gate(video, monkeypatch):
    purposes = []
    async def call(blocks, purpose):
        purposes.append(purpose)
        return '{"skip":false}'
    async def native(*args, **kwargs):
        return '完整原视频分析'
    def forbidden(*args, **kwargs):
        raise AssertionError('should not extract frames')
    monkeypatch.setattr(direct_video, 'analyze', native)
    monkeypatch.setattr(visual_preview, 'extract_visual_note_grids', forbidden)
    result = asyncio.run(visual_preview.analyze_visual_preview(video, '标题', call, {'direct_video': preferences()}, duration=30))
    assert result['completed'] and result['input_mode'] == 'native_video'
    assert purposes == ['video-visual-metadata']


def test_no_fallback_when_frames_disabled(video, monkeypatch):
    async def call(*args):
        return '{"skip":false}'
    async def native(*args, **kwargs):
        raise ValueError('不兼容')
    def forbidden(*args, **kwargs):
        raise AssertionError('frames are disabled')
    monkeypatch.setattr(direct_video, 'analyze', native)
    monkeypatch.setattr(visual_preview, 'extract_visual_note_grids', forbidden)
    result = asyncio.run(visual_preview.analyze_visual_preview(video, '标题', call, {'direct_video': preferences(), 'frames_allowed': False}, duration=30))
    assert not result['completed'] and result['input_mode'] == 'native_video_failed'


def test_metadata_skip_never_uploads(video, monkeypatch):
    async def call(*args):
        return '{"skip":true}'
    async def forbidden(*args, **kwargs):
        raise AssertionError('should not upload')
    monkeypatch.setattr(direct_video, 'analyze', forbidden)
    result = asyncio.run(visual_preview.analyze_visual_preview(video, '标题', call, {'direct_video': preferences()}, duration=30))
    assert not result['completed']
