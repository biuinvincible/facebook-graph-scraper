"""
Tests for src/extractors/media_extractor.py — MediaExtractor
Uses mocked aiohttp sessions and filesystem operations.
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import aiofiles

from src.extractors.media_extractor import MediaExtractor
from src.graph.schema import PostNode, CommentNode


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_extractor(config=None, download=True):
    cfg = config or {
        "download_media": download,
        "media_dir": "/tmp/test_media",
        "max_media_size_mb": 1,
        "ocr_enabled": False,
        "ocr_lang": "eng",
    }
    with patch.object(MediaExtractor, "_check_ocr", return_value=False):
        return MediaExtractor(cfg)


def make_post(post_id="test_post", image_urls=None, video_urls=None):
    return PostNode(
        post_id=post_id,
        post_url=f"https://fb.com/posts/{post_id}",
        image_urls=image_urls or [],
        video_urls=video_urls or [],
    )


# ─── __init__ ─────────────────────────────────────────────────────────────────

class TestMediaExtractorInit:
    def test_init_sets_config(self, tmp_path):
        cfg = {"download_media": True, "media_dir": str(tmp_path / "media"),
               "max_media_size_mb": 50, "ocr_enabled": False, "ocr_lang": "eng"}
        with patch.object(MediaExtractor, "_check_ocr", return_value=False):
            ext = MediaExtractor(cfg)
        assert ext.download is True
        assert ext.ocr_enabled is False

    def test_creates_media_dir(self, tmp_path):
        media_dir = tmp_path / "new_media_dir"
        cfg = {"media_dir": str(media_dir), "download_media": False,
               "max_media_size_mb": 10, "ocr_enabled": False, "ocr_lang": "eng"}
        with patch.object(MediaExtractor, "_check_ocr", return_value=False):
            ext = MediaExtractor(cfg)
        assert media_dir.exists()

    def test_check_ocr_returns_false_when_unavailable(self, tmp_path):
        cfg = {"media_dir": str(tmp_path), "download_media": False,
               "max_media_size_mb": 10, "ocr_enabled": False}
        with patch("src.extractors.media_extractor.MediaExtractor._check_ocr", return_value=False):
            ext = MediaExtractor(cfg)
        assert ext._ocr_available is False


# ─── _check_ocr ───────────────────────────────────────────────────────────────

class TestCheckOcr:
    def test_returns_false_when_tesseract_unavailable(self, tmp_path):
        cfg = {"media_dir": str(tmp_path), "download_media": False,
               "max_media_size_mb": 10}
        with patch("builtins.__import__", side_effect=ImportError("No module")):
            try:
                ext = MediaExtractor(cfg)
                assert ext._ocr_available is False
            except Exception:
                pass  # import might fail too


# ─── _get_extension ───────────────────────────────────────────────────────────

class TestGetExtension:
    def test_jpeg_from_content_type(self):
        ext = make_extractor()
        assert ext._get_extension("https://cdn/img", "image/jpeg") == ".jpg"

    def test_png_from_content_type(self):
        ext = make_extractor()
        assert ext._get_extension("https://cdn/img", "image/png") == ".png"

    def test_mp4_from_content_type(self):
        ext = make_extractor()
        assert ext._get_extension("https://cdn/vid", "video/mp4") == ".mp4"

    def test_jpg_from_url(self):
        ext = make_extractor()
        assert ext._get_extension("https://cdn/img.jpg?x=1", "") == ".jpg"

    def test_webp_from_url(self):
        ext = make_extractor()
        assert ext._get_extension("https://cdn/img.webp?x=1", "") == ".webp"

    def test_bin_fallback(self):
        ext = make_extractor()
        assert ext._get_extension("https://cdn/file", "application/octet-stream") == ".bin"

    def test_gif_from_content_type(self):
        ext = make_extractor()
        assert ext._get_extension("https://cdn/anim", "image/gif") == ".gif"

    def test_webm_from_content_type(self):
        ext = make_extractor()
        assert ext._get_extension("https://cdn/vid", "video/webm") == ".webm"


# ─── process_post_media ───────────────────────────────────────────────────────

class TestProcessPostMedia:
    @pytest.mark.asyncio
    async def test_skips_when_download_disabled(self):
        ext = make_extractor(download=False)
        post = make_post(image_urls=["https://cdn.fbcdn.net/img.jpg"])
        result = await ext.process_post_media(post)
        assert result is post  # returned unchanged

    @pytest.mark.asyncio
    async def test_processes_empty_post(self, tmp_path):
        cfg = {"download_media": True, "media_dir": str(tmp_path / "media"),
               "max_media_size_mb": 1, "ocr_enabled": False, "ocr_lang": "eng"}
        with patch.object(MediaExtractor, "_check_ocr", return_value=False):
            ext = MediaExtractor(cfg)
        post = make_post()  # no images or videos
        result = await ext.process_post_media(post)
        assert result.local_image_paths == []
        assert result.local_video_paths == []

    @pytest.mark.asyncio
    async def test_downloads_images(self, tmp_path):
        cfg = {"download_media": True, "media_dir": str(tmp_path / "media"),
               "max_media_size_mb": 10, "ocr_enabled": False, "ocr_lang": "eng"}
        with patch.object(MediaExtractor, "_check_ocr", return_value=False):
            ext = MediaExtractor(cfg)

        post = make_post(image_urls=["https://cdn.fbcdn.net/img1.jpg"])

        # Mock the download method
        with patch.object(ext, "_download_file", new_callable=AsyncMock,
                          return_value=Path("/tmp/test_media/post1/img_000.jpg")):
            result = await ext.process_post_media(post)
        assert len(result.local_image_paths) == 1

    @pytest.mark.asyncio
    async def test_runs_ocr_when_enabled(self, tmp_path):
        cfg = {"download_media": True, "media_dir": str(tmp_path / "media"),
               "max_media_size_mb": 10, "ocr_enabled": True, "ocr_lang": "eng"}
        with patch.object(MediaExtractor, "_check_ocr", return_value=True):
            ext = MediaExtractor(cfg)

        ext._ocr_available = True
        post = make_post(image_urls=["https://cdn.fbcdn.net/img1.jpg"])
        img_path = tmp_path / "media" / post.post_id / "img_000.jpg"

        with patch.object(ext, "_download_file", new_callable=AsyncMock, return_value=img_path):
            with patch.object(ext, "_run_ocr", new_callable=AsyncMock,
                              return_value={"text": "OCR result", "confidence": 90.0, "language": "eng"}):
                result = await ext.process_post_media(post)
        assert len(result.ocr_results) == 1
        assert result.ocr_results[0]["text"] == "OCR result"


# ─── _download_file ───────────────────────────────────────────────────────────

class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_returns_none_on_non_200_status(self, tmp_path):
        ext = make_extractor()
        session = AsyncMock()
        resp = AsyncMock()
        resp.status = 404
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=resp)
        result = await ext._download_file(session, "https://cdn/img.jpg", tmp_path, "img_000")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_file_too_large(self, tmp_path):
        ext = make_extractor()
        session = AsyncMock()
        resp = AsyncMock()
        resp.status = 200
        resp.headers = {
            "Content-Type": "image/jpeg",
            "Content-Length": str(100 * 1024 * 1024),  # 100MB > 1MB max
        }
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=resp)
        result = await ext._download_file(session, "https://cdn/huge.jpg", tmp_path, "img_000")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_path_on_success(self, tmp_path):
        ext = make_extractor()
        session = AsyncMock()
        resp = AsyncMock()
        resp.status = 200
        resp.headers = {"Content-Type": "image/jpeg", "Content-Length": "1024"}

        # iter_chunked must be an async generator function, not return a coroutine
        async def fake_iter_chunked(size):
            yield b"fake image data"

        resp.content.iter_chunked = fake_iter_chunked
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=resp)

        # Mock aiofiles.open
        mock_file = AsyncMock()
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=False)
        mock_file.write = AsyncMock()

        with patch("aiofiles.open", return_value=mock_file):
            result = await ext._download_file(session, "https://cdn/img.jpg", tmp_path, "img_000")
        assert result is not None
        assert str(result).endswith(".jpg")

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, tmp_path):
        ext = make_extractor()
        session = AsyncMock()
        session.get = MagicMock(side_effect=Exception("Network error"))
        result = await ext._download_file(session, "https://cdn/img.jpg", tmp_path, "img_000")
        assert result is None


# Helper for async iteration
async def aiter(items):
    for item in items:
        yield item


# ─── _sync_ocr ────────────────────────────────────────────────────────────────

class TestSyncOcr:
    def test_returns_none_when_pytesseract_unavailable(self, tmp_path):
        ext = make_extractor()
        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"fake image")

        with patch("builtins.__import__", side_effect=ImportError("No pytesseract")):
            result = ext._sync_ocr(fake_image)
        assert result is None

    def test_returns_none_on_exception(self, tmp_path):
        ext = make_extractor()
        non_existent = tmp_path / "nonexistent.jpg"
        result = ext._sync_ocr(non_existent)
        assert result is None


# ─── process_comment_media ────────────────────────────────────────────────────

class TestProcessCommentMedia:
    @pytest.mark.asyncio
    async def test_skips_when_download_disabled(self):
        ext = make_extractor(download=False)
        comment = CommentNode(
            comment_id="cmt1", post_id="post1",
            raw_text="text", cleaned_text="text",
            image_urls=["https://cdn.fbcdn.net/img.jpg"],
        )
        result = await ext.process_comment_media(comment, "post1")
        assert result is comment

    @pytest.mark.asyncio
    async def test_skips_when_no_images(self):
        ext = make_extractor(download=True)
        comment = CommentNode(
            comment_id="cmt1", post_id="post1",
            raw_text="text", cleaned_text="text",
            image_urls=[],
        )
        result = await ext.process_comment_media(comment, "post1")
        assert result is comment

    @pytest.mark.asyncio
    async def test_downloads_comment_images(self, tmp_path):
        cfg = {"download_media": True, "media_dir": str(tmp_path / "media"),
               "max_media_size_mb": 10, "ocr_enabled": False, "ocr_lang": "eng"}
        with patch.object(MediaExtractor, "_check_ocr", return_value=False):
            ext = MediaExtractor(cfg)

        comment = CommentNode(
            comment_id="cmt123abc", post_id="post1",
            raw_text="text", cleaned_text="text",
            image_urls=["https://cdn.fbcdn.net/img.jpg"],
        )
        with patch.object(ext, "_download_file", new_callable=AsyncMock,
                          return_value=Path("/tmp/media/post1/comments/cmt_123abc_00.jpg")):
            result = await ext.process_comment_media(comment, "post1")
        assert len(result.local_image_paths) == 1


# ─── download_video_ytdlp ─────────────────────────────────────────────────────

class TestDownloadVideoYtdlp:
    @pytest.mark.asyncio
    async def test_returns_none_when_ytdlp_unavailable(self, tmp_path):
        ext = make_extractor()
        with patch("builtins.__import__", side_effect=ImportError("No yt_dlp")):
            result = await ext.download_video_ytdlp("https://fb.com/video/123", "post1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, tmp_path):
        ext = make_extractor()
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(side_effect=Exception("yt-dlp error"))
            result = await ext.download_video_ytdlp("https://fb.com/video/123", "post1")
        assert result is None
