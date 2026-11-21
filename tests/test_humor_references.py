"""Loader, upvote weighting, and anti-copy checks for the humor reference set."""

from merchandise_discovery.domain.humor_references import (
    HumorReference,
    humor_reference_id,
    is_too_similar_to_references,
    select_humor_references,
)
from merchandise_discovery.domain.models.common import HumorTone
from merchandise_discovery.infrastructure.humor_reference_loader import (
    DEFAULT_HUMOR_REFERENCE_CSV_URL,
    load_fresh_humor_references,
    parse_humor_reference_csv,
)


def _reference(
    text: str,
    upvotes: int,
    humor_type: str,
    niche: str = "",
    *,
    is_theme: bool = False,
) -> HumorReference:
    return HumorReference(
        text=text,
        upvotes=upvotes,
        humor_type=humor_type,
        niche=niche,
        subreddit="example",
        post_url="https://www.reddit.com/r/example",
        date_found="2026-11-21",
        is_theme=is_theme,
        reference_id=humor_reference_id(text),
    )


def test_selection_weights_upvotes_then_boosts_tone_and_niche() -> None:
    """Log-scaled upvotes lead, and a tone or niche match outranks an equal-upvote neighbor."""

    popular = _reference("the fish filed a complaint about my vitals", 100_000, "dry")
    quiet = _reference("i gave report and the lake did not page back", 40, "dry")
    matching = _reference("nobody codes the fish", 40, "dark", niche="night-shift nurses")
    other_niche = _reference("the sourdough judged my handoff", 40, "dark", niche="bakers")
    theme = _reference("gallows shift humor (theme)", 9000, "dark", is_theme=True)

    selection = select_humor_references(
        [quiet, theme, other_niche, popular, matching],
        tone=HumorTone.DARK,
        niches=["night-shift nurse", "fishing"],
    )

    texts = [item.text for item in selection.examples]
    assert theme not in selection.examples
    assert selection.themes == [theme]
    assert texts[0] == popular.text
    assert texts.index(matching.text) < texts.index(other_niche.text)
    assert texts.index(matching.text) < texts.index(quiet.text)
    assert len(selection.display_examples) <= 10


def test_anti_copy_rejects_a_reworded_reference_and_ignores_themes() -> None:
    """A line that reuses the reference wording is dropped; a different joke is kept."""

    copied = _reference("I chart until the sun comes up", 100, "dry")
    theme = _reference("night shift dread (theme)", 100, "dark", is_theme=True)

    assert is_too_similar_to_references("i chart until the sun comes up", [copied, theme])
    assert is_too_similar_to_references(
        "I chart until the sun comes up and then I sigh",
        [copied],
    )
    assert not is_too_similar_to_references("the pager only works underwater", [copied, theme])
    assert not is_too_similar_to_references("night shift dread", [theme])


def test_csv_loader_prefers_the_url_then_the_bundled_file_and_adds_mongo(tmp_path) -> None:
    """A fresh URL wins, a failed fetch uses the repo file, and Mongo only adds new rows."""

    header = "date_found,subreddit,sticker_text_or_idea,upvotes,humor_type,niche,post_url\n"
    remote = header + "2026-11-21,nursing,the lake filed my overtime,4200,dark,nurses,https://reddit.com/a\n"
    bundled = header + "2026-11-20,fishing,bundled fallback joke,10,dry,fishing,https://reddit.com/b\n"
    calls = []

    def http_get(url: str) -> str:
        calls.append(url)
        if url.endswith("/missing.csv"):
            raise OSError("timeout")
        return remote

    class Repository:
        def list_all(self):
            return [
                _reference("the lake filed my overtime", 1, "dry"),
                _reference("mongo only extra", 8, "absurd", niche="nurses"),
            ]

    fetched = load_fresh_humor_references(Repository(), "https://example.com/list.csv", http_get=http_get)
    assert calls == ["https://example.com/list.csv"]
    assert [item.text for item in fetched] == ["the lake filed my overtime", "mongo only extra"]
    assert fetched[0].upvotes == 4200

    fallback = load_fresh_humor_references(
        None,
        "https://example.com/missing.csv",
        http_get=http_get,
        bundled_path=_write_csv(tmp_path, bundled),
    )
    assert [item.text for item in fallback] == ["bundled fallback joke"]

    defaulted = []

    def capture(url: str) -> str:
        defaulted.append(url)
        return header

    load_fresh_humor_references(None, "  ", http_get=capture)
    assert defaulted == [DEFAULT_HUMOR_REFERENCE_CSV_URL]


def test_csv_marks_theme_rows_and_hashes_text() -> None:
    """The theme marker is not a separate column; it lives in the sticker text."""

    body = (
        "date_found,subreddit,sticker_text_or_idea,upvotes,humor_type,niche,post_url\n"
        "2026-11-21,nursing,burnout jokes (theme),99,dark,nurses,https://reddit.com/t\n"
    )
    parsed = parse_humor_reference_csv(body)

    assert parsed[0].is_theme is True
    assert parsed[0].reference_id == humor_reference_id(parsed[0].text)


def _write_csv(directory, body: str):
    path = directory / "humor_references.csv"
    path.write_text(body, encoding="utf-8")
    return path
