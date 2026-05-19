"""
Tests for src/utils/helpers.py — all utility functions.
"""
import pytest
import asyncio
from src.utils.helpers import (
    normalize_fb_url,
    extract_post_id,
    extract_user_id,
    extract_hashtags,
    extract_mentions,
    extract_emojis,
    extract_external_links,
    clean_text,
    parse_count,
    parse_reaction_text,
    human_delay,
    micro_delay,
)


# ─── normalize_fb_url ─────────────────────────────────────────────────────────

class TestNormalizeFbUrl:
    def test_removes_tracking_params(self):
        url = "https://www.facebook.com/page/posts/123?__cft__=abc&__tn__=xyz"
        result = normalize_fb_url(url)
        assert "__cft__" not in result
        assert "__tn__" not in result

    def test_keeps_story_fbid(self):
        url = "https://www.facebook.com/page?story_fbid=111&__cft__=x"
        result = normalize_fb_url(url)
        assert "story_fbid=111" in result
        assert "__cft__" not in result

    def test_keeps_id_param(self):
        url = "https://www.facebook.com/profile?id=1234&ref=xxx"
        result = normalize_fb_url(url)
        assert "id=1234" in result
        assert "ref=" not in result

    def test_keeps_fbid(self):
        url = "https://www.facebook.com/photo?fbid=9999&ref=yyy"
        result = normalize_fb_url(url)
        assert "fbid=9999" in result

    def test_empty_url(self):
        assert normalize_fb_url("") == ""

    def test_no_query_params(self):
        url = "https://www.facebook.com/page/posts/123"
        result = normalize_fb_url(url)
        assert result == "https://www.facebook.com/page/posts/123"

    def test_invalid_url_returns_original(self):
        # urlparse doesn't typically throw, but test with unusual input
        url = "not-a-url"
        result = normalize_fb_url(url)
        assert result == "not-a-url"


# ─── extract_post_id ──────────────────────────────────────────────────────────

class TestExtractPostId:
    def test_posts_format(self):
        assert extract_post_id("https://www.facebook.com/page/posts/1234567890") == "1234567890"

    def test_permalink_format(self):
        assert extract_post_id("https://www.facebook.com/page/permalink/9999") == "9999"

    def test_story_fbid_format(self):
        assert extract_post_id("https://www.facebook.com/page?story_fbid=555") == "555"

    def test_p_format(self):
        assert extract_post_id("https://www.facebook.com/p/AbCdEf") == "AbCdEf"

    def test_reel_format(self):
        assert extract_post_id("https://www.facebook.com/reel/1112223334") == "1112223334"

    def test_video_v_param(self):
        assert extract_post_id("https://www.facebook.com/watch?v=123456") == "123456"

    def test_pfbid_format(self):
        result = extract_post_id("https://www.facebook.com/pfbidABCDEF123")
        assert result == "pfbidABCDEF123"

    def test_fbid_param(self):
        assert extract_post_id("https://www.facebook.com/photo?fbid=77777") == "77777"

    def test_photo_path(self):
        assert extract_post_id("https://www.facebook.com/photo/88888") == "88888"

    def test_none_for_empty(self):
        assert extract_post_id("") is None
        assert extract_post_id(None) is None

    def test_none_for_unrecognized(self):
        assert extract_post_id("https://www.facebook.com/") is None


# ─── extract_user_id ──────────────────────────────────────────────────────────

class TestExtractUserId:
    def test_id_param(self):
        assert extract_user_id("https://www.facebook.com/profile?id=12345") == "12345"

    def test_profile_php(self):
        assert extract_user_id("https://www.facebook.com/profile.php?id=99999") == "99999"

    def test_username_path(self):
        assert extract_user_id("https://www.facebook.com/someuser") == "someuser"

    def test_reserved_slug_pages(self):
        assert extract_user_id("https://www.facebook.com/pages/something") is None

    def test_reserved_slug_groups(self):
        assert extract_user_id("https://www.facebook.com/groups/something") is None

    def test_reserved_slug_events(self):
        assert extract_user_id("https://www.facebook.com/events/something") is None

    def test_reserved_slug_marketplace(self):
        assert extract_user_id("https://www.facebook.com/marketplace/something") is None

    def test_reserved_slug_watch(self):
        assert extract_user_id("https://www.facebook.com/watch/something") is None

    def test_empty(self):
        assert extract_user_id("") is None
        assert extract_user_id(None) is None


# ─── extract_hashtags ─────────────────────────────────────────────────────────

class TestExtractHashtags:
    def test_single_hashtag(self):
        assert "python" in extract_hashtags("Hello #python")

    def test_multiple_hashtags(self):
        tags = extract_hashtags("#foo bar #baz")
        assert "foo" in tags
        assert "baz" in tags

    def test_deduplication(self):
        tags = extract_hashtags("#foo #foo #bar")
        assert tags.count("foo") == 1

    def test_empty_text(self):
        assert extract_hashtags("") == []

    def test_none_text(self):
        assert extract_hashtags(None) == []

    def test_no_hashtags(self):
        assert extract_hashtags("no hashtags here") == []


# ─── extract_mentions ─────────────────────────────────────────────────────────

class TestExtractMentions:
    def test_single_mention(self):
        assert "friend" in extract_mentions("Hello @friend!")

    def test_multiple_mentions(self):
        mentions = extract_mentions("@alice and @bob")
        assert "alice" in mentions
        assert "bob" in mentions

    def test_deduplication(self):
        mentions = extract_mentions("@alice @alice @bob")
        assert mentions.count("alice") == 1

    def test_empty_text(self):
        assert extract_mentions("") == []

    def test_none_text(self):
        assert extract_mentions(None) == []


