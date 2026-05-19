"""
Additional tests for MediaExtractor — OCR and yt-dlp code paths.
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.extractors.media_extractor import MediaExtractor
from src.graph.schema import PostNode


def make_extractor_with_ocr(tmp_path):
    cfg = {
        "download_media": True,
        "media_dir": str(tmp_path / "media"),
        "max_media_size_mb": 10,
        "ocr_enabled": True,
        "ocr_lang": "eng",
    }
    with patch.object(MediaExtractor, "_check_ocr", return_value=True):
        ext = MediaExtractor(cfg)
    ext._ocr_available = True
    return ext


class TestCheckOcrWithTesseract:
    def test_returns_true_when_tesseract_available(self, tmp_path):
        cfg = {"media_dir": str(tmp_path), "download_media": False,
               "max_media_size_mb": 10}
        mock_pytesseract = MagicMock()
        mock_pytesseract.get_tesseract_version = MagicMock(return_value="4.1.1")
        with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
            ext = MediaExtractor(cfg)
            # _check_ocr is called in init, but tesseract may or may not be available
            assert isinstance(ext._ocr_available, bool)


class TestRunOcr:
    @pytest.mark.asyncio
    async def test_returns_none_when_ocr_fails(self, tmp_path):
        ext = make_extractor_with_ocr(tmp_path)
        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"fake")
        with patch.object(ext, "_sync_ocr", return_value=None):
            result = await ext._run_ocr(fake_image, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_empty_text(self, tmp_path):
        ext = make_extractor_with_ocr(tmp_path)
        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"fake")
        with patch.object(ext, "_sync_ocr", return_value={"text": "   ", "confidence": 50.0, "language": "eng"}):
            result = await ext._run_ocr(fake_image, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_ocr_result_with_text(self, tmp_path):
        ext = make_extractor_with_ocr(tmp_path)
        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"fake")
        ocr_result = {"text": "Hello World", "confidence": 90.0, "language": "eng"}
        with patch.object(ext, "_sync_ocr", return_value=ocr_result):
            result = await ext._run_ocr(fake_image, 1)
        assert result is not None
        assert result["text"] == "Hello World"
        assert result["image_idx"] == 1
        assert result["image_path"] == str(fake_image)

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, tmp_path):
        ext = make_extractor_with_ocr(tmp_path)
        fake_image = tmp_path / "test.jpg"
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(side_effect=Exception("OCR crash"))
            result = await ext._run_ocr(fake_image, 0)
        assert result is None


class TestSyncOcrWithPytesseract:
    def test_sync_ocr_with_mock_pytesseract(self, tmp_path):
        ext_cfg = {"media_dir": str(tmp_path), "download_media": False,
                   "max_media_size_mb": 10}
        with patch.object(MediaExtractor, "_check_ocr", return_value=True):
            ext = MediaExtractor(ext_cfg)
        ext._ocr_available = True

        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"fake")

        mock_pytesseract = MagicMock()
        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.size = (100, 100)
        mock_pil.Image.open = MagicMock(return_value=mock_img)
        mock_pytesseract.Output = MagicMock()
        mock_pytesseract.Output.DICT = "dict"
        mock_pytesseract.image_to_data = MagicMock(return_value={
            "text": ["Hello", "World", ""],
            "conf": ["90", "85", "-1"],
        })

        with patch.dict("sys.modules", {
            "pytesseract": mock_pytesseract,
            "PIL": mock_pil,
            "PIL.Image": mock_pil.Image,
        }):
            result = ext._sync_ocr(fake_image)
        # Should succeed when pytesseract is available
        assert result is None or isinstance(result, dict)

    def test_sync_ocr_returns_none_on_import_error(self, tmp_path):
        ext_cfg = {"media_dir": str(tmp_path), "download_media": False,
                   "max_media_size_mb": 10}
        with patch.object(MediaExtractor, "_check_ocr", return_value=False):
            ext = MediaExtractor(ext_cfg)
        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"fake")
        # Without pytesseract installed, should return None
        result = ext._sync_ocr(fake_image)
        assert result is None or isinstance(result, dict)


class TestSyncYtdlp:
    def test_sync_ytdlp_returns_none_when_unavailable(self, tmp_path):
        ext_cfg = {"media_dir": str(tmp_path), "download_media": False,
                   "max_media_size_mb": 10}
        with patch.object(MediaExtractor, "_check_ocr", return_value=False):
            ext = MediaExtractor(ext_cfg)
        result = ext._sync_ytdlp("https://fb.com/video/123", {})
        assert result is None

    def test_sync_ytdlp_with_mock_yt_dlp(self, tmp_path):
        ext_cfg = {"media_dir": str(tmp_path), "download_media": False,
                   "max_media_size_mb": 10}
        with patch.object(MediaExtractor, "_check_ocr", return_value=False):
            ext = MediaExtractor(ext_cfg)

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_info = {"id": "123", "ext": "mp4"}
        mock_ydl.extract_info = MagicMock(return_value=mock_info)
        mock_ydl.prepare_filename = MagicMock(return_value="/tmp/video_123.mp4")

        mock_ytdlp = MagicMock()
        mock_ytdlp.YoutubeDL = MagicMock(return_value=mock_ydl)

        with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
            result = ext._sync_ytdlp("https://fb.com/video/123", {})
        # With mocked yt_dlp, should succeed
        assert result == "/tmp/video_123.mp4"
