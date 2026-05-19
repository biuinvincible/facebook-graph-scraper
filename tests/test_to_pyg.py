"""
Tests for src/graph/to_pyg.py — json_to_hetero_dict().
Creates minimal JSON dict files and calls the function directly.
"""
import json
import pytest
import numpy as np
from pathlib import Path


def write_json(tmp_path: Path, data: dict, filename: str = "sample.json") -> str:
    path = tmp_path / filename
    path.write_text(json.dumps(data))
    return str(path)


def minimal_sample(post_id="p1") -> dict:
    """Minimal valid training-format JSON."""
    return {
        "post_id": post_id,
        "post_url": f"https://www.facebook.com/p/{post_id}",
        "platform": "facebook",
        "node_features": {
            "text": "Hello world",
            "image_urls": [],
            "local_images": [],
        },
        "engagement": {
            "like": 0, "love": 0, "haha": 0, "wow": 0,
            "sad": 0, "angry": 0, "care": 0,
            "comment_count": 0, "share_count": 0,
            "total_reactions": 0,
        },
        "graph_structure": {
            "author_id": None,
            "comment_tree": [],
            "hashtag_nodes": [],
            "edges_user_post": [],
            "edges_user_comment": [],
            "edges_user_user": [],
            "edges_comment_reply": [],
            "edges_post_hashtag": [],
        },
        "metadata": {},
    }


def full_sample() -> dict:
    """Full sample with all edge types and nested comments."""
    d = minimal_sample("post_full")
    d["graph_structure"].update({
        "author_id": "user1",
        "comment_tree": [
            {
                "comment_id": "cmt1",
                "author_id": "user2",
                "raw_text": "Great post",
                "replies": [
                    {
                        "comment_id": "cmt2",
                        "author_id": "user3",
                        "raw_text": "Agreed",
                        "replies": [],
                    }
                ],
            }
        ],
        "hashtag_nodes": [
            {"hashtag": "python", "frequency": 1, "post_ids": ["post_full"]},
        ],
        "edges_user_post": [
            {"user_id": "user1", "post_id": "post_full", "interaction_type": "author",
             "weight": 10.0, "timestamp": None, "edge_type": "user_post"},
        ],
        "edges_user_comment": [
            {"user_id": "user2", "comment_id": "cmt1", "relation_type": "author",
             "timestamp": None, "edge_type": "user_comment"},
            {"user_id": "user3", "comment_id": "cmt2", "relation_type": "author",
             "timestamp": None, "edge_type": "user_comment"},
        ],
        "edges_user_user": [
            {"source_user_id": "user3", "target_user_id": "user2",
             "relation_type": "reply", "edge_weight": 1.0, "timestamp": None,
             "edge_type": "user_user", "edge_id": "abc"},
            {"source_user_id": "user2", "target_user_id": "user3",
             "relation_type": "reply_rev", "edge_weight": 1.0, "timestamp": None,
             "edge_type": "user_user", "edge_id": "def"},
        ],
        "edges_comment_reply": [
            {"comment_id": "cmt1", "target_id": "post_full",
             "target_type": "post", "direction": "reply_to", "timestamp": None,
             "edge_type": "comment_reply"},
            {"comment_id": "cmt2", "target_id": "cmt1",
             "target_type": "comment", "direction": "reply_to", "timestamp": None,
             "edge_type": "comment_reply"},
            {"comment_id": "cmt1", "target_id": "cmt2",
             "target_type": "comment", "direction": "reply_to_rev", "timestamp": None,
             "edge_type": "comment_reply"},
        ],
        "edges_post_hashtag": [
            {"post_id": "post_full", "hashtag": "python", "direction": "has_hashtag",
             "edge_type": "post_hashtag"},
            {"post_id": "post_full", "hashtag": "python", "direction": "in_post",
             "edge_type": "post_hashtag"},
        ],
    })
    d["engagement"] = {
        "like": 10, "love": 5, "haha": 2, "wow": 1,
        "sad": 0, "angry": 0, "care": 3,
        "comment_count": 2, "share_count": 1, "total_reactions": 21,
    }
    return d


from src.graph.to_pyg import json_to_hetero_dict, to_pyg_heterodata


# ─── Basic structure ──────────────────────────────────────────────────────────

