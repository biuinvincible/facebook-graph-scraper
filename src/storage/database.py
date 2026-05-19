"""
SQLite storage backend for scraped graph data.
Stores nodes and edges in relational tables with JSON for complex fields.
"""
import asyncio
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
import aiosqlite
from loguru import logger

from ..graph.schema import GraphSample, PostNode, UserNode, CommentNode


CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    post_url TEXT,
    platform TEXT DEFAULT 'facebook',
    author_id TEXT,
    author_name TEXT,
    raw_text TEXT,
    cleaned_text TEXT,
    hashtags TEXT,       -- JSON array
    mentions TEXT,       -- JSON array
    emojis TEXT,         -- JSON array
    language TEXT,
    image_urls TEXT,     -- JSON array
    video_urls TEXT,     -- JSON array
    local_image_paths TEXT, -- JSON array
    ocr_results TEXT,    -- JSON array of {text, confidence}
    like_count INTEGER DEFAULT 0,
    love_count INTEGER DEFAULT 0,
    haha_count INTEGER DEFAULT 0,
    wow_count INTEGER DEFAULT 0,
    sad_count INTEGER DEFAULT 0,
    angry_count INTEGER DEFAULT 0,
    care_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    view_count INTEGER,
    post_type TEXT DEFAULT 'post',
    location TEXT,
    tagged_users TEXT,   -- JSON array
    external_links TEXT, -- JSON array
    source_page TEXT,
    timestamp TEXT,
    scraped_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    display_name TEXT,
    profile_url TEXT,
    profile_image_url TEXT,
    bio_text TEXT,
    follower_count INTEGER,
    following_count INTEGER,
    friend_count INTEGER,
    is_verified INTEGER DEFAULT 0,
    is_page INTEGER DEFAULT 0,
    is_group INTEGER DEFAULT 0,
    location TEXT,
    scraped_at TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    post_id TEXT,
    parent_id TEXT,
    depth INTEGER DEFAULT 0,
    author_id TEXT,
    author_name TEXT,
    raw_text TEXT,
    cleaned_text TEXT,
    hashtags TEXT,
    mentions TEXT,
    emojis TEXT,
    image_urls TEXT,
    local_image_paths TEXT,
    ocr_results TEXT,
    like_count INTEGER DEFAULT 0,
    timestamp TEXT,
    scraped_at TEXT,
    FOREIGN KEY (post_id) REFERENCES posts(post_id)
);

