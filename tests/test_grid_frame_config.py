from xingye_bot.grid_frames import visual_note_frame_options


def test_visual_note_frame_options_use_defaults():
    assert visual_note_frame_options() == {
        "frame_interval": 6,
        "max_frames": 240,
        "grid": (3, 3),
    }


def test_visual_note_frame_options_clamp_invalid_values():
    options = visual_note_frame_options({
        "visual_note_frame_interval": 0,
        "visual_note_max_frames": 9999,
        "visual_note_grid_cols": -2,
        "visual_note_grid_rows": "not-a-number",
    })

    assert options == {
        "frame_interval": 1,
        "max_frames": 360,
        "grid": (1, 3),
    }


def test_visual_note_frame_options_accept_valid_values():
    options = visual_note_frame_options({
        "visual_note_frame_interval": "12",
        "visual_note_max_frames": "120",
        "visual_note_grid_cols": "4",
        "visual_note_grid_rows": "2",
    })

    assert options == {
        "frame_interval": 12,
        "max_frames": 120,
        "grid": (4, 2),
    }
