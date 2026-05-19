"""
Tests for src/graph/schema.py — data classes, to_dict(), to_training_json().
"""
import uuid
import pytest
from src.graph.schema import (
    UserNode, PostNode, CommentNode,
    UserPostEdge, UserUserEdge, CommentReplyEdge,
    HashtagNode, PostHashtagEdge, PostPostEdge, UserCommentEdge,
    GraphSample,
)


# ─── UserNode ────────────────────────────────────────────────────────────────

class TestUserNode:
    def test_defaults(self):
        u = UserNode(user_id="u1")
        assert u.user_id == "u1"
        assert u.node_type == "user"
        assert u.is_verified is False
        assert u.is_page is False
        assert u.is_group is False

    def test_to_dict_excludes_none(self):
        u = UserNode(user_id="u1", username=None, display_name="Test")
        d = u.to_dict()
        assert "username" not in d
        assert d["display_name"] == "Test"

    def test_to_dict_includes_all_non_none(self):
        u = UserNode(user_id="u1", username="slug", follower_count=100)
        d = u.to_dict()
        assert d["username"] == "slug"
        assert d["follower_count"] == 100

    def test_scraped_at_set(self):
        u = UserNode(user_id="u1")
        assert u.scraped_at  # non-empty string


# ─── PostNode ────────────────────────────────────────────────────────────────

class TestPostNode:
    def test_defaults(self):
        p = PostNode(post_id="p1", post_url="https://fb.com/p/1")
        assert p.platform == "facebook"
        assert p.post_type == "post"
        assert p.like_count == 0
        assert p.node_type == "post"

    def test_total_reactions(self, simple_post):
        # like=10, love=5, haha=2, wow=1, sad=0, angry=0, care=3 → 21
        assert simple_post.total_reactions() == 21

    def test_total_reactions_zeros(self):
        p = PostNode(post_id="p1", post_url="https://fb.com/p/1")
        assert p.total_reactions() == 0

    def test_to_dict_includes_all_fields(self):
        p = PostNode(post_id="p1", post_url="https://fb.com/p/1")
        d = p.to_dict()
        assert "post_id" in d
        assert "like_count" in d
        assert "node_type" in d

    def test_to_dict_includes_none_values(self):
        p = PostNode(post_id="p1", post_url="https://fb.com/p/1", timestamp=None)
        d = p.to_dict()
        # PostNode.to_dict returns ALL fields (including None)
        assert "timestamp" in d

    def test_hashtags_list_default(self):
        p = PostNode(post_id="p1", post_url="https://fb.com/p/1")
        assert p.hashtags == []

    def test_scraped_at_set(self):
        p = PostNode(post_id="p1", post_url="https://fb.com/p/1")
        assert p.scraped_at


# ─── CommentNode ─────────────────────────────────────────────────────────────

class TestCommentNode:
    def test_defaults(self):
        c = CommentNode(comment_id="c1", post_id="p1")
        assert c.depth == 0
        assert c.parent_id is None
        assert c.node_type == "comment"
        assert c.like_count == 0

    def test_to_dict_includes_all(self):
        c = CommentNode(comment_id="c1", post_id="p1", raw_text="hi")
        d = c.to_dict()
        assert d["comment_id"] == "c1"
        assert d["raw_text"] == "hi"

    def test_mentioned_users_default(self):
        c = CommentNode(comment_id="c1", post_id="p1")
        assert c.mentioned_users == []


# ─── UserPostEdge ─────────────────────────────────────────────────────────────

class TestUserPostEdge:
    def test_weight_auto_set(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="author")
        assert e.weight == 10.0

    def test_weight_comment(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="comment")
        assert e.weight == 3.0

    def test_weight_share(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="share")
        assert e.weight == 5.0

    def test_weight_like(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="like")
        assert e.weight == 1.0

    def test_weight_love(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="love")
        assert e.weight == 2.0

    def test_weight_care(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="care")
        assert e.weight == 2.0

    def test_weight_wow(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="wow")
        assert e.weight == 1.5

    def test_weight_haha(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="haha")
        assert e.weight == 1.5

    def test_weight_sad(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="sad")
        assert e.weight == 1.5

    def test_weight_angry(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="angry")
        assert e.weight == 1.5

    def test_explicit_weight_not_overridden(self):
        # When weight != 1.0 already, __post_init__ still reassigns from WEIGHTS
        # because condition is weight == 1.0
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="author", weight=99.0)
        # weight==99.0 != 1.0, so __post_init__ condition is False → stays 99.0
        assert e.weight == 99.0

    def test_to_dict(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="like")
        d = e.to_dict()
        assert d["user_id"] == "u1"
        assert d["edge_type"] == "user_post"

    def test_edge_id_is_uuid(self):
        e = UserPostEdge(user_id="u1", post_id="p1", interaction_type="like")
        assert len(e.edge_id) > 0


