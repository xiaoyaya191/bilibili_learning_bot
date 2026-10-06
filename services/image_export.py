"""Readable content cards with measured wrapping and per-export pagination."""
import os
import re
import uuid
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps


def render_images(content, title, directory, options=None, background=None):
    from core.config_schema import ImageSettings
    settings = ImageSettings.model_validate(options or {}).model_dump()
    if not isinstance(content, str) or not content.strip() or len(content) > 500000:
        raise ValueError('导出内容须为1至500000字符')
    width, height, font_size = settings['width'], settings['height'], settings['font_size']
    fonts = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc',
             Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
             Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'),
             Path('/system/fonts/NotoSansCJK-Regular.ttc'),
             Path('/system/fonts/DroidSansFallback.ttf'),
             Path('/System/Library/Fonts/PingFang.ttc')]
    font_path = next((font for font in fonts if font.is_file()), None)
    if font_path is None:
        raise ValueError('未找到中文字体，请安装 Microsoft YaHei 或 Noto Sans CJK')
    font = ImageFont.truetype(str(font_path), font_size)
    heading = ImageFont.truetype(str(font_path), int(font_size * 1.35))
    caption = ImageFont.truetype(str(font_path), max(18, int(font_size * 0.65)))
    background_path = background if background is not None else settings['background']
    base = Image.new('RGB', (width, height), '#f3f0e9')
    if background_path:
        target = Path(background_path)
        if not target.is_file() or target.stat().st_size > 15 * 1024 * 1024:
            raise ValueError('背景图片不存在或超过15MB')
        with Image.open(target) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError('背景图片最多2000万像素')
            base = ImageOps.fit(ImageOps.exif_transpose(image).convert('RGB'), (width, height))
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(title))[:60].strip(' .') or 'video'
    output = Path(directory) / (safe + '-' + uuid.uuid4().hex[:10])
    output.mkdir(parents=True, exist_ok=False)
    margin = max(36, int(width * 0.065))
    available = width - margin * 2 - 48
    measure = ImageDraw.Draw(base)
    def wrap(text, text_font):
        lines = []
        for paragraph in text.splitlines() or ['']:
            current = ''
            for character in paragraph:
                if current and measure.textlength(current + character, font=text_font) > available:
                    lines.append(current)
                    current = character
                else:
                    current += character
            lines.append(current)
        return lines
    title_lines = wrap(str(title), heading)[:3]
    body_lines = wrap(content, font)
    line_height = int(font_size * 1.6)
    start_y = margin + 85 + len(title_lines) * int(font_size * 1.7)
    per_page = max(1, (height - margin - 100 - start_y) // line_height)
    total = max(1, (len(body_lines) + per_page - 1) // per_page)
    if total > 200:
        raise ValueError('内容过长，最多200张，请分批导出')
    paths = []
    for page in range(total):
        canvas = base.copy().convert('RGBA')
        panel = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        panel_draw = ImageDraw.Draw(panel)
        panel_draw.rounded_rectangle((margin - 24, margin - 24, width - margin + 24, height - margin + 24),
                                     radius=28, fill=(255, 253, 248, int(settings['overlay'] * 255)))
        canvas.alpha_composite(panel)
        draw = ImageDraw.Draw(canvas)
        draw.text((margin, margin), 'BILIBILI_LEARNING_BOT', font=caption, fill='#92683f')
        for index, line in enumerate(title_lines):
            draw.text((margin, margin + 50 + index * int(font_size * 1.7)), line, font=heading, fill='#22282f')
        draw.line((margin, start_y - 20, width - margin, start_y - 20), fill='#d9d0c3', width=2)
        for index, line in enumerate(body_lines[page * per_page:(page + 1) * per_page]):
            draw.text((margin, start_y + index * line_height), line, font=font, fill='#303740')
        draw.text((margin, height - margin - 32), '知识片段 · 由本地导出生成', font=caption, fill='#776f65')
        draw.text((width - margin - 100, height - margin - 32), f'{page + 1:02d} / {total:02d}', font=caption, fill='#776f65')
        target = output / f'{page + 1:03d}.png'
        canvas.convert('RGB').save(target, optimize=True)
        paths.append(str(target))
    return {'path': str(output), 'paths': paths, 'pages': total, 'width': width, 'height': height}
