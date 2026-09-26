import pytest

from app.services.youtube import extract_video_id


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=arj7oStGLkU",
        "https://www.youtube.com/watch?v=arj7oStGLkU&t=42s&list=PL123",
        "https://youtu.be/arj7oStGLkU?si=abc",
        "https://m.youtube.com/watch?v=arj7oStGLkU",
        "https://www.youtube.com/embed/arj7oStGLkU",
        "https://www.youtube.com/shorts/arj7oStGLkU",
        "arj7oStGLkU",
    ],
)
def test_extracts_id(url):
    assert extract_video_id(url) == "arj7oStGLkU"


@pytest.mark.parametrize("url", ["", "https://example.com/watch?v=arj7oStGLkU", "https://www.youtube.com/", "not a url"])
def test_rejects_non_youtube(url):
    assert extract_video_id(url) is None
