"""Loader, upvote weighting, and anti-copy checks for the humor reference set."""

from merchandise_discovery.domain.humor import niche_pair_block
from merchandise_discovery.domain.humor_references import (
    HumorReference,
    HumorReferenceLoadError,
    copied_from_source,
    extract_market_signal,
    humor_reference_id,
    identity_pick_bucket,
    is_too_similar_to_references,
    market_signal_prompt,
    select_humor_references,
)
from merchandise_discovery.domain.models.common import HumorTone
from merchandise_discovery.infrastructure.humor_reference_loader import (
    DEFAULT_HUMOR_REFERENCE_CSV_URL,
    find_humor_reference_csv,
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


def test_bundled_humor_csv_matches_the_synced_file_shape() -> None:
    """The file may be the short list or the sales list. Every row has text and a demand number."""

    from merchandise_discovery.infrastructure.humor_reference_loader import (
        bundled_humor_reference_csv,
    )

    body = bundled_humor_reference_csv().read_text(encoding="utf-8")
    header = body.splitlines()[0].casefold()
    parsed = parse_humor_reference_csv(body)

    assert "sticker_text_or_idea" in header or "text" in header
    assert "upvotes" in header or "sales" in header
    assert parsed
    assert all(item.text.strip() for item in parsed)
    assert all(item.upvotes > 0 or item.demand > 0 for item in parsed)
    themes = [item for item in parsed if item.is_theme]
    assert all("(theme)" in item.text.casefold() for item in themes)
    selection = select_humor_references(parsed, tone=HumorTone.DRY, niches=["mechanics"])
    assert all(not item.is_theme for item in selection.examples)


def test_selling_rows_are_market_signal_and_not_joke_examples() -> None:
    """New columns are kept. The prompt names the trend and does not quote the product line."""

    body = (
        "sticker_text_or_idea,sales,identity,theme,hook,marketplace,notes\n"
        "Do not show me your rash,1200,nurses,shift life,badge reel,etsy,ignore me\n"
        "AI slop (theme),40,office workers,ai slop,,redbubble,\n"
    )
    parsed = parse_humor_reference_csv(body)

    assert parsed[0].niche == "nurses"
    assert parsed[0].demand == 1200
    assert parsed[0].hook == "badge reel"
    assert parsed[0].theme == "shift life"
    assert parsed[0].upvotes == 0
    assert parsed[1].is_theme is True
    signal = extract_market_signal(parsed)
    prompt = market_signal_prompt(signal)
    assert "nurses" in signal.identities
    assert "badge reel" in signal.hooks
    assert any("slop" in theme for theme in signal.themes)
    assert "Do not show me your rash" not in prompt
    assert "Buyer signal" in prompt
    assert is_too_similar_to_references("Do not show me your rash", parsed)
    assert signal.token_weights["nurses"] > signal.token_weights.get("office", 0)
    assert "Trending buyers" in prompt


def test_sales_weight_buyers_ahead_of_themes_and_the_pick_can_explore() -> None:
    """A bigger seller boosts its buyer more. A share of 0 never follows that trend."""

    import random

    hunters = HumorReference(
        text="Do not copy this hunter decal pack",
        niche="hunters",
        sales=100,
        demand=100,
        reference_id="h",
    )
    nurses = HumorReference(
        text="Nurse badge reel 50 pack",
        niche="nurses",
        sales=25,
        demand=25,
        reference_id="n",
    )
    theme = HumorReference(
        text="AI slop (theme)",
        niche="general",
        upvotes=90_000,
        demand=90_000,
        is_theme=True,
        reference_id="t",
    )
    signal = extract_market_signal([hunters, nurses, theme])
    prompt = market_signal_prompt(signal)

    assert signal.identities[0] == "hunters"
    assert "general" not in signal.identities
    assert signal.token_weights["hunters"] > signal.token_weights["nurses"]
    assert signal.token_weights["hunters"] > signal.token_weights.get("slop", 1)
    assert "hunter decal" not in prompt
    assert identity_pick_bucket(0, random.Random(1), has_buyers=True) == "exploratory"
    assert identity_pick_bucket(1, random.Random(1), has_buyers=True) == "trending"
    assert identity_pick_bucket(0.6, random.Random(1), has_buyers=False) == "exploratory"
    chooser = random.Random(0)
    picks = [identity_pick_bucket(0.6, chooser, has_buyers=True) for _ in range(200)]
    assert 90 <= picks.count("trending") <= 150



def test_csv_marks_theme_rows_and_hashes_text() -> None:
    """The theme marker is not a separate column; it lives in the sticker text."""

    body = (
        "date_found,subreddit,sticker_text_or_idea,upvotes,humor_type,niche,post_url\n"
        "2026-11-21,nursing,burnout jokes (theme),99,dark,nurses,https://reddit.com/t\n"
    )
    parsed = parse_humor_reference_csv(body)

    assert parsed[0].is_theme is True
    assert parsed[0].reference_id == humor_reference_id(parsed[0].text)


def test_source_sentences_are_not_treated_as_jokes() -> None:
    """A merchandise line that is the source sentence, or mostly its words, is rejected."""

    quote = "I also noticed I was getting elephants foot and adhesion issues in places."
    nozzle = "This is with a 0.4 mm nozzle."
    corners = "One corner can give you info about the other corners too."

    assert copied_from_source(quote, quote, "something else")
    assert copied_from_source(nozzle, nozzle)
    assert copied_from_source(corners, corners)
    assert copied_from_source(
        "I was getting elephants foot and adhesion issues",
        quote,
    )
    assert not copied_from_source(
        "My first layer files a complaint",
        quote,
        nozzle,
    )
    assert not copied_from_source("", quote)


def test_blank_niches_ask_for_one_real_person() -> None:
    """A run with no Niche A/B stacks co-occurring traits instead of two scenarios."""

    blank = niche_pair_block()
    assert "one real person" in blank
    assert "pairing_score" in blank
    named = niche_pair_block(identity="night-shift nurses")
    assert "night-shift nurses" in named
    assert "stack modifier" in named
    supplied = niche_pair_block("nurses", "3D printing")
    assert 'both "nurses" and "3D printing"' in supplied


def test_empty_fetch_uses_the_file_above_the_working_directory(tmp_path) -> None:
    """A zero-row download falls back by walking up from the process directory."""

    repo = tmp_path / "repo"
    nested = repo / "src" / "merchandise_discovery" / "entrypoints"
    nested.mkdir(parents=True)
    header = "date_found,subreddit,sticker_text_or_idea,upvotes,humor_type,niche,post_url\n"
    row = "2026-11-21,nursing,the lake filed my overtime,10,dry,nurses,https://reddit.com/a\n"
    (repo / "data").mkdir()
    (repo / "data" / "humor_references.csv").write_text(header + row, encoding="utf-8")

    found = find_humor_reference_csv([nested])
    assert found == repo / "data" / "humor_references.csv"

    loaded = load_fresh_humor_references(
        None,
        "https://example.com/empty.csv",
        http_get=lambda _url: header,
        bundled_path=found,
    )
    assert [item.text for item in loaded] == ["the lake filed my overtime"]


def test_zero_rows_fail_instead_of_returning_an_empty_list(tmp_path) -> None:
    """A fetch and a missing file must stop the run with a clear error."""

    header = "date_found,subreddit,sticker_text_or_idea,upvotes,humor_type,niche,post_url\n"
    missing = tmp_path / "missing.csv"
    try:
        load_fresh_humor_references(
            None,
            "https://example.com/empty.csv",
            http_get=lambda _url: header,
            bundled_path=missing,
        )
    except HumorReferenceLoadError as error:
        assert "0 rows" in str(error)
    else:
        raise AssertionError("expected a loud failure")


def _write_csv(directory, body: str):
    path = directory / "humor_references.csv"
    path.write_text(body, encoding="utf-8")
    return path