class TestJsonToHeteroDict:
    def test_returns_dict(self, tmp_path):
        path = write_json(tmp_path, minimal_sample())
        result = json_to_hetero_dict(path)
        assert isinstance(result, dict)

    def test_has_required_keys(self, tmp_path):
        path = write_json(tmp_path, minimal_sample())
        result = json_to_hetero_dict(path)
        for key in ("post_id", "num_nodes", "node_ids", "edge_index", "post_engagement",
                    "raw_text", "image_urls", "local_images"):
            assert key in result

    def test_post_id_correct(self, tmp_path):
        path = write_json(tmp_path, minimal_sample("my_post"))
        result = json_to_hetero_dict(path)
        assert result["post_id"] == "my_post"

    def test_post_node_always_exists(self, tmp_path):
        path = write_json(tmp_path, minimal_sample())
        result = json_to_hetero_dict(path)
        assert result["num_nodes"]["post"] == 1
        assert "p1" in result["node_ids"]["post"]

    def test_minimal_no_edges(self, tmp_path):
        path = write_json(tmp_path, minimal_sample())
        result = json_to_hetero_dict(path)
        assert result["edge_index"] == {}

    def test_post_engagement_shape(self, tmp_path):
        path = write_json(tmp_path, minimal_sample())
        result = json_to_hetero_dict(path)
        eng = result["post_engagement"]
        assert isinstance(eng, np.ndarray)
        assert eng.shape == (1, 10)
        assert eng.dtype == np.float32

    def test_post_engagement_values(self, tmp_path):
        d = minimal_sample()
        d["engagement"] = {
            "like": 5, "love": 3, "haha": 1, "wow": 2,
            "sad": 0, "angry": 0, "care": 1,
            "comment_count": 4, "share_count": 2, "total_reactions": 12,
        }
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        eng = result["post_engagement"][0]
        assert eng[0] == 5.0   # like
        assert eng[1] == 3.0   # love
        assert eng[9] == 12.0  # total_reactions

    def test_raw_text(self, tmp_path):
        d = minimal_sample()
        d["node_features"]["text"] = "Test content"
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert result["raw_text"] == "Test content"

    def test_image_urls(self, tmp_path):
        d = minimal_sample()
        d["node_features"]["image_urls"] = ["https://img1.jpg", "https://img2.jpg"]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert result["image_urls"] == ["https://img1.jpg", "https://img2.jpg"]


# ─── Node registration ────────────────────────────────────────────────────────