# ─── UserUserEdge ─────────────────────────────────────────────────────────────

class TestUserUserEdge:
    def test_edge_id_deterministic(self):
        e1 = UserUserEdge(source_user_id="u1", target_user_id="u2", relation_type="reply")
        e2 = UserUserEdge(source_user_id="u1", target_user_id="u2", relation_type="reply")
        assert e1.edge_id == e2.edge_id

    def test_edge_id_different_for_different_inputs(self):
        e1 = UserUserEdge(source_user_id="u1", target_user_id="u2", relation_type="reply")
        e2 = UserUserEdge(source_user_id="u2", target_user_id="u1", relation_type="reply")
        assert e1.edge_id != e2.edge_id

    def test_edge_id_is_uuid5_hex(self):
        e = UserUserEdge(source_user_id="u1", target_user_id="u2", relation_type="follow")
        key = "u1|u2|follow"
        expected = uuid.uuid5(uuid.NAMESPACE_URL, key).hex
        assert e.edge_id == expected

    def test_to_dict_includes_edge_weight_and_edge_id(self):
        e = UserUserEdge(source_user_id="u1", target_user_id="u2", relation_type="reply")
        d = e.to_dict()
        assert "edge_id" in d
        assert "edge_weight" in d
        assert d["edge_weight"] == 1.0
        assert d["source_user_id"] == "u1"
        assert d["relation_type"] == "reply"
        assert d["edge_type"] == "user_user"

    def test_to_dict_includes_timestamp(self):
        e = UserUserEdge(source_user_id="u1", target_user_id="u2", relation_type="mention",
                         timestamp="2024-01-01")
        d = e.to_dict()
        assert d["timestamp"] == "2024-01-01"

    def test_defaults(self):
        e = UserUserEdge()
        assert e.relation_type == "follow"
        assert e.is_mutual is False
        assert e.edge_weight == 1.0
        assert e.edge_type == "user_user"


# ─── CommentReplyEdge ─────────────────────────────────────────────────────────

class TestCommentReplyEdge:
    def test_defaults(self):
        e = CommentReplyEdge()
        assert e.target_type == "post"
        assert e.direction == "reply_to"
        assert e.edge_type == "comment_reply"

    def test_to_dict(self):
        e = CommentReplyEdge(comment_id="c1", target_id="p1", target_type="post")
        d = e.to_dict()
        assert d["comment_id"] == "c1"
        assert d["target_type"] == "post"


# ─── HashtagNode ──────────────────────────────────────────────────────────────

class TestHashtagNode:
    def test_defaults(self):
        h = HashtagNode(hashtag="python")
        assert h.frequency == 0
        assert h.post_ids == []
        assert h.node_type == "hashtag"

    def test_to_dict(self):
        h = HashtagNode(hashtag="python", frequency=5, post_ids=["p1", "p2"])
        d = h.to_dict()
        assert d["hashtag"] == "python"
        assert d["frequency"] == 5
        assert d["post_ids"] == ["p1", "p2"]


# ─── PostHashtagEdge ──────────────────────────────────────────────────────────

class TestPostHashtagEdge:
    def test_defaults(self):
        e = PostHashtagEdge()
        assert e.direction == "has_hashtag"
        assert e.edge_type == "post_hashtag"

    def test_to_dict(self):
        e = PostHashtagEdge(post_id="p1", hashtag="python", direction="in_post")
        d = e.to_dict()
        assert d["post_id"] == "p1"
        assert d["hashtag"] == "python"
        assert d["direction"] == "in_post"


# ─── PostPostEdge ─────────────────────────────────────────────────────────────

class TestPostPostEdge:
    def test_defaults(self):
        e = PostPostEdge()
        assert e.similarity_type == "hashtag"
        assert e.similarity_score == 0.0
        assert e.edge_type == "post_post"

    def test_to_dict(self):
        e = PostPostEdge(source_post_id="p1", target_post_id="p2", similarity_score=0.75)
        d = e.to_dict()
        assert d["source_post_id"] == "p1"
        assert d["similarity_score"] == 0.75


# ─── UserCommentEdge ──────────────────────────────────────────────────────────

class TestUserCommentEdge:
    def test_defaults(self):
        e = UserCommentEdge()
        assert e.relation_type == "author"
        assert e.edge_type == "user_comment"
        assert e.reaction_type is None

    def test_to_dict(self):
        e = UserCommentEdge(user_id="u1", comment_id="c1")
        d = e.to_dict()
        assert d["user_id"] == "u1"
        assert d["comment_id"] == "c1"


# ─── GraphSample ─────────────────────────────────────────────────────────────

