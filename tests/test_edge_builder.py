"""
Tests for src/graph/edge_builder.py — EdgeBuilder
"""
import pytest
from src.graph.edge_builder import EdgeBuilder
from src.graph.schema import PostNode, PostPostEdge


def make_post(post_id, hashtags):
    return PostNode(
        post_id=post_id,
        post_url=f"https://www.facebook.com/page/posts/{post_id}",
        hashtags=hashtags,
    )


class TestBuildPostPostEdges:
    def test_empty_list_returns_empty(self):
        eb = EdgeBuilder()
        edges = eb.build_post_post_edges([])
        assert edges == []

    def test_single_post_no_edges(self):
        eb = EdgeBuilder()
        post = make_post("p1", ["tag1"])
        edges = eb.build_post_post_edges([post])
        assert edges == []

    def test_two_posts_no_shared_hashtags(self):
        eb = EdgeBuilder()
        p1 = make_post("p1", ["tag1", "tag2"])
        p2 = make_post("p2", ["tag3", "tag4"])
        edges = eb.build_post_post_edges([p1, p2])
        assert edges == []

    def test_two_posts_one_shared_hashtag(self):
        eb = EdgeBuilder()
        p1 = make_post("p1", ["tag1", "tag2"])
        p2 = make_post("p2", ["tag2", "tag3"])
        edges = eb.build_post_post_edges([p1, p2])
        assert len(edges) == 1
        edge = edges[0]
        assert isinstance(edge, PostPostEdge)
        assert edge.similarity_type == "hashtag"
        assert "tag2" in edge.shared_hashtags
        assert edge.source_post_id == "p1"
        assert edge.target_post_id == "p2"

    def test_similarity_score_calculation(self):
        eb = EdgeBuilder()
        # 2 shared out of 4 total unique = 0.5
        p1 = make_post("p1", ["tag1", "tag2"])
        p2 = make_post("p2", ["tag2", "tag3"])
        edges = eb.build_post_post_edges([p1, p2])
        assert len(edges) == 1
        # shared={tag2}, union={tag1,tag2,tag3} → 1/3 ≈ 0.3333
        assert abs(edges[0].similarity_score - round(1/3, 4)) < 0.001

    def test_full_overlap_score_is_one(self):
        eb = EdgeBuilder()
        p1 = make_post("p1", ["tag1", "tag2"])
        p2 = make_post("p2", ["tag1", "tag2"])
        edges = eb.build_post_post_edges([p1, p2])
        assert len(edges) == 1
        assert edges[0].similarity_score == 1.0

    def test_three_posts_multiple_edges(self):
        eb = EdgeBuilder()
        p1 = make_post("p1", ["tag1", "tag2"])
        p2 = make_post("p2", ["tag2", "tag3"])
        p3 = make_post("p3", ["tag1", "tag3"])
        edges = eb.build_post_post_edges([p1, p2, p3])
        # p1-p2: share tag2; p1-p3: share tag1; p2-p3: share tag3
        assert len(edges) == 3

    def test_no_duplicate_edges(self):
        eb = EdgeBuilder()
        p1 = make_post("p1", ["tag1"])
        p2 = make_post("p2", ["tag1"])
        edges = eb.build_post_post_edges([p1, p2, p1])  # p1 duplicated
        # pair (p1,p2) should appear only once
        pairs = [(e.source_post_id, e.target_post_id) for e in edges]
        assert len(pairs) == len(set(pairs))

    def test_posts_with_empty_hashtags(self):
        eb = EdgeBuilder()
        p1 = make_post("p1", [])
        p2 = make_post("p2", [])
        edges = eb.build_post_post_edges([p1, p2])
        assert edges == []

    def test_one_empty_one_with_tags(self):
        eb = EdgeBuilder()
        p1 = make_post("p1", [])
        p2 = make_post("p2", ["tag1"])
        edges = eb.build_post_post_edges([p1, p2])
        assert edges == []

    def test_edge_pair_ordering(self):
        eb = EdgeBuilder()
        p1 = make_post("aaa", ["tag1"])
        p2 = make_post("zzz", ["tag1"])
        edges = eb.build_post_post_edges([p1, p2])
        assert len(edges) == 1
        # source should be the earlier-indexed post
        assert edges[0].source_post_id == "aaa"
        assert edges[0].target_post_id == "zzz"

    def test_many_shared_hashtags(self):
        eb = EdgeBuilder()
        tags = [f"tag{i}" for i in range(10)]
        p1 = make_post("p1", tags)
        p2 = make_post("p2", tags)
        edges = eb.build_post_post_edges([p1, p2])
        assert len(edges) == 1
        assert len(edges[0].shared_hashtags) == 10
        assert edges[0].similarity_score == 1.0
