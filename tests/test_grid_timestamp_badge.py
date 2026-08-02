from PIL import Image, ImageChops

from xingye_bot.grid_frames import _draw_timestamp_badge, _load_font


def test_timestamp_badge_is_drawn_in_the_lower_right_corner():
    image = Image.new("RGB", (320, 180), "white")
    _draw_timestamp_badge(image, 83, _load_font(20))

    lower_right = image.crop((160, 90, 320, 180))
    upper_left = image.crop((0, 0, 80, 60))
    white_lower_right = Image.new("RGB", lower_right.size, "white")
    white_upper_left = Image.new("RGB", upper_left.size, "white")
    assert ImageChops.difference(lower_right, white_lower_right).getbbox() is not None
    assert ImageChops.difference(upper_left, white_upper_left).getbbox() is None
