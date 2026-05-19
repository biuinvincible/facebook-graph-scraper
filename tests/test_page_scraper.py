"""
Tests for PageScraper._build_sample() — pure logic, no browser needed.
We instantiate PageScraper with mocked BrowserContext + config and call _build_sample directly.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from src.graph.schema import (
    PostNode, CommentNode, UserNode, UserCommentEdge,
    UserUserEdge, CommentReplyEdge, HashtagNode, PostHashtagEdge,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_scraper(config=None):
    """Create a PageScraper with mocked context (no real browser)."""
    from src.scrapers.page_scraper import PageScraper
    mock_ctx = MagicMock()
    mock_ctx.new_page = AsyncMock()
    cfg = config or {
        "scraping": {"max_posts_per_target": 10, "scrape_comments": True, "scrape_reactions": True},
        "storage": {},
        "min_delay": 0.0,
        "max_delay": 0.0,
    }
    return PageScraper(mock_ctx, cfg)


def make_post(post_id="p1", raw_text="Hello", author_id="user1", hashtags=None):
    return PostNode(
        post_id=post_id,
        post_url=f"https://www.facebook.com/page/posts/{post_id}",
        author_id=author_id,
        author_name="Author",
        raw_text=raw_text,
        hashtags=hashtags or [],
    )


def make_comment(comment_id, post_id, author_id, author_name="",
                 parent_id=None, depth=0, hashtags=None,
                 mentioned_users=None, timestamp=None):
    return CommentNode(
        comment_id=comment_id,
        post_id=post_id,
        author_id=author_id,
        author_name=author_name,
        parent_id=parent_id,
        depth=depth,
        raw_text="text",
        cleaned_text="text",
        hashtags=hashtags or [],
        mentioned_users=mentioned_users or [],
        timestamp=timestamp,
    )


# ─── Basic structure ─────────────────────────────────────────────────────────

class TestBuildSampleBasic:
    def test_no_author_no_edges(self):
        scraper = make_scraper()
        post = make_post()
        sample = scraper._build_sample(post, None, [], [])
        assert sample.post is post
        assert sample.author is None
        assert sample.edges_user_post == []

    def test_with_author_creates_author_edge(self):
        scraper = make_scraper()
        post = make_post(author_id="user1")
        author = UserNode(user_id="user1", display_name="Author")
        sample = scraper._build_sample(post, author, [], [])
        assert sample.author is author
        assert len(sample.edges_user_post) == 1
        assert sample.edges_user_post[0].interaction_type == "author"
        assert sample.edges_user_post[0].user_id == "user1"
        assert sample.edges_user_post[0].post_id == "p1"

    def test_comment_edges_passed_through(self):
        scraper = make_scraper()
        post = make_post()
        author = UserNode(user_id="user1")
        comment = make_comment("c1", "p1", "user2")
        ce = UserCommentEdge(user_id="user2", comment_id="c1")
        sample = scraper._build_sample(post, author, [comment], [ce])
        assert sample.edges_user_comment == [ce]

    def test_comments_stored(self):
        scraper = make_scraper()
        post = make_post()
        c1 = make_comment("c1", "p1", "user2")
        c2 = make_comment("c2", "p1", "user3")
        sample = scraper._build_sample(post, None, [c1, c2], [])
        assert len(sample.comments) == 2

    def test_commenter_nodes_deduped(self):
        """Same author appearing in two comments should only add one UserNode."""
        scraper = make_scraper()
        post = make_post()
        c1 = make_comment("c1", "p1", "user2", "Bob")
        c2 = make_comment("c2", "p1", "user2", "Bob")
        sample = scraper._build_sample(post, None, [c1, c2], [])
        assert len(sample.commenters) == 1
        assert sample.commenters[0].user_id == "user2"

    def test_comment_without_author_id_skipped_for_commenter_node(self):
        scraper = make_scraper()
        post = make_post()
        c = make_comment("c1", "p1", None)
        sample = scraper._build_sample(post, None, [c], [])
        assert sample.commenters == []


# ─── Reply edges (User→User) ─────────────────────────────────────────────────

class TestBuildSampleReplyEdges:
    def test_reply_creates_user_user_edge(self):
        scraper = make_scraper()
        post = make_post()
        parent = make_comment("c1", "p1", "user2", parent_id=None)
        reply = make_comment("c2", "p1", "user3", parent_id="c1")
        sample = scraper._build_sample(post, None, [parent, reply], [])
        reply_edges = [e for e in sample.edges_user_user if e.relation_type == "reply"]
        assert len(reply_edges) == 1
        assert reply_edges[0].source_user_id == "user3"
        assert reply_edges[0].target_user_id == "user2"

    def test_self_reply_skipped(self):
        """Reply to own comment should not create an edge."""
        scraper = make_scraper()
        post = make_post()
        parent = make_comment("c1", "p1", "user2", parent_id=None)
        reply = make_comment("c2", "p1", "user2", parent_id="c1")  # same author
        sample = scraper._build_sample(post, None, [parent, reply], [])
        reply_edges = [e for e in sample.edges_user_user if e.relation_type == "reply"]
        assert len(reply_edges) == 0

    def test_reply_to_unknown_parent_skipped(self):
        """If parent_id exists but no comment has that ID, no edge created."""
        scraper = make_scraper()
        post = make_post()
        reply = make_comment("c2", "p1", "user3", parent_id="c_unknown")
        sample = scraper._build_sample(post, None, [reply], [])
        reply_edges = [e for e in sample.edges_user_user if e.relation_type == "reply"]
        assert len(reply_edges) == 0

    def test_dedup_uu_edges_no_duplicate_reply(self):
        """Two identical reply combinations should produce only one edge."""
        scraper = make_scraper()
        post = make_post()
        parent = make_comment("c1", "p1", "user2", parent_id=None)
        reply1 = make_comment("c2", "p1", "user3", parent_id="c1")
        reply2 = make_comment("c3", "p1", "user3", parent_id="c1")
        sample = scraper._build_sample(post, None, [parent, reply1, reply2], [])
        reply_edges = [e for e in sample.edges_user_user
                       if e.relation_type == "reply"
                       and e.source_user_id == "user3"
                       and e.target_user_id == "user2"]
        assert len(reply_edges) == 1


# ─── Mention edges ───────────────────────────────────────────────────────────

class TestBuildSampleMentionEdges:
    def test_mention_in_comment(self):
        scraper = make_scraper()
        post = make_post()
        c = make_comment("c1", "p1", "user2", mentioned_users=[
            {"name": "Target User", "href": "https://www.facebook.com/user3"}
        ])
        sample = scraper._build_sample(post, None, [c], [])
        mention_edges = [e for e in sample.edges_user_user if e.relation_type == "mention"]
        assert len(mention_edges) == 1
        assert mention_edges[0].source_user_id == "user2"
        assert mention_edges[0].target_user_id == "user3"

    def test_mention_same_as_author_skipped(self):
        scraper = make_scraper()
        post = make_post(author_id="user2")
        c = make_comment("c1", "p1", "user2", mentioned_users=[
            {"name": "Self", "href": "https://www.facebook.com/user2"}
        ])
        sample = scraper._build_sample(post, None, [c], [])
        mention_edges = [e for e in sample.edges_user_user
                         if e.relation_type == "mention"
                         and e.source_user_id == "user2"
                         and e.target_user_id == "user2"]
        assert len(mention_edges) == 0

    def test_mention_dedup(self):
        """Same mention repeated in two comments → only one edge."""
        scraper = make_scraper()
        post = make_post()
        c1 = make_comment("c1", "p1", "user2", mentioned_users=[
            {"name": "Target", "href": "https://www.facebook.com/user3"}
        ])
        c2 = make_comment("c2", "p1", "user2", mentioned_users=[
            {"name": "Target", "href": "https://www.facebook.com/user3"}
        ])
        sample = scraper._build_sample(post, None, [c1, c2], [])
        mention_edges = [e for e in sample.edges_user_user
                         if e.relation_type == "mention"
                         and e.source_user_id == "user2"
                         and e.target_user_id == "user3"]
        assert len(mention_edges) == 1

    def test_mention_from_post_text(self):
        scraper = make_scraper()
        post = make_post(raw_text="Cảm ơn @friendslug", author_id="user1")
        author = UserNode(user_id="user1")
        sample = scraper._build_sample(post, author, [], [])
        mention_edges = [e for e in sample.edges_user_user if e.relation_type == "mention"]
        assert len(mention_edges) == 1
        assert mention_edges[0].source_user_id == "user1"
        assert mention_edges[0].target_user_id == "friendslug"

    def test_mention_from_post_no_author_id_skipped(self):
        scraper = make_scraper()
        post = make_post(raw_text="@someone here", author_id=None)
        sample = scraper._build_sample(post, None, [], [])
        mention_edges = [e for e in sample.edges_user_user if e.relation_type == "mention"]
        assert len(mention_edges) == 0


# ─── Bidirectional reversed edges ────────────────────────────────────────────

class TestBuildSampleReversedEdges:
    def test_reply_creates_reverse_edge(self):
        scraper = make_scraper()
        post = make_post()
        parent = make_comment("c1", "p1", "user2")
        reply = make_comment("c2", "p1", "user3", parent_id="c1")
        sample = scraper._build_sample(post, None, [parent, reply], [])
        rev_edges = [e for e in sample.edges_user_user if e.relation_type == "reply_rev"]
        assert len(rev_edges) == 1
        assert rev_edges[0].source_user_id == "user2"
        assert rev_edges[0].target_user_id == "user3"

    def test_mention_creates_reverse_edge(self):
        scraper = make_scraper()
        post = make_post()
        c = make_comment("c1", "p1", "user2", mentioned_users=[
            {"name": "X", "href": "https://www.facebook.com/user3"}
        ])
        sample = scraper._build_sample(post, None, [c], [])
        rev_edges = [e for e in sample.edges_user_user if e.relation_type == "mention_rev"]
        assert len(rev_edges) == 1

    def test_no_duplicate_reverse_edges(self):
        """Reverse edge should only be added once even if forward appears twice."""
        scraper = make_scraper()
        post = make_post()
        parent = make_comment("c1", "p1", "user2")
        reply1 = make_comment("c2", "p1", "user3", parent_id="c1")
        sample = scraper._build_sample(post, None, [parent, reply1], [])
        rev_edges = [e for e in sample.edges_user_user
                     if e.relation_type == "reply_rev"
                     and e.source_user_id == "user2"
                     and e.target_user_id == "user3"]
        assert len(rev_edges) == 1


# ─── CommentReplyEdge construction ───────────────────────────────────────────

class TestBuildSampleCommentReplyEdges:
    def test_top_level_comment_reply_to_post(self):
        scraper = make_scraper()
        post = make_post()
        c = make_comment("c1", "p1", "user2", parent_id=None)
        sample = scraper._build_sample(post, None, [c], [])
        post_edges = [e for e in sample.edges_comment_reply
                      if e.target_type == "post" and e.direction == "reply_to"]
        assert len(post_edges) == 1
        assert post_edges[0].comment_id == "c1"
        assert post_edges[0].target_id == "p1"

    def test_reply_creates_reply_to_comment_edge(self):
        scraper = make_scraper()
        post = make_post()
        parent = make_comment("c1", "p1", "user2", parent_id=None)
        reply = make_comment("c2", "p1", "user3", parent_id="c1")
        sample = scraper._build_sample(post, None, [parent, reply], [])
        # reply_to
        fwd = [e for e in sample.edges_comment_reply
               if e.comment_id == "c2" and e.direction == "reply_to"
               and e.target_type == "comment"]
        assert len(fwd) == 1
        assert fwd[0].target_id == "c1"

    def test_reply_creates_reply_to_rev_edge(self):
        scraper = make_scraper()
        post = make_post()
        parent = make_comment("c1", "p1", "user2", parent_id=None)
        reply = make_comment("c2", "p1", "user3", parent_id="c1")
        sample = scraper._build_sample(post, None, [parent, reply], [])
        rev = [e for e in sample.edges_comment_reply
               if e.comment_id == "c1" and e.direction == "reply_to_rev"
               and e.target_id == "c2"]
        assert len(rev) == 1

    def test_top_level_comment_not_reply_to_comment(self):
        scraper = make_scraper()
        post = make_post()
        c = make_comment("c1", "p1", "user2", parent_id=None)
        sample = scraper._build_sample(post, None, [c], [])
        comment_edges = [e for e in sample.edges_comment_reply
                         if e.target_type == "comment"]
        assert len(comment_edges) == 0

    def test_comment_timestamp_propagated(self):
        scraper = make_scraper()
        post = make_post()
        c = make_comment("c1", "p1", "user2", parent_id=None, timestamp="2024-01-01T12:00:00")
        sample = scraper._build_sample(post, None, [c], [])
        for e in sample.edges_comment_reply:
            assert e.timestamp == "2024-01-01T12:00:00"


# ─── Hashtag nodes and edges ─────────────────────────────────────────────────

class TestBuildSampleHashtags:
    def test_post_hashtags_create_nodes(self):
        scraper = make_scraper()
        post = make_post(hashtags=["python", "ml"])
        sample = scraper._build_sample(post, None, [], [])
        tags = {h.hashtag for h in sample.hashtags}
        assert "python" in tags
        assert "ml" in tags

    def test_comment_hashtags_merged(self):
        scraper = make_scraper()
        post = make_post(hashtags=["python"])
        c = make_comment("c1", "p1", "user2", hashtags=["ai"])
        sample = scraper._build_sample(post, None, [c], [])
        tags = {h.hashtag for h in sample.hashtags}
        assert "python" in tags
        assert "ai" in tags

    def test_hashtag_dedup(self):
        scraper = make_scraper()
        post = make_post(hashtags=["python"])
        c = make_comment("c1", "p1", "user2", hashtags=["python"])
        sample = scraper._build_sample(post, None, [c], [])
        assert len([h for h in sample.hashtags if h.hashtag == "python"]) == 1

    def test_duplicate_hashtag_still_one_node(self):
        """Same tag in post + comment → set dedup → one HashtagNode with freq=1.
        Note: line 364 (frequency += 1) is unreachable because all_tags is a set;
        set iteration never yields the same element twice."""
        scraper = make_scraper()
        post = make_post(hashtags=["python"])
        c = make_comment("c1", "p1", "user2", hashtags=["python"])
        sample = scraper._build_sample(post, None, [c], [])
        nodes = [h for h in sample.hashtags if h.hashtag == "python"]
        assert len(nodes) == 1
        assert nodes[0].frequency == 1

    def test_post_hashtag_bidirectional_edges(self):
        scraper = make_scraper()
        post = make_post(hashtags=["python"])
        sample = scraper._build_sample(post, None, [], [])
        has_hashtag = [e for e in sample.edges_post_hashtag if e.direction == "has_hashtag"]
        in_post = [e for e in sample.edges_post_hashtag if e.direction == "in_post"]
        assert len(has_hashtag) == 1
        assert len(in_post) == 1

    def test_no_hashtags_no_nodes(self):
        scraper = make_scraper()
        post = make_post(raw_text="No tags here", hashtags=[])
        sample = scraper._build_sample(post, None, [], [])
        assert sample.hashtags == []
        assert sample.edges_post_hashtag == []