CREATE TABLE IF NOT EXISTS edges_user_post (
    edge_id TEXT PRIMARY KEY,
    user_id TEXT,
    post_id TEXT,
    interaction_type TEXT,
    weight REAL DEFAULT 1.0,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS edges_user_user (
    edge_id TEXT PRIMARY KEY,
    source_user_id TEXT,
    target_user_id TEXT,
    relation_type TEXT,
    is_mutual INTEGER DEFAULT 0,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS edges_post_post (
    edge_id TEXT PRIMARY KEY,
    source_post_id TEXT,
    target_post_id TEXT,
    similarity_type TEXT,
    shared_hashtags TEXT,
    similarity_score REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS edges_user_comment (
    edge_id TEXT PRIMARY KEY,
    user_id TEXT,
    comment_id TEXT,
    relation_type TEXT,
    reaction_type TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS graph_samples (
    sample_id TEXT PRIMARY KEY,
    post_id TEXT,
    scraped_at TEXT,
    json_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments(parent_id);
CREATE INDEX IF NOT EXISTS idx_edges_user_post_user ON edges_user_post(user_id);
CREATE INDEX IF NOT EXISTS idx_edges_user_post_post ON edges_user_post(post_id);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def connect(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(CREATE_TABLES)
        await self._db.commit()
        logger.info(f"Connected to database: {self.db_path}")

    async def close(self):
        if self._db:
            await self._db.close()

    def _j(self, data) -> str:
        """JSON serialize"""
        return json.dumps(data, ensure_ascii=False)

    async def save_sample(self, sample: GraphSample, json_path: Optional[str] = None):
        """Save complete GraphSample to all relevant tables"""
        try:
            await self.save_post(sample.post)
            if sample.author:
                await self.save_user(sample.author)
            for user in sample.commenters:
                await self.save_user(user)
            for comment in sample.comments:
                await self.save_comment(comment)
            for edge in sample.edges_user_post:
                await self.save_user_post_edge(edge)
            for edge in sample.edges_user_user:
                await self.save_user_user_edge(edge)
            for edge in sample.edges_post_post:
                await self.save_post_post_edge(edge)
            for edge in sample.edges_user_comment:
                await self.save_user_comment_edge(edge)

            # Record sample index
            await self._db.execute(
                "INSERT OR REPLACE INTO graph_samples VALUES (?, ?, ?, ?)",
                (sample.sample_id, sample.post.post_id if sample.post else None,
                 sample.scraped_at, json_path),
            )
            await self._db.commit()
        except Exception as e:
            logger.error(f"DB save error for sample {sample.sample_id}: {e}")

    async def save_post(self, post: Optional[PostNode]):
        if not post:
            return
        await self._db.execute("""
            INSERT OR REPLACE INTO posts VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )""", (
            post.post_id, post.post_url, post.platform,
            post.author_id, post.author_name,
            post.raw_text, post.cleaned_text,
            self._j(post.hashtags), self._j(post.mentions), self._j(post.emojis),
            post.language,
            self._j(post.image_urls), self._j(post.video_urls),
            self._j(post.local_image_paths), self._j(post.ocr_results),
            post.like_count, post.love_count, post.haha_count,
            post.wow_count, post.sad_count, post.angry_count, post.care_count,
            post.comment_count, post.share_count, post.view_count,
            post.post_type, post.location,
            self._j(post.tagged_users), self._j(post.external_links),
            post.source_page, post.timestamp, post.scraped_at,
        ))
        await self._db.commit()

    async def save_user(self, user: Optional[UserNode]):
        if not user:
            return
        await self._db.execute("""
            INSERT OR REPLACE INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            user.user_id, user.username, user.display_name,
            user.profile_url, user.profile_image_url, user.bio_text,
            user.follower_count, user.following_count, user.friend_count,
            int(user.is_verified), int(user.is_page), int(user.is_group),
            user.location, user.scraped_at,
        ))
        await self._db.commit()

    async def save_comment(self, comment: Optional[CommentNode]):
        if not comment:
            return
        await self._db.execute("""
            INSERT OR REPLACE INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            comment.comment_id, comment.post_id, comment.parent_id, comment.depth,
            comment.author_id, comment.author_name,
            comment.raw_text, comment.cleaned_text,
            self._j(comment.hashtags), self._j(comment.mentions), self._j(comment.emojis),
            self._j(comment.image_urls), self._j(comment.local_image_paths),
            self._j(comment.ocr_results),
            comment.like_count, comment.timestamp, comment.scraped_at,
        ))
        await self._db.commit()

    async def save_user_post_edge(self, edge):
        await self._db.execute(
            "INSERT OR REPLACE INTO edges_user_post VALUES (?,?,?,?,?,?)",
            (edge.edge_id, edge.user_id, edge.post_id,
             edge.interaction_type, edge.weight, edge.timestamp),
        )
        await self._db.commit()

    async def save_user_user_edge(self, edge):
        await self._db.execute(
            "INSERT OR REPLACE INTO edges_user_user VALUES (?,?,?,?,?,?)",
            (edge.edge_id, edge.source_user_id, edge.target_user_id,
             edge.relation_type, int(edge.is_mutual), edge.timestamp),
        )
        await self._db.commit()

    async def save_post_post_edge(self, edge):
        await self._db.execute(
            "INSERT OR REPLACE INTO edges_post_post VALUES (?,?,?,?,?,?)",
            (edge.edge_id, edge.source_post_id, edge.target_post_id,
             edge.similarity_type, self._j(edge.shared_hashtags), edge.similarity_score),
        )
        await self._db.commit()

    async def save_user_comment_edge(self, edge):
        await self._db.execute(
            "INSERT OR REPLACE INTO edges_user_comment VALUES (?,?,?,?,?,?)",
            (edge.edge_id, edge.user_id, edge.comment_id,
             edge.relation_type, edge.reaction_type, edge.timestamp),
        )
        await self._db.commit()

    async def get_stats(self) -> Dict[str, int]:
        stats = {}
        for table in ["posts", "users", "comments", "edges_user_post",
                      "edges_user_user", "edges_user_comment", "edges_post_post"]:
            async with self._db.execute(f"SELECT COUNT(*) FROM {table}") as cur:
                row = await cur.fetchone()
                stats[table] = row[0]
        return stats
