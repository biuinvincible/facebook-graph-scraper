"""
Build Post-Post similarity edges from hashtag/topic overlap.
"""
from typing import List, Dict, Tuple
from ..graph.schema import PostNode, PostPostEdge


class EdgeBuilder:
    def build_post_post_edges(self, posts: List[PostNode]) -> List[PostPostEdge]:
        """
        Compare all pairs of posts and build similarity edges based on:
        - Shared hashtags
        - Same author (post chain)
        """
        edges = []
        seen_pairs = set()

        for i, post_a in enumerate(posts):
            for j, post_b in enumerate(posts):
                if i >= j:
                    continue

                pair_key = tuple(sorted([post_a.post_id, post_b.post_id]))
                if pair_key in seen_pairs:
                    continue

                # Hashtag similarity
                shared_tags = list(
                    set(post_a.hashtags) & set(post_b.hashtags)
                )
                if shared_tags:
                    score = len(shared_tags) / max(
                        len(set(post_a.hashtags) | set(post_b.hashtags)), 1
                    )
                    edge = PostPostEdge(
                        source_post_id=post_a.post_id,
                        target_post_id=post_b.post_id,
                        similarity_type="hashtag",
                        shared_hashtags=shared_tags,
                        similarity_score=round(score, 4),
                    )
                    edges.append(edge)
                    seen_pairs.add(pair_key)

        return edges
