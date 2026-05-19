"""
Shared fixtures for the Facebook scraper test suite.
"""
import pytest
from src.graph.schema import (
    PostNode, CommentNode, UserNode, GraphSample,
    UserPostEdge, UserUserEdge, UserCommentEdge,
    CommentReplyEdge, HashtagNode, PostHashtagEdge, PostPostEdge,
)


@pytest.fixture
def simple_post():
    return PostNode(
        post_id="post123",
        post_url="https://www.facebook.com/page/posts/post123",
        author_id="user1",
        author_name="Test Author",
        raw_text="Hello #world @friend check https://example.com",
        cleaned_text="Hello #world @friend check https://example.com",
        hashtags=["world"],
        mentions=["friend"],
        like_count=10,
        love_count=5,
        haha_count=2,
        wow_count=1,
        sad_count=0,
        angry_count=0,
        care_count=3,
        comment_count=4,
        share_count=2,
        view_count=100,
    )


@pytest.fixture
def simple_author():
    return UserNode(
        user_id="user1",
        display_name="Test Author",
        username="testauthor",
    )


@pytest.fixture
def top_level_comment():
    return CommentNode(
        comment_id="cmt001",
        post_id="post123",
        author_id="user2",
        author_name="Commenter One",
        parent_id=None,
        depth=0,
        raw_text="Great post! #awesome",
        cleaned_text="Great post! #awesome",
        hashtags=["awesome"],
        mentions=[],
        timestamp="2024-01-01T10:00:00",
    )


@pytest.fixture
def reply_comment():
    return CommentNode(
        comment_id="cmt002",
        post_id="post123",
        author_id="user3",
        author_name="Replier",
        parent_id="cmt001",
        depth=1,
        raw_text="I agree @Commenter",
        cleaned_text="I agree @Commenter",
        hashtags=[],
        mentions=["Commenter"],
        mentioned_users=[{"name": "Commenter One", "href": "https://www.facebook.com/user2"}],
        timestamp="2024-01-01T10:05:00",
    )


@pytest.fixture
def minimal_post():
    return PostNode(
        post_id="minpost",
        post_url="https://www.facebook.com/page/posts/minpost",
    )


@pytest.fixture
def full_graph_sample(simple_post, simple_author, top_level_comment, reply_comment):
    sample = GraphSample(sample_id="sample_test001")
    sample.post = simple_post
    sample.author = simple_author
    sample.comments = [top_level_comment, reply_comment]
    sample.commenters = [
        UserNode(user_id="user2", display_name="Commenter One"),
        UserNode(user_id="user3", display_name="Replier"),
    ]
    sample.hashtags = [HashtagNode(hashtag="world", frequency=1, post_ids=["post123"])]
    sample.edges_user_post = [
        UserPostEdge(user_id="user1", post_id="post123", interaction_type="author"),
        UserPostEdge(user_id="user2", post_id="post123", interaction_type="comment"),
    ]
    sample.edges_user_comment = [
        UserCommentEdge(user_id="user2", comment_id="cmt001", relation_type="author"),
        UserCommentEdge(user_id="user3", comment_id="cmt002", relation_type="author"),
    ]
    sample.edges_user_user = [
        UserUserEdge(source_user_id="user3", target_user_id="user2", relation_type="reply"),
    ]
    sample.edges_comment_reply = [
        CommentReplyEdge(comment_id="cmt001", target_id="post123", target_type="post", direction="reply_to"),
        CommentReplyEdge(comment_id="cmt002", target_id="cmt001", target_type="comment", direction="reply_to"),
    ]
    sample.edges_post_hashtag = [
        PostHashtagEdge(post_id="post123", hashtag="world", direction="has_hashtag"),
        PostHashtagEdge(post_id="post123", hashtag="world", direction="in_post"),
    ]
    return sample
