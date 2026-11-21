"""Studio keeps a dark line, unique styles, and drops copies, clichés, and listings."""

import base64
import io
import re
from types import SimpleNamespace

from PIL import Image

from merchandise_discovery.application.discovery_stage_executor import (
    _expected_sticker_text,
    _shrink_vision_url,
)
from merchandise_discovery.domain.humor import StickerTextBatch, StickerTextCheck
from merchandise_discovery.domain.models.artifacts import Artwork
from merchandise_discovery.domain.models.common import IdentityType, PipelineVariant, SocialSource
from merchandise_discovery.domain.models.usage import UsageMetrics
from merchandise_discovery.domain.models.workflow import RunConfig, WorkflowRun
from merchandise_discovery.domain.pipelines.social_identity_focused.artwork import (
    build_identity_artwork_prompt,
)
from merchandise_discovery.domain.pipelines.social_identity_v2.pipeline import (
    SocialIdentityV2Input,
    SocialIdentityV2Output,
)
from merchandise_discovery.domain.stages.stage_15_artwork_generation import ArtworkGenerationOutput
from merchandise_discovery.domain.studio_lines import (
    ScoredLine,
    StudioBatch,
    StudioLine,
    reject_unoriginal,
    select_studio_finals,
    studio_image_prompt,
)
from merchandise_discovery.infrastructure.providers.web_listing_search import WebListingSearch
from tests.test_social_behavior_pipeline import _executor

_CLEARS = [f"Raid boss {number} forgot the watering can today" for number in range(10)]


def _line(
    text: str,
    *,
    score: float = 9,
    dark: bool = False,
    buyers: list[str] | None = None,
    spoof: str = "",
    brand_fits: bool = True,
    link: str = "",
    critic_ok: bool = True,
    buyer_ok: bool = True,
    scene: str = "A single object finishes the joke.",
) -> ScoredLine:
    return ScoredLine(
        text=text,
        buyers=buyers or ["gardeners", "gamers"],
        scene=scene,
        dark=dark,
        spoof_brand=spoof,
        kind="crossover",
        format_source="",
        pattern="dark twist scene" if dark else "wordplay pun",
        score=score,
        brand_fits=brand_fits,
        brand_joke_link=link,
        critic_ok=critic_ok,
        buyer_ok=buyer_ok,
        critic_reason="lands",
        buyer_reason="would buy",
    )


def test_finals_keep_one_dark_line_and_do_not_reuse_a_style() -> None:
    """Ten survivors include the dark joke, and each one gets a different style."""

    lines = [_line(text, score=9 - (index * 0.01)) for index, text in enumerate(_CLEARS)]
    lines.append(_line("The group chat died at 2 AM again", score=7.5, dark=True))
    lines.append(
        _line(
            "I knead coffee before sunrise",
            score=9,
            spoof="Starbucks",
            brand_fits=False,
            link="The logo is only a name swap.",
        )
    )
    styled, note = select_studio_finals(lines, 10, flat_only=False)

    texts = [line.text for line, _name, _note in styled]
    styles = [name for _line, name, _note in styled]
    assert len(styled) == 10
    assert "The group chat died at 2 AM again" in texts
    assert "I knead coffee before sunrise" not in texts
    assert len(set(styles)) == 10
    assert note == ""


def test_flat_only_uses_the_current_flat_style_on_every_line() -> None:
    """The owner's flat vector look stays available as a single style."""

    lines = [_line(text) for text in _CLEARS[:4]]
    lines.append(_line("The group chat died at 2 AM again", score=8, dark=True))
    styled, _note = select_studio_finals(lines, 4, flat_only=True)

    assert len(styled) == 4
    assert {name for _line, name, _note in styled} == {"flat vector"}


def test_a_listed_phrase_and_a_copied_example_do_not_ship() -> None:
    """The sale flag and the example list both remove a line before the finals."""

    copied = _line("Perennials Respawn. Annuals Rage Quit.")
    fresh, dropped = reject_unoriginal([copied, *[_line(text) for text in _CLEARS[:3]]])
    assert [line.text for line in dropped] == ["Perennials Respawn. Annuals Rage Quit."]
    listed = _line("The fridge has opinions now")
    listed.for_sale_url = "https://www.etsy.com/listing/1/the-fridge-has-opinions-now-sticker"
    pool = [*fresh, listed, _line("The group chat died at 2 AM again", score=8, dark=True)]
    styled, _note = select_studio_finals(pool, 4, flat_only=True)

    texts = [line.text for line, _name, _note in styled]
    assert "The fridge has opinions now" not in texts
    assert "Perennials Respawn. Annuals Rage Quit." not in texts


def test_image_prompt_uses_the_exact_line_the_scene_and_the_style() -> None:
    """The picture request is the line, the scene, and one style on a white die-cut sticker."""

    prompt = studio_image_prompt(
        "Raid boss 0 forgot the watering can today",
        "A tomato with a health bar holds an empty watering can.",
        "pixel art",
        "Pixel art: chunky pixels, a limited 8-bit palette, no smooth vectors.",
    )

    assert 'spelled exactly: "Raid boss 0 forgot the watering can today"' in prompt
    assert "empty watering can" in prompt
    assert "pixel art" in prompt
    assert "Die-cut vinyl sticker" in prompt
    assert "plain white background" in prompt
    assert len(prompt) >= 180


