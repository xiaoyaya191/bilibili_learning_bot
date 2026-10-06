"""Account-scoped learning settings and safe image upload/export endpoints."""
import io
import uuid
import zipfile
from pathlib import Path
from flask import Blueprint, current_app, request, jsonify, send_file
from PIL import Image, ImageOps
from pydantic import ValidationError
from core.config_schema import RagSettings, AlignmentSettings, ImageSettings, ProviderSettings

blueprint = Blueprint('learning_settings', __name__)
SECTIONS = {'rag_qa': RagSettings, 'subtitle_alignment': AlignmentSettings,
            'image_export': ImageSettings, 'model_provider': ProviderSettings}


def directory():
    return Path(current_app.config['LEARNING_DATA_DIRECTORY']()).resolve()


def read_settings():
    return current_app.config['LEARNING_READ_CONFIG']()


@blueprint.route('/api/learning/settings', methods=['GET', 'POST'])
def settings():
    from services.model_providers import provider_ids, get_provider
    config = read_settings()
    if request.method == 'GET':
        return jsonify(ok=True, settings={name: schema.model_validate(config.get(name, {})).model_dump()
                                          for name, schema in SECTIONS.items()}, providers=provider_ids())
    body = request.get_json(silent=True)
    try:
        if not isinstance(body, dict) or set(body) - set(SECTIONS):
            raise ValueError('仅支持学习设置分区')
        for name, incoming in body.items():
            if not isinstance(incoming, dict):
                raise ValueError(name + ' 必须为对象')
            if set(incoming) - set(SECTIONS[name].model_fields):
                raise ValueError(name + ' 包含未知字段')
            updated = dict(config.get(name, {}), **incoming)
            config[name] = SECTIONS[name].model_validate(updated).model_dump()
        rag = config.get('rag_qa', {})
        if rag.get('chunk_overlap', 120) >= rag.get('chunk_size', 900):
            raise ValueError('分块重叠须小于分块长度')
        get_provider(config.get('model_provider', {}).get('plugin', 'openai-compatible'))
        background = config.get('image_export', {}).get('background', '')
        if background and not Path(background).resolve().is_relative_to(directory() / 'image_backgrounds'):
            raise ValueError('背景须使用当前账号上传的图片')
        if not current_app.config['LEARNING_WRITE_CONFIG'](config):
            raise ValueError('配置保存失败')
        return jsonify(ok=True)
    except (ValueError, TypeError, ValidationError) as error:
        return jsonify(ok=False, message=str(error)), 400


@blueprint.post('/api/learning/background')
def upload_background():
    file = request.files.get('file')
    try:
        if file is None:
            raise ValueError('请选择背景图片')
        raw = file.stream.read(15 * 1024 * 1024 + 1)
        if len(raw) > 15 * 1024 * 1024:
            raise ValueError('背景最多15MB')
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError('背景最多2000万像素')
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('背景只支持PNG、JPEG、WEBP')
            image.load()
            folder = directory() / 'image_backgrounds'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (uuid.uuid4().hex + '.png')
            ImageOps.exif_transpose(image).convert('RGB').save(path, optimize=True)
        return jsonify(ok=True, path=str(path))
    except (ValueError, OSError, Image.DecompressionBombError) as error:
        return jsonify(ok=False, message=str(error)), 400


@blueprint.post('/api/learning/export-images')
def export_images():
    from services.image_export import render_images
    body = request.get_json(silent=True) or {}
    try:
        if not isinstance(body, dict):
            raise ValueError('导出请求必须为对象')
        config = read_settings()
        options = config.get('image_export', {})
        background = options.get('background', '')
        if background and not Path(background).resolve().is_relative_to(directory() / 'image_backgrounds'):
            raise ValueError('背景图片不属于当前账号')
        result = render_images(body.get('content', ''), body.get('title', '视频知识卡片'),
                               directory() / 'image_exports', options)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for path in result['paths']:
                output.write(path, Path(path).name)
        archive.seek(0)
        return send_file(archive, mimetype='application/zip', as_attachment=True,
                         download_name='video-learning-images.zip')
    except (ValueError, TypeError, OSError) as error:
        return jsonify(ok=False, message=str(error)), 400