class TestGraphSample:
    def test_empty_to_training_json(self):
        s = GraphSample()
        result = s.to_training_json()
        assert result == {}

    def test_to_training_json_minimal(self, minimal_post):
        s = GraphSample(sample_id="s1")
        s.post = minimal_post
        result = s.to_training_json()
        assert result["post_id"] == "minpost"
        assert result["platform"] == "facebook"
        assert result["engagement"]["total_reactions"] == 0
        assert result["graph_structure"]["comment_tree"] == []
        assert result["graph_structure"]["neighbors"] == []

    def test_to_training_json_full(self, full_graph_sample):
        result = full_graph_sample.to_training_json()
        assert result["sample_id"] == "sample_test001"
        assert result["post_id"] == "post123"
        assert result["post_url"] == "https://www.facebook.com/page/posts/post123"

        # Node features
        assert result["node_features"]["text"] == "Hello #world @friend check https://example.com"
        assert "world" in result["node_features"]["hashtags"]

        # Engagement
        eng = result["engagement"]
        assert eng["like"] == 10
        assert eng["love"] == 5
        assert eng["care"] == 3
        assert eng["total_reactions"] == 21
        assert eng["view_count"] == 100

        # Graph structure
        gs = result["graph_structure"]
        # author edge is filtered from neighbors
        neighbors = gs["neighbors"]
        # Only non-author interaction edges become neighbors
        assert len(neighbors) == 1
        assert neighbors[0]["type"] == "comment"
        assert neighbors[0]["user_id"] == "user2"
        # Comment content attached to neighbor
        assert neighbors[0]["comment_id"] == "cmt001"

        # Comment tree: top-level + reply
        ct = gs["comment_tree"]
        assert len(ct) == 1
        top = ct[0]
        assert top["comment_id"] == "cmt001"
        assert len(top["replies"]) == 1
        assert top["replies"][0]["comment_id"] == "cmt002"

        # Hashtag nodes
        assert len(gs["hashtag_nodes"]) == 1
        assert gs["hashtag_nodes"][0]["hashtag"] == "world"

        # Edges
        assert len(gs["edges_user_post"]) == 2
        assert len(gs["edges_user_comment"]) == 2
        assert len(gs["edges_user_user"]) == 1
        assert len(gs["edges_comment_reply"]) == 2
        assert len(gs["edges_post_hashtag"]) == 2

    def test_to_training_json_no_comments_no_hashtags(self, simple_post, simple_author):
        s = GraphSample(sample_id="s_empty")
        s.post = simple_post
        s.author = simple_author
        result = s.to_training_json()
        gs = result["graph_structure"]
        assert gs["comment_tree"] == []
        assert gs["hashtag_nodes"] == []
        assert gs["neighbors"] == []

    def test_to_training_json_comment_without_matching_author(self, simple_post):
        """Neighbor entry should NOT have content if comment author_id doesn't match edge user_id."""
        s = GraphSample(sample_id="s2")
        s.post = simple_post
        # Edge with user_id "user99" but no comment has that author_id
        from src.graph.schema import UserPostEdge
        s.edges_user_post = [UserPostEdge(user_id="user99", post_id="post123", interaction_type="comment")]
        result = s.to_training_json()
        neighbors = result["graph_structure"]["neighbors"]
        assert len(neighbors) == 1
        assert "content" not in neighbors[0]

    def test_to_training_json_metadata(self, simple_post):
        simple_post.location = "Hanoi"
        simple_post.post_type = "reel"
        simple_post.source_page = "testpage"
        s = GraphSample(sample_id="s_meta")
        s.post = simple_post
        result = s.to_training_json()
        meta = result["metadata"]
        assert meta["location"] == "Hanoi"
        assert meta["post_type"] == "reel"
        assert meta["source_page"] == "testpage"

    def test_sample_id_prefix(self):
        s = GraphSample()
        assert s.sample_id.startswith("vngraph_")

    def test_scraped_at_set(self):
        s = GraphSample()
        assert s.scraped_at

    def test_to_training_json_deep_replies(self, simple_post):
        """build_subtree should recurse into depth-2 replies."""
        s = GraphSample(sample_id="s_deep")
        s.post = simple_post
        c1 = CommentNode(comment_id="c1", post_id="post123", parent_id=None)
        c2 = CommentNode(comment_id="c2", post_id="post123", parent_id="c1")
        c3 = CommentNode(comment_id="c3", post_id="post123", parent_id="c2")
        s.comments = [c1, c2, c3]
        result = s.to_training_json()
        ct = result["graph_structure"]["comment_tree"]
        assert len(ct) == 1
        assert len(ct[0]["replies"]) == 1
        assert len(ct[0]["replies"][0]["replies"]) == 1
        assert ct[0]["replies"][0]["replies"][0]["comment_id"] == "c3"
