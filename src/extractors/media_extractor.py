"""
Media downloader and OCR extractor.
Downloads images/videos and runs OCR for text-in-image extraction.
"""
import asyncio
import hashlib
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import aiohttp
import aiofiles
from loguru import logger

from ..graph.schema import PostNode


class MediaExtractor:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.media_dir = Path(config.get("media_dir", "data/media"))
        self.max_size = config.get("max_media_size_mb", 50) * 1024 * 1024
        self.download = config.get("download_media", True)
        self.ocr_enabled = config.get("ocr_enabled", True)
        self.ocr_lang = config.get("ocr_lang", "vie+eng")
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # Check OCR availability
        self._ocr_available = self._check_ocr()

    def _check_ocr(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            logger.warning("Tesseract not available — OCR disabled")
            return False

    async def process_post_media(self, post: PostNode) -> PostNode:
        """Download all images/videos and run OCR"""
        if not self.download:
            return post

        post_dir = self.media_dir / post.post_id
        post_dir.mkdir(parents=True, exist_ok=True)

        local_images = []
        ocr_results = []

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
        ) as session:
            for idx, url in enumerate(post.image_urls):
                local_path = await self._download_file(session, url, post_dir, f"img_{idx:03d}")
                if local_path:
                    local_images.append(str(local_path))
                    if self._ocr_available and self.ocr_enabled:
                        ocr = await self._run_ocr(local_path, idx)
                        if ocr:
                            ocr_results.append(ocr)

            # Download videos (first frame via yt-dlp if available)
            local_videos = []
            for idx, url in enumerate(post.video_urls):
                local_path = await self._download_file(session, url, post_dir, f"vid_{idx:03d}")
                if local_path:
                    local_videos.append(str(local_path))

        post.local_image_paths = local_images
        post.local_video_paths = local_videos
        post.ocr_results = ocr_results
        return post

    async def _download_file(
        self, session: aiohttp.ClientSession, url: str,
        dest_dir: Path, prefix: str
    ) -> Optional[Path]:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None

                content_type = resp.headers.get("Content-Type", "")
                ext = self._get_extension(url, content_type)
                filename = f"{prefix}{ext}"
                filepath = dest_dir / filename

                # Check size
                content_length = int(resp.headers.get("Content-Length", 0))
                if content_length > self.max_size:
                    logger.debug(f"Skipping large file: {url} ({content_length/1e6:.1f}MB)")
                    return None

                async with aiofiles.open(filepath, "wb") as f:
                    downloaded = 0
                    async for chunk in resp.content.iter_chunked(8192):
                        downloaded += len(chunk)
                        if downloaded > self.max_size:
                            break
                        await f.write(chunk)

                return filepath
        except Exception as e:
            logger.debug(f"Download failed for {url}: {e}")
            return None

    async def _run_ocr(self, image_path: Path, image_idx: int) -> Optional[Dict[str, Any]]:
        """Run Tesseract OCR on image, return extracted text"""
        try:
            import pytesseract
            from PIL import Image

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._sync_ocr, image_path)
            if result and result["text"].strip():
                result["image_idx"] = image_idx
                result["image_path"] = str(image_path)
                return result
        except Exception as e:
            logger.debug(f"OCR failed for {image_path}: {e}")
        return None

    def _sync_ocr(self, image_path: Path) -> Optional[Dict[str, Any]]:
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            # Resize if too large
            if max(img.size) > 4000:
                img.thumbnail((4000, 4000))

            data = pytesseract.image_to_data(
                img,
                lang=self.ocr_lang,
                output_type=pytesseract.Output.DICT,
            )
            # Filter confident detections
            confident_words = [
                data["text"][i]
                for i in range(len(data["text"]))
                if int(data["conf"][i]) > 60 and data["text"][i].strip()
            ]
            text = " ".join(confident_words)
            avg_conf = sum(
                int(c) for c in data["conf"] if int(c) > 0
            ) / max(1, sum(1 for c in data["conf"] if int(c) > 0))

            return {"text": text, "confidence": round(avg_conf, 1), "language": self.ocr_lang}
        except Exception as e:
            logger.debug(f"Sync OCR error: {e}")
            return None

    def _get_extension(self, url: str, content_type: str) -> str:
        CT_MAP = {
            "image/jpeg": ".jpg", "image/png": ".png",
            "image/gif": ".gif", "image/webp": ".webp",
            "video/mp4": ".mp4", "video/webm": ".webm",
        }
        for ct, ext in CT_MAP.items():
            if ct in content_type:
                return ext
        # Try from URL
        for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm"]:
            if ext in url.lower():
                return ext
        return ".bin"

    async def process_comment_media(self, comment, post_id: str):
        """Download ảnh trong comment về local disk"""
        if not self.download or not comment.image_urls:
            return comment

        comment_dir = self.media_dir / post_id / "comments"
        comment_dir.mkdir(parents=True, exist_ok=True)

        local_paths = []
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
        ) as session:
            for idx, url in enumerate(comment.image_urls):
                prefix = f"cmt_{comment.comment_id[:8]}_{idx:02d}"
                local_path = await self._download_file(session, url, comment_dir, prefix)
                if local_path:
                    local_paths.append(str(local_path))

        comment.local_image_paths = local_paths
        return comment

    async def download_video_ytdlp(self, url: str, post_id: str) -> Optional[str]:
        """Download video using yt-dlp for higher quality"""
        try:
            import yt_dlp
            post_dir = self.media_dir / post_id
            post_dir.mkdir(parents=True, exist_ok=True)
            output_template = str(post_dir / "video_%(id)s.%(ext)s")

            ydl_opts = {
                "outtmpl": output_template,
                "format": "best[height<=720]",
                "quiet": True,
                "no_warnings": True,
            }
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._sync_ytdlp, url, ydl_opts)
            return result
        except Exception as e:
            logger.debug(f"yt-dlp download failed: {e}")
            return None

    def _sync_ytdlp(self, url: str, opts: dict) -> Optional[str]:
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                return filename
        except Exception:
            return None
