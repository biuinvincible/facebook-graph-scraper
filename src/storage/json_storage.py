"""
JSON file storage — saves each GraphSample as a separate JSON file.
Also handles batch export and JSONL streaming.
"""
import asyncio
from pathlib import Path
from typing import List, Optional
import aiofiles
import orjson
from loguru import logger

from ..graph.schema import GraphSample


class JsonStorage:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def save_sample(self, sample: GraphSample) -> str:
        """Save a GraphSample to JSON file atomically (tmp → rename), return path"""
        post_id = sample.post.post_id if sample.post else sample.sample_id
        filepath = self.output_dir / f"{post_id}.json"
        tmp_path = filepath.with_suffix(".tmp")
        data = sample.to_training_json()

        async with aiofiles.open(tmp_path, "wb") as f:
            await f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS))
        tmp_path.replace(filepath)  # atomic on same filesystem

        return str(filepath)

    async def save_batch_jsonl(self, samples: List[GraphSample], filename: str):
        """Save multiple samples to a JSONL file (one JSON per line)"""
        filepath = self.output_dir / filename
        async with aiofiles.open(filepath, "wb") as f:
            for sample in samples:
                data = sample.to_training_json()
                line = orjson.dumps(data) + b"\n"
                await f.write(line)
        logger.info(f"Saved {len(samples)} samples to {filepath}")
        return str(filepath)

    async def load_sample(self, filepath: str) -> Optional[dict]:
        """Load a saved GraphSample JSON"""
        try:
            async with aiofiles.open(filepath, "rb") as f:
                content = await f.read()
            return orjson.loads(content)
        except Exception as e:
            logger.error(f"Failed to load {filepath}: {e}")
            return None

    def get_all_sample_paths(self) -> List[str]:
        """List all saved sample JSON files"""
        return [str(p) for p in self.output_dir.rglob("*.json")]