class TestNodeRegistration:
    def test_author_id_registers_user(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["author_id"] = "user1"
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert "user1" in result["node_ids"]["user"]
        assert result["num_nodes"]["user"] >= 1

    def test_comment_registers_comment_and_user(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["comment_tree"] = [
            {"comment_id": "cmt1", "author_id": "user2", "raw_text": "hi", "replies": []}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert "cmt1" in result["node_ids"]["comment"]
        assert "user2" in result["node_ids"]["user"]

    def test_nested_replies_registered(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["comment_tree"] = [
            {
                "comment_id": "cmt1", "author_id": "user2", "raw_text": "hi",
                "replies": [
                    {"comment_id": "cmt2", "author_id": "user3", "raw_text": "yo", "replies": []}
                ],
            }
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert "cmt1" in result["node_ids"]["comment"]
        assert "cmt2" in result["node_ids"]["comment"]
        assert "user3" in result["node_ids"]["user"]

    def test_hashtag_registered(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["hashtag_nodes"] = [
            {"hashtag": "python", "frequency": 1, "post_ids": []}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert "python" in result["node_ids"]["hashtag"]

    def test_user_user_edge_registers_users(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["edges_user_user"] = [
            {"source_user_id": "ua", "target_user_id": "ub", "relation_type": "reply",
             "edge_weight": 1.0, "timestamp": None, "edge_type": "user_user"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert "ua" in result["node_ids"]["user"]
        assert "ub" in result["node_ids"]["user"]


# ─── Edge index building ──────────────────────────────────────────────────────

class TestEdgeIndexBuilding:
    def test_author_post_edge(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["author_id"] = "user1"
        d["graph_structure"]["edges_user_post"] = [
            {"user_id": "user1", "post_id": "p1", "interaction_type": "author",
             "weight": 10.0, "edge_type": "user_post"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        key = ("user", "author", "post")
        assert key in result["edge_index"]
        arr = result["edge_index"][key]
        assert arr.shape[0] == 2
        assert arr.shape[1] == 1

    def test_non_author_user_post_edge_skipped(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["edges_user_post"] = [
            {"user_id": "user2", "post_id": "p1", "interaction_type": "comment",
             "weight": 3.0, "edge_type": "user_post"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert ("user", "author", "post") not in result["edge_index"]

    def test_user_author_comment_edge(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["comment_tree"] = [
            {"comment_id": "cmt1", "author_id": "user2", "raw_text": "hi", "replies": []}
        ]
        d["graph_structure"]["edges_user_comment"] = [
            {"user_id": "user2", "comment_id": "cmt1", "relation_type": "author",
             "timestamp": None, "edge_type": "user_comment"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        key = ("user", "author", "comment")
        assert key in result["edge_index"]

    def test_user_user_edge(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["edges_user_user"] = [
            {"source_user_id": "ua", "target_user_id": "ub", "relation_type": "reply",
             "edge_weight": 1.0, "edge_type": "user_user"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert ("user", "reply", "user") in result["edge_index"]

    def test_comment_reply_to_post_edge(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["comment_tree"] = [
            {"comment_id": "cmt1", "author_id": "user2", "raw_text": "hi", "replies": []}
        ]
        d["graph_structure"]["edges_comment_reply"] = [
            {"comment_id": "cmt1", "target_id": "p1", "target_type": "post",
             "direction": "reply_to", "timestamp": None, "edge_type": "comment_reply"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert ("comment", "reply_to", "post") in result["edge_index"]

    def test_comment_reply_to_comment_edge(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["comment_tree"] = [
            {
                "comment_id": "cmt1", "author_id": "user2", "raw_text": "hi",
                "replies": [
                    {"comment_id": "cmt2", "author_id": "user3", "raw_text": "yo", "replies": []}
                ],
            }
        ]
        d["graph_structure"]["edges_comment_reply"] = [
            {"comment_id": "cmt2", "target_id": "cmt1", "target_type": "comment",
             "direction": "reply_to", "timestamp": None, "edge_type": "comment_reply"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert ("comment", "reply_to", "comment") in result["edge_index"]

    def test_post_has_hashtag_edge(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["hashtag_nodes"] = [
            {"hashtag": "python", "frequency": 1, "post_ids": []}
        ]
        d["graph_structure"]["edges_post_hashtag"] = [
            {"post_id": "p1", "hashtag": "python", "direction": "has_hashtag",
             "edge_type": "post_hashtag"},
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert ("post", "has_hashtag", "hashtag") in result["edge_index"]

    def test_in_post_hashtag_direction_skipped(self, tmp_path):
        """Only 'has_hashtag' direction creates edges; 'in_post' is ignored."""
        d = minimal_sample()
        d["graph_structure"]["hashtag_nodes"] = [
            {"hashtag": "python", "frequency": 1, "post_ids": []}
        ]
        d["graph_structure"]["edges_post_hashtag"] = [
            {"post_id": "p1", "hashtag": "python", "direction": "in_post",
             "edge_type": "post_hashtag"},
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert ("post", "has_hashtag", "hashtag") not in result["edge_index"]

    def test_edge_index_is_numpy_int64(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["author_id"] = "user1"
        d["graph_structure"]["edges_user_post"] = [
            {"user_id": "user1", "post_id": "p1", "interaction_type": "author",
             "weight": 10.0, "edge_type": "user_post"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        for key, arr in result["edge_index"].items():
            assert arr.dtype == np.int64, f"Expected int64 for {key}, got {arr.dtype}"


# ─── Ghost node guard ─────────────────────────────────────────────────────────

class TestGhostNodeGuard:
    def test_comment_edge_ghost_comment_id_skipped(self, tmp_path):
        """Edge where comment_id was never registered should be skipped."""
        d = minimal_sample()
        # No comment_tree → cmt_ghost never registered
        d["graph_structure"]["edges_comment_reply"] = [
            {"comment_id": "cmt_ghost", "target_id": "p1", "target_type": "post",
             "direction": "reply_to", "timestamp": None, "edge_type": "comment_reply"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        # Should not include this edge since cmt_ghost not in node_ids["comment"]
        assert ("comment", "reply_to", "post") not in result["edge_index"]

    def test_comment_reply_to_comment_ghost_target_skipped(self, tmp_path):
        """Edge where target comment_id was never registered should be skipped."""
        d = minimal_sample()
        d["graph_structure"]["comment_tree"] = [
            {"comment_id": "cmt1", "author_id": "user2", "raw_text": "hi", "replies": []}
        ]
        d["graph_structure"]["edges_comment_reply"] = [
            {"comment_id": "cmt1", "target_id": "cmt_nonexistent", "target_type": "comment",
             "direction": "reply_to", "timestamp": None, "edge_type": "comment_reply"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        # cmt_nonexistent not registered → edge skipped
        assert ("comment", "reply_to", "comment") not in result["edge_index"]

    def test_empty_comment_id_skipped(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["edges_comment_reply"] = [
            {"comment_id": "", "target_id": "p1", "target_type": "post",
             "direction": "reply_to", "timestamp": None, "edge_type": "comment_reply"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert ("comment", "reply_to", "post") not in result["edge_index"]

    def test_empty_user_id_user_user_edge_skipped(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["edges_user_user"] = [
            {"source_user_id": "", "target_user_id": "ub", "relation_type": "reply",
             "edge_weight": 1.0, "edge_type": "user_user"}
        ]
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        assert ("user", "reply", "user") not in result["edge_index"]


# ─── Full integration ─────────────────────────────────────────────────────────

class TestFullSample:
    def test_full_sample_all_edge_types(self, tmp_path):
        d = full_sample()
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)

        # Nodes
        assert result["num_nodes"]["post"] == 1
        assert result["num_nodes"]["user"] >= 3  # user1, user2, user3
        assert result["num_nodes"]["comment"] >= 2
        assert result["num_nodes"]["hashtag"] >= 1

        # Edges present
        ei = result["edge_index"]
        assert ("user", "author", "post") in ei
        assert ("user", "author", "comment") in ei
        assert ("user", "reply", "user") in ei
        assert ("user", "reply_rev", "user") in ei
        assert ("comment", "reply_to", "post") in ei
        assert ("comment", "reply_to", "comment") in ei
        assert ("comment", "reply_to_rev", "comment") in ei
        assert ("post", "has_hashtag", "hashtag") in ei

    def test_full_sample_engagement(self, tmp_path):
        d = full_sample()
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        eng = result["post_engagement"][0]
        assert eng[0] == 10.0  # like
        assert eng[9] == 21.0  # total_reactions

    def test_no_author_in_gs_no_author_node(self, tmp_path):
        d = minimal_sample()
        d["graph_structure"]["author_id"] = None
        path = write_json(tmp_path, d)
        result = json_to_hetero_dict(path)
        # No author_id → no user node registered via author path
        # (still might have 0 users)
        assert result["num_nodes"]["user"] == 0


# ─── to_pyg_heterodata (ImportError branch) ──────────────────────────────────

class TestToPygHeterodata:
    def test_raises_import_error_without_torch(self, tmp_path, monkeypatch):
        """When torch is not installed, to_pyg_heterodata raises ImportError."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("torch", "torch_geometric"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        path = write_json(tmp_path, minimal_sample())
        with pytest.raises(ImportError, match="Install PyG"):
            to_pyg_heterodata(path)

    def test_with_mocked_torch(self, tmp_path, monkeypatch):
        """When torch is available (mocked), to_pyg_heterodata runs without error."""
        from unittest.mock import MagicMock
        import sys
        mock_torch = MagicMock()
        mock_torch.zeros = MagicMock(return_value=MagicMock())
        mock_torch.from_numpy = MagicMock(return_value=MagicMock())

        mock_heterodata_instance = MagicMock()
        mock_heterodata_class = MagicMock(return_value=mock_heterodata_instance)
        mock_pyg_data = MagicMock()
        mock_pyg_data.HeteroData = mock_heterodata_class

        monkeypatch.setitem(sys.modules, "torch", mock_torch)
        monkeypatch.setitem(sys.modules, "torch_geometric", MagicMock())
        monkeypatch.setitem(sys.modules, "torch_geometric.data", mock_pyg_data)

        # Use minimal sample (no edges) to test node-feature loop
        path = write_json(tmp_path, minimal_sample())
        result = to_pyg_heterodata(path)
        assert result is mock_heterodata_instance

    def test_with_mocked_torch_and_edges(self, tmp_path, monkeypatch):
        """With edges present, to_pyg_heterodata also sets edge_index (line 183)."""
        from unittest.mock import MagicMock
        import sys
        mock_torch = MagicMock()
        mock_torch.zeros = MagicMock(return_value=MagicMock())
        mock_torch.from_numpy = MagicMock(return_value=MagicMock())

        mock_heterodata_instance = MagicMock()
        mock_heterodata_class = MagicMock(return_value=mock_heterodata_instance)
        mock_pyg_data = MagicMock()
        mock_pyg_data.HeteroData = mock_heterodata_class

        monkeypatch.setitem(sys.modules, "torch", mock_torch)
        monkeypatch.setitem(sys.modules, "torch_geometric", MagicMock())
        monkeypatch.setitem(sys.modules, "torch_geometric.data", mock_pyg_data)

        # Use full sample which has edges
        path = write_json(tmp_path, full_sample(), "full.json")
        result = to_pyg_heterodata(path)
        assert result is mock_heterodata_instance
        # torch.from_numpy should have been called for edge_index conversion
        assert mock_torch.from_numpy.call_count > 0
