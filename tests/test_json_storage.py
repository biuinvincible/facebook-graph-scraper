"""
Tests for src/storage/json_storage.py
- save_sample(), load_sample(), get_all_sample_paths()
Uses pytest tmp_path fixture for real file I/O.
"""
import pytest
import asyncio
import json
from pathlib import Path

from src.storage.json_storage import JsonStorage
from src.graph.schema import GraphSample, PostNode


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_sample(post_id="test_post_001") -> GraphSample:
    sample = GraphSample(sample_id="s_test")
    sample.post = PostNode(
        post_id=post_id,
        post_url=f"https://www.facebook.com/page/posts/{post_id}",
        raw_text="Sample post text",
        author_id="user1",
        author_name="Test Author",
    )
    return sample


# ─── __init__ ────────────────────────────────────────────────────────────────

class TestJsonStorageInit:
    def test_creates_output_dir(self, tmp_path):
        out_dir = tmp_path / "new_dir" / "nested"
        storage = JsonStorage(str(out_dir))
        assert out_dir.exists()

    def test_existing_dir_ok(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        assert storage.output_dir == tmp_path


# ─── save_sample ─────────────────────────────────────────────────────────────

class TestSaveSample:
    @pytest.mark.asyncio
    async def test_saves_file(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        sample = make_sample("post_abc")
        path = await storage.save_sample(sample)
        assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_filename_uses_post_id(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        sample = make_sample("post_xyz")
        path = await storage.save_sample(sample)
        assert "post_xyz.json" in path

    @pytest.mark.asyncio
    async def test_saved_content_is_valid_json(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        sample = make_sample("post_json")
        path = await storage.save_sample(sample)
        content = Path(path).read_bytes()
        parsed = json.loads(content)
        assert isinstance(parsed, dict)
        assert parsed["post_id"] == "post_json"

    @pytest.mark.asyncio
    async def test_saves_without_post_uses_sample_id(self, tmp_path):
        """If sample.post is None, fallback to sample_id."""
        storage = JsonStorage(str(tmp_path))
        sample = GraphSample(sample_id="fallback_id")
        # No post → to_training_json returns {} but file should still be created
        path = await storage.save_sample(sample)
        assert "fallback_id.json" in path
        assert Path(path).exists()


# ─── load_sample ─────────────────────────────────────────────────────────────

class TestLoadSample:
    @pytest.mark.asyncio
    async def test_loads_saved_sample(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        sample = make_sample("load_test")
        path = await storage.save_sample(sample)
        loaded = await storage.load_sample(path)
        assert loaded is not None
        assert loaded["post_id"] == "load_test"

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        result = await storage.load_sample(str(tmp_path / "nonexistent.json"))
        assert result is None

    @pytest.mark.asyncio
    async def test_load_invalid_json_returns_none(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_bytes(b"not valid json {{{{")
        storage = JsonStorage(str(tmp_path))
        result = await storage.load_sample(str(bad_file))
        assert result is None

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_data(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        sample = make_sample("roundtrip")
        path = await storage.save_sample(sample)
        loaded = await storage.load_sample(path)
        assert loaded["post_url"] == "https://www.facebook.com/page/posts/roundtrip"


# ─── get_all_sample_paths ─────────────────────────────────────────────────────

class TestGetAllSamplePaths:
    @pytest.mark.asyncio
    async def test_returns_all_json_files(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        await storage.save_sample(make_sample("p1"))
        await storage.save_sample(make_sample("p2"))
        await storage.save_sample(make_sample("p3"))
        paths = storage.get_all_sample_paths()
        assert len(paths) == 3

    def test_empty_dir_returns_empty_list(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        assert storage.get_all_sample_paths() == []

    @pytest.mark.asyncio
    async def test_returns_strings(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        await storage.save_sample(make_sample("str_test"))
        paths = storage.get_all_sample_paths()
        for p in paths:
            assert isinstance(p, str)

    @pytest.mark.asyncio
    async def test_finds_files_in_subdir(self, tmp_path):
        """rglob should find JSON files in subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.json").write_text('{"test": 1}')
        storage = JsonStorage(str(tmp_path))
        paths = storage.get_all_sample_paths()
        assert any("nested.json" in p for p in paths)

    @pytest.mark.asyncio
    async def test_non_json_files_excluded(self, tmp_path):
        (tmp_path / "data.txt").write_text("not json")
        (tmp_path / "data.csv").write_text("a,b,c")
        storage = JsonStorage(str(tmp_path))
        paths = storage.get_all_sample_paths()
        assert all(p.endswith(".json") for p in paths)


# ─── save_batch_jsonl ─────────────────────────────────────────────────────────

class TestSaveBatchJsonl:
    @pytest.mark.asyncio
    async def test_saves_multiple_samples(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        samples = [make_sample(f"p{i}") for i in range(3)]
        path = await storage.save_batch_jsonl(samples, "batch.jsonl")
        assert Path(path).exists()
        lines = Path(path).read_bytes().strip().split(b"\n")
        assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_each_line_is_valid_json(self, tmp_path):
        storage = JsonStorage(str(tmp_path))
        samples = [make_sample(f"q{i}") for i in range(2)]
        path = await storage.save_batch_jsonl(samples, "test.jsonl")
        lines = Path(path).read_bytes().strip().split(b"\n")
        for line in lines:
            parsed = json.loads(line)
            assert isinstance(parsed, dict)
