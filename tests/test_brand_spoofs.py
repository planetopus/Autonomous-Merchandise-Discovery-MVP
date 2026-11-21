"""Two of every five finals are major-brand logo spoofs, with the logo in the image prompt."""

from types import SimpleNamespace

from merchandise_discovery.domain.humor import brand_spoofs_needed, is_brand_spoof
from merchandise_discovery.domain.models.common import SocialSource
from merchandise_discovery.domain.pipelines.social_behavior_text.artwork import (
    build_targeted_artwork_prompt,
)
from merchandise_discovery.domain.pipelines.social_behavior_text.pipeline import (
    SocialBehaviorTextCandidate,
)
from merchandise_discovery.infrastructure.brand_catalog import (
    load_brands,
    rotate_brands,
    style_for,
)


def test_brand_catalog_has_a_rotating_set_of_major_logos() -> None:
    """The file covers the major US categories and a run only sees a slice."""

    brands = load_brands()
    categories = {item["category"] for item in brands}
    assert len(brands) >= 150
    for name in ("fast food", "retail", "beverages", "beer", "cars", "tools", "tech", "snacks"):
        assert any(name in category for category in categories)
    first = rotate_brands(brands, "run-a", 8)
    again = rotate_brands(brands, "run-a", 8)
    assert [item["name"] for item in first] == [item["name"] for item in again]
    assert len({item["name"] for item in first}) == 8
    assert style_for("Starbucks")["style"].casefold().find("green") >= 0


def test_five_finals_need_two_logo_spoofs_and_the_prompt_names_the_logo() -> None:
    """The quota is two of five, and the image prompt carries that brand's colors."""

    assert brand_spoofs_needed(5, 0) == 2
    assert brand_spoofs_needed(5, 2) == 0
    assert brand_spoofs_needed(2, 0) == 0
    assert is_brand_spoof(SimpleNamespace(pattern="brand_logo_spoof", spoof_brand=""))
    candidate = SocialBehaviorTextCandidate(
        source_platform=SocialSource.REDDIT,
        source_url="https://reddit.com/r/nursing/comments/abc/coffee",
        source_title="Break room",
        source_excerpt="Nurses live on coffee.",
        audience_context="Night-shift nurses.",
        behavior="Refilling the mug.",
        friction_or_pressure="The pot is empty.",
        artwork_text="SHIFT SIP",
        image_idea="A green circular siren with the new words in the white ring.",
        why_it_works="The siren is the cafe and the words are the shift.",
        format="logo spoof",
        spoof_brand="Starbucks",
        pattern="brand_logo_spoof",
        artwork_prompt="A die-cut vinyl sticker of one green siren logo.",
        visual_punchline="The siren wears a badge.",
        main_visual_metaphor="A green siren.",
        audience_specific_cue="A nurse badge.",
        tone="deadpan",
        style_direction="Flat vector sticker.",
        things_to_avoid=["a scene"],
        specificity_reason="The siren makes the cafe pun.",
    )
    prompt = build_targeted_artwork_prompt(candidate)
    assert "Starbucks" in prompt
    assert "green" in prompt.casefold()
    assert "SHIFT SIP" in prompt
    assert "BACK & BODY HURTS" not in prompt
