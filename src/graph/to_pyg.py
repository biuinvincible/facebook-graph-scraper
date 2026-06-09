"""
Convert JSON graph samples → PyTorch Geometric HeteroData format.

Output structure (per sample):
    data['post'].x         = placeholder (1, feature_dim) — replaced by embeddings later
    data['user'].x         = placeholder (N_users, feature_dim)
    data['comment'].x      = placeholder (N_comments, feature_dim)
    data['hashtag'].x      = placeholder (N_hashtags, feature_dim)

    data['user', 'author', 'post'].edge_index       = (2, E)
    data['user', 'author', 'comment'].edge_index    = (2, E)
    data['user', 'reply', 'user'].edge_index        = (2, E)
    data['user', 'reply_rev', 'user'].edge_index    = (2, E)
    data['user', 'mention', 'user'].edge_index      = (2, E)
    data['user', 'mention_rev', 'user'].edge_index  = (2, E)
    data['comment', 'reply_to', 'post'].edge_index  = (2, E)
    data['comment', 'reply_to', 'comment'].edge_index = (2, E)
    data['comment', 'reply_to_rev', 'comment'].edge_index = (2, E)
    data['post', 'has_hashtag', 'hashtag'].edge_index = (2, E)
"""
import json
import numpy as np
from pathlib import Path
from typing import Dict, Any, Tuple
from collections import defaultdict


def json_to_hetero_dict(json_path: str) -> Dict[str, Any]:
    """
    Load 1 JSON file → dict chứa node mappings và edge_index arrays.
    Không cần PyG installed — output tương thích HeteroData.
    """
    with open(json_path) as f:
        d = json.load(f)

    gs = d["graph_structure"]
    post_id = d["post_id"]
    eng = d.get("engagement", {})

    # ── Node ID mappings (string → int index) ────────────────────────────────
    node_ids: Dict[str, Dict[str, int]] = {
        "post": {post_id: 0},
        "user": {},
        "comment": {},
        "hashtag": {},
        "image": {},
    }

    def get_id(ntype: str, nid: str) -> int:
        if nid not in node_ids[ntype]:
            node_ids[ntype][nid] = len(node_ids[ntype])
        return node_ids[ntype][nid]

    # Register all nodes from edges
    get_id("post", post_id)

    # Users từ author edge
    if gs.get("author_id"):
        get_id("user", gs["author_id"])

    # Users + Comments từ comment tree
    def register_comments(cmts):
        for c in cmts:
            get_id("comment", c["comment_id"])
            if c.get("author_id"):
                get_id("user", c["author_id"])
            register_comments(c.get("replies", []))
    register_comments(gs.get("comment_tree", []))

    # Hashtags
    for h in gs.get("hashtag_nodes", []):
        get_id("hashtag", h["hashtag"])

    # Image nodes
    for img in gs.get("image_nodes", []):
        get_id("image", img["image_id"])

    # Users từ user_user edges
    for e in gs.get("edges_user_user", []):
        get_id("user", e["source_user_id"])
        get_id("user", e["target_user_id"])

    # ── Edge index builders ───────────────────────────────────────────────────
    edges: Dict[Tuple, list] = defaultdict(list)  # (src_type, rel, dst_type) → [(src,dst)]

    # User →[author]→ Post
    for e in gs.get("edges_user_post", []):
        if e["interaction_type"] == "author" and e.get("user_id"):
            edges[("user", "author", "post")].append(
                (get_id("user", e["user_id"]), get_id("post", post_id))
            )

    # User →[author]→ Comment
    for e in gs.get("edges_user_comment", []):
        if e.get("user_id") and e.get("comment_id"):
            edges[("user", "author", "comment")].append(
                (get_id("user", e["user_id"]), get_id("comment", e["comment_id"]))
            )

    # User → User (reply, reply_rev, mention, mention_rev)
    for e in gs.get("edges_user_user", []):
        rel = e["relation_type"]
        src = e["source_user_id"]
        tgt = e["target_user_id"]
        if src and tgt:
            edges[("user", rel, "user")].append(
                (get_id("user", src), get_id("user", tgt))
            )

    # Comment →[reply_to]→ Post / Comment
    for e in gs.get("edges_comment_reply", []):
        cid = e["comment_id"]
        tid = e["target_id"]
        ttype = e["target_type"]
        direction = e["direction"]
        if not cid or not tid:
            continue
        if ttype == "post":
            if cid in node_ids["comment"] and tid in node_ids["post"]:
                edges[("comment", direction, "post")].append(
                    (get_id("comment", cid), get_id("post", tid))
                )
        else:
            if cid in node_ids["comment"] and tid in node_ids["comment"]:
                edges[("comment", direction, "comment")].append(
                    (get_id("comment", cid), get_id("comment", tid))
                )

    # Post →[has_hashtag]→ Hashtag
    for e in gs.get("edges_post_hashtag", []):
        if e["direction"] == "has_hashtag":
            edges[("post", "has_hashtag", "hashtag")].append(
                (get_id("post", e["post_id"]), get_id("hashtag", e["hashtag"]))
            )

    # Post/Comment ↔ Image edges
    for e in gs.get("edges_content_image", []):
        iid = e["image_id"]
        sid = e["source_id"]
        stype = e["source_type"]
        direction = e["direction"]
        if iid not in node_ids["image"]: continue
        if direction == "contains":
            src_type = stype   # "post" | "comment"
            dst_type = "image"
            src_id = get_id(src_type, sid)
            dst_id = get_id("image", iid)
        else:  # contained_by
            src_type = "image"
            dst_type = stype
            src_id = get_id("image", iid)
            dst_id = get_id(stype, sid)
        edges[(src_type, direction, dst_type)].append((src_id, dst_id))

    # ── Convert to numpy edge_index arrays ───────────────────────────────────
    edge_index_dict = {}
    for (src_type, rel, dst_type), pairs in edges.items():
        if pairs:
            arr = np.array(pairs, dtype=np.int64).T  # shape (2, E)
            edge_index_dict[(src_type, rel, dst_type)] = arr

    # ── Node counts & placeholder features ───────────────────────────────────
    num_nodes = {ntype: len(ids) for ntype, ids in node_ids.items()}

    # Engagement features cho Post node (sẽ được concat vào text embedding sau)
    post_engagement = np.array([[
        eng.get("like", 0), eng.get("love", 0), eng.get("haha", 0),
        eng.get("wow", 0),  eng.get("sad", 0),  eng.get("angry", 0),
        eng.get("care", 0), eng.get("comment_count", 0), eng.get("share_count", 0),
        eng.get("total_reactions", 0),
    ]], dtype=np.float32)

    return {
        "post_id": post_id,
        "num_nodes": num_nodes,          # {'post':1, 'user':N, 'comment':M, 'hashtag':H}
        "node_ids": node_ids,            # string→int mappings
        "edge_index": edge_index_dict,   # (src,rel,dst) → np.array shape (2,E)
        "post_engagement": post_engagement,  # (1, 10) — to be concat with text embed
        "raw_text": d.get("node_features", {}).get("text", ""),
        "image_urls": d.get("node_features", {}).get("image_urls", []),
        "local_images": d.get("node_features", {}).get("local_images", []),
        "image_nodes": gs.get("image_nodes", []),  # [{image_id, local_path, source_type, source_id}]
    }


