"""
Tests for src/storage/database.py — Database (aiosqlite)
"""
import pytest
import pytest_asyncio
import asyncio
from pathlib import Path

from src.storage.database import Database
from src.graph.schema import (
    PostNode, UserNode, CommentNode, GraphSample,
    UserPostEdge, UserUserEdge, UserCommentEdge, PostPostEdge,
)


# ────────────────────────────────────────────────────────────────────────────
# Helper fixtures
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_post():
    return PostNode(
        post_id="post_db_001",
        post_url="https://www.facebook.com/page/posts/post_db_001",
        author_id="user_db_1",
        author_name="DB Author",
        raw_text="Test post #hello @world",
        cleaned_text="Test post #hello @world",
        hashtags=["hello"],
        mentions=["world"],
        like_count=5,
        love_count=2,
        comment_count=3,
        share_count=1,
    )


@pytest.fixture
def minimal_user():
    return UserNode(
        user_id="user_db_1",
        display_name="DB Author",
        username="dbauthor",
    )


@pytest.fixture
def minimal_comment():
    return CommentNode(
        comment_id="cmt_db_001",
        post_id="post_db_001",
        author_id="user_db_2",
        author_name="Commenter",
        raw_text="Nice post!",
        cleaned_text="Nice post!",
        hashtags=[],
        mentions=[],
        depth=0,
    )


# ────────────────────────────────────────────────────────────────────────────
# Connection / Schema
# ────────────────────────────────────────────────────────────────────────────

class TestDatabaseConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_tables(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        async with Database(db_path) as db:
            # Tables should exist — get_stats won't raise
            stats = await db.get_stats()
            assert "posts" in stats
            assert "users" in stats
            assert "comments" in stats

    @pytest.mark.asyncio
    async def test_in_memory_db(self):
        async with Database(":memory:") as db:
            stats = await db.get_stats()
            assert stats["posts"] == 0

    @pytest.mark.asyncio
    async def test_close_without_connect_is_safe(self, tmp_path):
        db = Database(str(tmp_path / "test.db"))
        # close without connecting should not raise
        await db.close()

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path):
        db_path = str(tmp_path / "nested" / "dir" / "test.db")
        async with Database(db_path) as db:
            stats = await db.get_stats()
            assert stats["posts"] == 0


# ────────────────────────────────────────────────────────────────────────────
# save_post
# ────────────────────────────────────────────────────────────────────────────

class TestSavePost:
    @pytest.mark.asyncio
    async def test_save_post_basic(self, minimal_post):
        async with Database(":memory:") as db:
            await db.save_post(minimal_post)
            stats = await db.get_stats()
            assert stats["posts"] == 1

    @pytest.mark.asyncio
    async def test_save_post_none_is_noop(self):
        async with Database(":memory:") as db:
            await db.save_post(None)
            stats = await db.get_stats()
            assert stats["posts"] == 0

    @pytest.mark.asyncio
    async def test_save_post_or_replace(self, minimal_post):
        async with Database(":memory:") as db:
            await db.save_post(minimal_post)
            minimal_post.raw_text = "Updated text"
            await db.save_post(minimal_post)
            stats = await db.get_stats()
            assert stats["posts"] == 1  # Replace, not duplicate

    @pytest.mark.asyncio
    async def test_save_post_with_lists(self, minimal_post):
        minimal_post.image_urls = ["https://cdn.fbcdn.net/img1.jpg"]
        minimal_post.hashtags = ["foo", "bar"]
        async with Database(":memory:") as db:
            await db.save_post(minimal_post)
            stats = await db.get_stats()
            assert stats["posts"] == 1


# ────────────────────────────────────────────────────────────────────────────
# save_user
# ────────────────────────────────────────────────────────────────────────────

class TestSaveUser:
    @pytest.mark.asyncio
    async def test_save_user_basic(self, minimal_user):
        async with Database(":memory:") as db:
            await db.save_user(minimal_user)
            stats = await db.get_stats()
            assert stats["users"] == 1

    @pytest.mark.asyncio
    async def test_save_user_none_is_noop(self):
        async with Database(":memory:") as db:
            await db.save_user(None)
            stats = await db.get_stats()
            assert stats["users"] == 0


# ────────────────────────────────────────────────────────────────────────────
# save_comment
# ────────────────────────────────────────────────────────────────────────────

class TestSaveComment:
    @pytest.mark.asyncio
    async def test_save_comment_basic(self, minimal_comment, minimal_post):
        async with Database(":memory:") as db:
            await db.save_post(minimal_post)
            await db.save_comment(minimal_comment)
            stats = await db.get_stats()
            assert stats["comments"] == 1

    @pytest.mark.asyncio
    async def test_save_comment_none_is_noop(self):
        async with Database(":memory:") as db:
            await db.save_comment(None)
            stats = await db.get_stats()
            assert stats["comments"] == 0


