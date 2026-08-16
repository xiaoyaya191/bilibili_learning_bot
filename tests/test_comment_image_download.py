from brain._brain_interact import BrainInteractMixin


def test_comment_image_urls_include_resized_bilibili_fallback():
    url = "https://i0.hdslb.com/bfs/reply/example.jpg"

    assert BrainInteractMixin._comment_image_urls(url) == [
        url,
        "https://i0.hdslb.com/bfs/reply/example.jpg@1024w_1e_1c",
    ]


def test_comment_image_urls_do_not_duplicate_existing_resize_rule():
    url = "https://i0.hdslb.com/bfs/reply/example.jpg@720w_1e_1c"

    assert BrainInteractMixin._comment_image_urls(url) == [url]