def test_studio_run_gates_lines_and_labels_every_survivor() -> None:
    """A scripted studio run drops the three failures and labels the ten that remain."""

    drafts = {
        "crossover": [
            _draft("Perennials Respawn. Annuals Rage Quit.", kind="crossover"),
            _draft("Another Monday another mug", kind="crossover"),
            _draft("Office plants file a grievance", kind="crossover"),
            _draft("I knead coffee before sunrise", kind="crossover", spoof="Starbucks"),
            _draft("The group chat died at 2 AM again", kind="crossover", dark=True),
            *[_draft(text, kind="crossover") for text in _CLEARS[:4]],
        ],
        "format": [
            _draft("The fridge has opinions now", kind="format"),
            *[_draft(text, kind="format") for text in _CLEARS[4:]],
        ],
    }

    def respond(**kwargs):
        model = kwargs["response_model"]
        name = model.__name__
        prompt = kwargs["user_prompt"]
        usage = UsageMetrics(provider="openai", model="gpt-5", request_count=1, total_tokens=12)
        if name == "StudioBatch":
            half = "format" if "ORIGINAL" in prompt else "crossover"
            return SimpleNamespace(output=StudioBatch(lines=drafts[half]), usage=usage)
        if name == "ComedyGateBatch":
            return SimpleNamespace(output=model(reviews=_comedy(prompt)), usage=usage)
        if name == "BuyerGateBatch":
            return SimpleNamespace(output=model(reviews=_buyers(prompt)), usage=usage)
        raise AssertionError(name)

    provider = SimpleNamespace(complete_structured=respond)
    search_calls: list[str] = []

    def search(query: str):
        search_calls.append(query)
        if "fridge has opinions" in query.casefold():
            return (
                [
                    {
                        "url": "https://www.etsy.com/listing/9/the-fridge-has-opinions-now-sticker",
                        "title": "The fridge has opinions now sticker",
                    }
                ],
                UsageMetrics(provider="openai", model="gpt-5", request_count=1, total_tokens=4),
            )
        return ([], UsageMetrics(provider="openai", model="gpt-5", request_count=1, total_tokens=4))

    executor = _executor(SimpleNamespace())
    executor._reasoning_provider = provider
    executor._listing_search = WebListingSearch(search, min_interval_seconds=0)
    run = WorkflowRun(
        title="Studio",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_IDENTITY_V2,
            social_generation_mode="studio",
            social_fast_mode=True,
            social_check_already_for_sale=True,
            social_identity="gardeners",
            social_identity_type=IdentityType.INTEREST,
            social_query="weekend routines",
            social_niche_a="gardeners",
            social_niche_b="gamers",
            social_candidate_count=10,
        ),
    )
    input_model = SocialIdentityV2Input(
        sources=[SocialSource.REDDIT],
        identity="gardeners",
        identity_type=IdentityType.INTEREST,
        query="weekend routines",
        candidate_count=10,
        niche_a="gardeners",
        niche_b="gamers",
    )

    output, _usage, _selection, reviews, _playbook, _pair = executor._studio_reasoning(
        run,
        input_model,
        None,
        SocialIdentityV2Output,
    )

    texts = [candidate.artwork_text for candidate in output.candidates]
    assert len(texts) == 10
    assert "The group chat died at 2 AM again" in texts
    assert "Perennials Respawn. Annuals Rage Quit." not in texts
    assert "Another Monday another mug" not in texts
    assert "Office plants file a grievance" not in texts
    assert "I knead coffee before sunrise" not in texts
    assert "The fridge has opinions now" not in texts
    styles = {candidate.style_direction.split(".", 1)[0] for candidate in output.candidates}
    assert len(styles) == 10
    assert all(2 <= len(candidate.who_its_for) <= 4 for candidate in output.candidates)
    assert all(
        "Die-cut vinyl sticker" in candidate.artwork_prompt for candidate in output.candidates
    )
    assert all(
        candidate.artwork_text in candidate.artwork_prompt for candidate in output.candidates
    )
    assert any(review.kept is False and "already for sale" in review.reason for review in reviews)
    assert any(review.kept is False and "copied" in review.reason for review in reviews)
    assert search_calls
    assert "Fast mode skipped Reddit" in output.stage_warning
    direct = build_identity_artwork_prompt(output.candidates[0])
    assert direct == output.candidates[0].artwork_prompt


def test_expected_sticker_text_is_the_line_not_the_audience_prefix() -> None:
    artwork = Artwork(
        run_id="run",
        concept_id="concept",
        brief_id="brief",
        prompt="prompt",
        combination_name="Gardeners · Raid boss 0 forgot the watering can today",
        source_url="https://example.com/sticker.png",
    )

    assert _expected_sticker_text(artwork) == "Raid boss 0 forgot the watering can today"