# ────────────────────────────────────────────────────────────────────────────
# save edges
# ────────────────────────────────────────────────────────────────────────────

class TestSaveEdges:
    @pytest.mark.asyncio
    async def test_save_user_post_edge(self, minimal_post, minimal_user):
        edge = UserPostEdge(
            user_id="user_db_1",
            post_id="post_db_001",
            interaction_type="author",
        )
        async with Database(":memory:") as db:
            await db.save_post(minimal_post)
            await db.save_user(minimal_user)
            await db.save_user_post_edge(edge)
            stats = await db.get_stats()
            assert stats["edges_user_post"] == 1

    @pytest.mark.asyncio
    async def test_save_user_user_edge(self):
        edge = UserUserEdge(
            source_user_id="u1",
            target_user_id="u2",
            relation_type="reply",
        )
        async with Database(":memory:") as db:
            await db.save_user_user_edge(edge)
            stats = await db.get_stats()
            assert stats["edges_user_user"] == 1

    @pytest.mark.asyncio
    async def test_save_post_post_edge(self):
        edge = PostPostEdge(
            source_post_id="p1",
            target_post_id="p2",
            similarity_type="hashtag",
            shared_hashtags=["tag1"],
            similarity_score=0.5,
        )
        async with Database(":memory:") as db:
            await db.save_post_post_edge(edge)
            stats = await db.get_stats()
            assert stats["edges_post_post"] == 1

    @pytest.mark.asyncio
    async def test_save_user_comment_edge(self):
        edge = UserCommentEdge(
            user_id="u1",
            comment_id="c1",
            relation_type="author",
        )
        async with Database(":memory:") as db:
            await db.save_user_comment_edge(edge)
            stats = await db.get_stats()
            assert stats["edges_user_comment"] == 1


# ────────────────────────────────────────────────────────────────────────────
# save_sample (full GraphSample)
# ────────────────────────────────────────────────────────────────────────────

class TestSaveSample:
    @pytest.mark.asyncio
    async def test_save_full_graph_sample(self, full_graph_sample):
        async with Database(":memory:") as db:
            await db.save_sample(full_graph_sample)
            stats = await db.get_stats()
            assert stats["posts"] == 1
            assert stats["users"] >= 2  # author + commenters
            assert stats["comments"] == 2
            assert stats["edges_user_post"] >= 1
            assert stats["edges_user_comment"] >= 1

    @pytest.mark.asyncio
    async def test_save_sample_with_json_path(self, full_graph_sample):
        async with Database(":memory:") as db:
            await db.save_sample(full_graph_sample, json_path="/data/json/sample.json")
            stats = await db.get_stats()
            assert stats["posts"] == 1

    @pytest.mark.asyncio
    async def test_save_sample_idempotent(self, full_graph_sample):
        async with Database(":memory:") as db:
            await db.save_sample(full_graph_sample)
            await db.save_sample(full_graph_sample)
            stats = await db.get_stats()
            assert stats["posts"] == 1  # OR REPLACE deduplicates

    @pytest.mark.asyncio
    async def test_save_sample_no_post(self):
        sample = GraphSample(sample_id="empty_sample")
        async with Database(":memory:") as db:
            await db.save_sample(sample)
            stats = await db.get_stats()
            assert stats["posts"] == 0

    @pytest.mark.asyncio
    async def test_save_sample_no_author(self):
        post = PostNode(
            post_id="p_noauthor",
            post_url="https://fb.com/page/posts/p_noauthor",
        )
        sample = GraphSample(sample_id="sample_noauthor")
        sample.post = post
        async with Database(":memory:") as db:
            await db.save_sample(sample)
            stats = await db.get_stats()
            assert stats["posts"] == 1
            assert stats["users"] == 0


# ────────────────────────────────────────────────────────────────────────────
# get_stats
# ────────────────────────────────────────────────────────────────────────────

class TestGetStats:
    @pytest.mark.asyncio
    async def test_get_stats_all_tables(self):
        async with Database(":memory:") as db:
            stats = await db.get_stats()
            expected_tables = [
                "posts", "users", "comments",
                "edges_user_post", "edges_user_user",
                "edges_user_comment", "edges_post_post",
            ]
            for table in expected_tables:
                assert table in stats
                assert stats[table] == 0

    @pytest.mark.asyncio
    async def test_get_stats_counts_correctly(self, minimal_post, minimal_user):
        async with Database(":memory:") as db:
            await db.save_post(minimal_post)
            await db.save_user(minimal_user)
            stats = await db.get_stats()
            assert stats["posts"] == 1
            assert stats["users"] == 1