def to_pyg_heterodata(json_path: str):
    """
    Convert JSON → PyTorch Geometric HeteroData.
    Requires: pip install torch torch_geometric
    """
    try:
        import torch
        from torch_geometric.data import HeteroData
    except ImportError:
        raise ImportError("Install PyG: pip install torch torch-geometric")

    data_dict = json_to_hetero_dict(json_path)
    data = HeteroData()

    # Placeholder node features (sẽ thay bằng embeddings thực sau)
    FEAT_DIM = 1
    for ntype, count in data_dict["num_nodes"].items():
        data[ntype].x = torch.zeros(count, FEAT_DIM)
        data[ntype].node_id = list(data_dict["node_ids"][ntype].keys())

    # Edge indices
    for (src, rel, dst), edge_index in data_dict["edge_index"].items():
        data[src, rel, dst].edge_index = torch.from_numpy(edge_index)

    # Post engagement as extra feature
    data["post"].engagement = torch.from_numpy(data_dict["post_engagement"])

    return data


if __name__ == "__main__":
    import glob, sys

    files = sorted(glob.glob("data/raw/*.json"))
    if not files:
        print("No JSON files found")
        sys.exit(1)

    f = files[-1]
    print(f"Converting: {f}")
    result = json_to_hetero_dict(f)

    print(f"\n=== HeteroData Summary ===")
    print(f"Nodes:")
    for ntype, count in result["num_nodes"].items():
        print(f"  {ntype}: {count}")

    print(f"\nEdge types (edge_index shape):")
    for (src, rel, dst), ei in result["edge_index"].items():
        print(f"  ({src}, {rel}, {dst}): {ei.shape} — {ei.shape[1]} edges")

    print(f"\nPost engagement features: {result['post_engagement']}")
    print(f"Text preview: {repr(result['raw_text'][:80])}")
    print(f"Images: {len(result['image_urls'])}")