# ─── extract_emojis ───────────────────────────────────────────────────────────

class TestExtractEmojis:
    def test_single_emoji(self):
        result = extract_emojis("Hello 😀")
        assert "😀" in result

    def test_multiple_emojis(self):
        # The regex returns consecutive emojis as one match; check at least one result
        result = extract_emojis("🎉 🎊 🎈")
        assert len(result) >= 2

    def test_no_emojis(self):
        assert extract_emojis("no emojis here") == []

    def test_empty_text(self):
        assert extract_emojis("") == []

    def test_none_text(self):
        assert extract_emojis(None) == []


# ─── extract_external_links ───────────────────────────────────────────────────

class TestExtractExternalLinks:
    def test_http_link(self):
        links = extract_external_links("Visit https://example.com today")
        assert "https://example.com" in links

    def test_www_link(self):
        links = extract_external_links("Check www.example.com")
        assert "www.example.com" in links

    def test_no_links(self):
        assert extract_external_links("no links here") == []

    def test_empty(self):
        assert extract_external_links("") == []

    def test_none(self):
        assert extract_external_links(None) == []

    def test_multiple_links(self):
        links = extract_external_links("See https://a.com and https://b.com")
        assert len(links) == 2


# ─── clean_text ───────────────────────────────────────────────────────────────

class TestCleanText:
    def test_collapses_whitespace(self):
        assert clean_text("hello   world") == "hello world"

    def test_strips_leading_trailing(self):
        assert clean_text("  hello  ") == "hello"

    def test_removes_zero_width(self):
        result = clean_text("hello​world")  # zero-width space
        assert "​" not in result

    def test_unicode_normalization(self):
        # NFC normalization test
        text = "café"  # café NFC
        assert clean_text(text) == "café"

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_none_returns_none(self):
        assert clean_text(None) is None

    def test_newlines_collapsed(self):
        assert clean_text("line1\n\nline2") == "line1 line2"


# ─── parse_count ──────────────────────────────────────────────────────────────

class TestParseCount:
    def test_plain_integer(self):
        assert parse_count("1234") == 1234

    def test_comma_separated(self):
        assert parse_count("1,234") == 1234

    def test_k_suffix(self):
        assert parse_count("1k") == 1000

    def test_K_suffix_uppercase(self):
        assert parse_count("2K") == 2000

    def test_m_suffix(self):
        assert parse_count("1m") == 1_000_000

    def test_M_suffix(self):
        assert parse_count("2M") == 2_000_000

    def test_b_suffix(self):
        assert parse_count("1b") == 1_000_000_000

    def test_empty_string(self):
        assert parse_count("") == 0

    def test_none(self):
        assert parse_count(None) == 0

    def test_dot_separator(self):
        # "1.234" → strip dot → "1234" → 1234
        assert parse_count("1.234") == 1234

    def test_invalid_string(self):
        assert parse_count("abc") == 0


# ─── parse_reaction_text ──────────────────────────────────────────────────────

class TestParseReactionText:
    def test_like_vn(self):
        count, rtype = parse_reaction_text("1,234 Thích")
        assert rtype == "like"
        assert count == 1234

    def test_love_en(self):
        count, rtype = parse_reaction_text("500 Love")
        assert rtype == "love"
        assert count == 500

    def test_haha(self):
        count, rtype = parse_reaction_text("10 Haha")
        assert rtype == "haha"
        assert count == 10

    def test_wow(self):
        count, rtype = parse_reaction_text("5 Wow")
        assert rtype == "wow"

    def test_sad_vn(self):
        count, rtype = parse_reaction_text("3 Buồn")
        assert rtype == "sad"

    def test_angry_en(self):
        count, rtype = parse_reaction_text("7 Angry")
        assert rtype == "angry"

    def test_care_vn(self):
        count, rtype = parse_reaction_text("2 Thương thương")
        assert rtype == "care"

    def test_unknown(self):
        count, rtype = parse_reaction_text("something unknown")
        assert rtype == "unknown"
        assert count == 0

    def test_no_count(self):
        count, rtype = parse_reaction_text("Thích")
        assert rtype == "like"
        assert count == 0


# ─── Async helpers ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_human_delay_runs():
    """human_delay should complete without error (use short values)."""
    await human_delay(0.001, 0.005)


@pytest.mark.asyncio
async def test_micro_delay_runs():
    await micro_delay()


@pytest.mark.asyncio
async def test_human_scroll_runs():
    """human_scroll should call page.evaluate for each step."""
    from src.utils.helpers import human_scroll
    from unittest.mock import AsyncMock, MagicMock
    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock()
    await human_scroll(mock_page, steps=2, pause_min=0.001, pause_max=0.002)
    assert mock_page.evaluate.call_count == 2


class TestExtractUserIdProfilePhp:
    def test_profile_php_id(self):
        # Line 119: profile.php?id= branch
        url = "https://www.facebook.com/profile.php?id=77777"
        assert extract_user_id(url) == "77777"


class TestParseCountEdgeCases:
    def test_value_error_returns_zero(self):
        # Lines 203-204: ValueError branch — "k" with non-numeric prefix
        # strip dots/commas → "xk" → float("x") raises ValueError
        from src.utils.helpers import parse_count
        assert parse_count("xk") == 0

    def test_non_digit_string_returns_zero(self):
        from src.utils.helpers import parse_count
        assert parse_count("hello") == 0
