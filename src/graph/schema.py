"""
Graph schema definitions for Heterogeneous Graph Embedding.
Aligns with GNN multimodal training requirements.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


# ─── NODE TYPES ─────────────────────────────────────────────────────────────

@dataclass
class UserNode:
    """User/Account node"""
    user_id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    profile_url: Optional[str] = None
    profile_image_url: Optional[str] = None
    bio_text: Optional[str] = None
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    friend_count: Optional[int] = None
    post_count: Optional[int] = None
    is_verified: bool = False
    is_page: bool = False
    is_group: bool = False
    location: Optional[str] = None
    joined_date: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    node_type: str = "user"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class PostNode:
    """Post node - central multimodal entity"""
    post_id: str
    post_url: str
    platform: str = "facebook"
    timestamp: Optional[str] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None

    # Multimodal text
    raw_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    hashtags: List[str] = field(default_factory=list)
    mentions: List[str] = field(default_factory=list)
    emojis: List[str] = field(default_factory=list)
    language: Optional[str] = None

    # Media
    image_urls: List[str] = field(default_factory=list)
    video_urls: List[str] = field(default_factory=list)
    local_image_paths: List[str] = field(default_factory=list)
    local_video_paths: List[str] = field(default_factory=list)
    ocr_results: List[Dict[str, Any]] = field(default_factory=list)  # [{text, confidence, image_idx}]
    object_tags: List[str] = field(default_factory=list)

    # Engagement
    like_count: int = 0
    love_count: int = 0
    haha_count: int = 0
    wow_count: int = 0
    sad_count: int = 0
    angry_count: int = 0
    care_count: int = 0       # "Thương thương" Vietnam FB reaction
    comment_count: int = 0
    share_count: int = 0
    view_count: Optional[int] = None

    # Context
    post_type: str = "post"   # post, reel, story, live
    location: Optional[str] = None
    tagged_users: List[str] = field(default_factory=list)
    external_links: List[str] = field(default_factory=list)
    source_page: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    node_type: str = "post"

    def total_reactions(self) -> int:
        return (self.like_count + self.love_count + self.haha_count +
                self.wow_count + self.sad_count + self.angry_count + self.care_count)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class CommentNode:
    """Comment/Reply node for hierarchical comment tree"""
    comment_id: str
    post_id: str
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    parent_id: Optional[str] = None   # None = top-level, else reply
    depth: int = 0                    # 0=comment, 1=reply, 2=reply-to-reply

    raw_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    hashtags: List[str] = field(default_factory=list)
    mentions: List[str] = field(default_factory=list)
    emojis: List[str] = field(default_factory=list)

    image_urls: List[str] = field(default_factory=list)
    local_image_paths: List[str] = field(default_factory=list)
    ocr_results: List[Dict[str, Any]] = field(default_factory=list)
    mentioned_users: List[Dict[str, str]] = field(default_factory=list)  # [{name, href}]

    like_count: int = 0
    reaction_type: Optional[str] = None   # reaction left on this comment
    reply_count: int = 0
    timestamp: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    node_type: str = "comment"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ─── EDGE TYPES ─────────────────────────────────────────────────────────────

@dataclass
class UserPostEdge:
    """User → Post interaction edge"""
    edge_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    post_id: str = ""
    interaction_type: str = "like"  # like, love, haha, wow, sad, angry, care, comment, share, author
    weight: float = 1.0             # like=1, comment=3, share=5, author=10
    timestamp: Optional[str] = None
    edge_type: str = "user_post"

    WEIGHTS = {
        "author": 10.0,
        "share": 5.0,
        "comment": 3.0,
        "love": 2.0,
        "care": 2.0,
        "wow": 1.5,
        "haha": 1.5,
        "sad": 1.5,
        "angry": 1.5,
        "like": 1.0,
    }

    def __post_init__(self):
        if self.weight == 1.0 and self.interaction_type in self.WEIGHTS:
            self.weight = self.WEIGHTS[self.interaction_type]

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class UserUserEdge:
    """User ↔ User social connection edge"""
    source_user_id: str = ""
    target_user_id: str = ""
    relation_type: str = "follow"   # follow, friend, mention, reply, tag
    is_mutual: bool = False
    timestamp: Optional[str] = None
    edge_type: str = "user_user"

    @property
    def edge_id(self) -> str:
        # Deterministic ID → INSERT OR REPLACE loại bỏ duplicate
        key = f"{self.source_user_id}|{self.target_user_id}|{self.relation_type}"
        return uuid.uuid5(uuid.NAMESPACE_URL, key).hex

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_user_id": self.source_user_id,
            "target_user_id": self.target_user_id,
            "relation_type": self.relation_type,
            "is_mutual": self.is_mutual,
            "timestamp": self.timestamp,
            "edge_type": self.edge_type,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class PostPostEdge:
    """Post ↔ Post content similarity edge"""
    edge_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_post_id: str = ""
    target_post_id: str = ""
    similarity_type: str = "hashtag"  # hashtag, topic, share_chain, reply
    shared_hashtags: List[str] = field(default_factory=list)
    similarity_score: float = 0.0
    edge_type: str = "post_post"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class UserCommentEdge:
    """User → Comment authorship/reaction edge"""
    edge_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    comment_id: str = ""
    relation_type: str = "author"   # author, like, reaction
    reaction_type: Optional[str] = None
    timestamp: Optional[str] = None
    edge_type: str = "user_comment"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ─── GRAPH SAMPLE (final training unit) ─────────────────────────────────────

@dataclass
class GraphSample:
    """Complete graph-structured training sample per post"""
    sample_id: str = field(default_factory=lambda: f"vngraph_{uuid.uuid4().hex[:8]}")

    # Central node
    post: Optional[PostNode] = None

    # Neighbor nodes
    author: Optional[UserNode] = None
    commenters: List[UserNode] = field(default_factory=list)
    comments: List[CommentNode] = field(default_factory=list)

    # Edges
    edges_user_post: List[UserPostEdge] = field(default_factory=list)
    edges_user_user: List[UserUserEdge] = field(default_factory=list)
    edges_post_post: List[PostPostEdge] = field(default_factory=list)
    edges_user_comment: List[UserCommentEdge] = field(default_factory=list)

    # Metadata
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_training_json(self) -> Dict[str, Any]:
        """Export in the format described for GNN training"""
        post = self.post
        if not post:
            return {}

        neighbors = []
        for edge in self.edges_user_post:
            if edge.interaction_type == "author":
                continue
            neighbor = {
                "user_id": edge.user_id,
                "type": edge.interaction_type,
                "timestamp": edge.timestamp,
                "weight": edge.weight,
            }
            # Attach comment content if this is a comment edge
            for c in self.comments:
                if c.author_id == edge.user_id:
                    neighbor["content"] = c.raw_text
                    neighbor["comment_id"] = c.comment_id
                    break
            neighbors.append(neighbor)

        # Build comment tree
        comment_tree = []
        top_comments = [c for c in self.comments if c.parent_id is None]
        for tc in top_comments:
            replies = [c.to_dict() for c in self.comments if c.parent_id == tc.comment_id]
            tc_dict = tc.to_dict()
            tc_dict["replies"] = replies
            comment_tree.append(tc_dict)

        return {
            "sample_id": self.sample_id,
            "post_id": post.post_id,
            "post_url": post.post_url,
            "platform": post.platform,

            "node_features": {
                "text": post.raw_text,
                "cleaned_text": post.cleaned_text,
                "hashtags": post.hashtags,
                "mentions": post.mentions,
                "emojis": post.emojis,
                "language": post.language,
                "image_urls": post.image_urls,
                "video_urls": post.video_urls,
                "local_images": post.local_image_paths,
                "ocr_results": post.ocr_results,
                "object_tags": post.object_tags,
            },

            "engagement": {
                "like": post.like_count,
                "love": post.love_count,
                "haha": post.haha_count,
                "wow": post.wow_count,
                "sad": post.sad_count,
                "angry": post.angry_count,
                "care": post.care_count,
                "comment_count": post.comment_count,
                "share_count": post.share_count,
                "view_count": post.view_count,
                "total_reactions": post.total_reactions(),
            },

            "graph_structure": {
                "author_id": post.author_id,
                "author_name": post.author_name,
                "neighbors": neighbors,
                "comment_tree": comment_tree,
                "edges_user_user": [e.to_dict() for e in self.edges_user_user],
                "edges_post_post": [e.to_dict() for e in self.edges_post_post],
            },

            "metadata": {
                "timestamp": post.timestamp,
                "location": post.location,
                "post_type": post.post_type,
                "source_page": post.source_page,
                "tagged_users": post.tagged_users,
                "external_links": post.external_links,
                "scraped_at": self.scraped_at,
            },
        }