def test_text_check_runs_against_the_exact_line() -> None:
    """A vision success is recorded, and the call is about the sticker words."""

    seen: dict[str, str] = {}

    def respond(**kwargs):
        seen["prompt"] = kwargs["user_prompt"]
        seen["model"] = kwargs["model"]
        return SimpleNamespace(
            output=StickerTextBatch(checks=[StickerTextCheck(index=1, text_ok=True, problem="")]),
            usage=UsageMetrics(provider="openai", model="gpt-4o-mini", request_count=1),
        )

    executor = _executor(SimpleNamespace())
    executor._reasoning_provider = SimpleNamespace(complete_structured=respond)
    artwork = Artwork(
        run_id="run",
        concept_id="concept",
        brief_id="brief",
        prompt="Die-cut sticker",
        combination_name="Gardeners · Raid boss 0 forgot the watering can today",
        source_url="https://example.com/sticker.png",
        critique={"who_its_for": "gardeners · gamers"},
    )
    run = WorkflowRun(title="Check", config=RunConfig(social_image_qa=True))

    result = executor._check_sticker_text(
        run,
        ArtworkGenerationOutput(artworks=[artwork]),
    )

    assert result.artworks[0].critique["text_check"] == "passed"
    assert result.artworks[0].critique["who_its_for"] == "gardeners · gamers"
    assert 'exactly "Raid boss 0 forgot the watering can today"' in seen["prompt"]
    assert "Gardeners ·" not in seen["prompt"]
    assert seen["model"] == "gpt-4o-mini"
    assert result.warning == ""


def test_text_check_records_the_reason_when_the_vision_call_fails() -> None:
    """A failed vision call is skipped with the error, which the page can show."""

    def respond(**_kwargs):
        raise RuntimeError("vision rejected the reasoning parameter")

    executor = _executor(SimpleNamespace())
    executor._reasoning_provider = SimpleNamespace(complete_structured=respond)
    artwork = Artwork(
        run_id="run",
        concept_id="concept",
        brief_id="brief",
        prompt="Die-cut sticker",
        combination_name="Raid boss 0 forgot the watering can today",
        source_url="https://example.com/sticker.png",
    )
    run = WorkflowRun(title="Check", config=RunConfig())

    result = executor._check_sticker_text(run, ArtworkGenerationOutput(artworks=[artwork]))

    assert result.artworks[0].critique["text_check"] == "skipped"
    assert "reasoning parameter" in result.artworks[0].critique["text_problem"]
    assert "did not run" in result.warning


def test_vision_images_are_shrunk_before_the_text_check() -> None:
    """A large sticker PNG is reduced so the vision request can actually be sent."""

    image = Image.new("RGB", (1200, 900), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    shrunk = _shrink_vision_url(f"data:image/png;base64,{payload}")
    encoded = shrunk.split(",", 1)[1]
    opened = Image.open(io.BytesIO(base64.b64decode(encoded)))

    assert max(opened.size) <= 768


def _draft(text: str, *, kind: str, dark: bool = False, spoof: str = "") -> StudioLine:
    return StudioLine(
        artwork_text=text,
        buyer_groups=["gardeners", "gamers"],
        scene=f"The picture for {text} carries the joke.",
        dark=dark,
        spoof_brand=spoof,
        kind=kind,
        format_source="doorbell count" if kind == "format" else "",
        pattern="",
    )


def _quoted(prompt: str) -> list[tuple[int, str]]:
    comedy = re.findall(r'(?m)^(\d+)\. "(.*)" Picture:', prompt)
    if comedy:
        return [(int(index), text) for index, text in comedy]
    buyer = re.findall(r'(?m)^(\d+)\. Buyers:.*?Line: "(.*)" Picture:', prompt)
    return [(int(index), text) for index, text in buyer]


def _comedy(prompt: str):
    from merchandise_discovery.domain.studio_lines import ComedyGateItem

    reviews = []
    for index, text in _quoted(prompt):
        if "Monday" in text:
            reviews.append(
                ComedyGateItem(
                    index=index,
                    passed=False,
                    score=3,
                    reason="cliché",
                    cliche=True,
                    instant=True,
                    one_joke=False,
                )
            )
            continue
        score = 7.5 if "died" in text.casefold() else 9
        reviews.append(
            ComedyGateItem(
                index=index,
                passed=True,
                score=score,
                reason="one joke",
                cliche=False,
                instant=True,
                one_joke=True,
                brand_fits="knead" not in text.casefold(),
                brand_joke_link=""
                if "knead" not in text.casefold()
                else "The siren is only a name swap.",
            )
        )
    return reviews


def _buyers(prompt: str):
    from merchandise_discovery.domain.studio_lines import BuyerGateItem

    return [
        BuyerGateItem(
            index=index,
            would_buy="grievance" not in text.casefold(),
            reason="not their joke" if "grievance" in text.casefold() else "would buy",
        )
        for index, text in _quoted(prompt)
    ]
