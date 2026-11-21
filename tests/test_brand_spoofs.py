"""Two of every five finals are major-brand logo spoofs, with the logo in the image prompt."""

from types import SimpleNamespace

from merchandise_discovery.domain.humor import (
    dark_humor_needed,
    is_brand_spoof,
    is_dark_humor,
    order_kept_lines,
    spoof_earns_final,
)
from merchandise_discovery.domain.models.common import SocialSource
from merchandise_discovery.domain.pipelines.social_behavior_text.artwork import (
    build_targeted_artwork_prompt,
)
from merchandise_discovery.domain.pipelines.social_behavior_text.pipeline import (
    SocialBehaviorTextCandidate,
)
from merchandise_discovery.domain.sticker_direction import sticker_download_name
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

    assert dark_humor_needed(5, 0) == 1
    assert dark_humor_needed(12, 1) == 1
    assert dark_humor_needed(2, 0) == 0
    assert is_brand_spoof(SimpleNamespace(pattern="brand_logo_spoof", spoof_brand=""))
    weak = SimpleNamespace(
        pattern="brand_logo_spoof",
        spoof_brand="Subway",
        funny_score=7.0,
        brand_fits=False,
        brand_joke_link="The name sounds like sleep.",
    )
    strong = SimpleNamespace(
        pattern="brand_logo_spoof",
        spoof_brand="Bath & Body Works",
        funny_score=9.0,
        brand_fits=True,
        brand_joke_link="The store is self-care for aging moms, so the ache is the product.",
    )
    assert not spoof_earns_final(weak)
    assert spoof_earns_final(strong)
    assert is_dark_humor(SimpleNamespace(pattern="dark_twist_scene", humor_mechanism=""))
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


def test_the_final_five_keep_the_higher_scores_and_one_dark_line() -> None:
    """A weak logo swap stays out. A dark line and the 7.6 pun stay in."""

    def line(text: str, score: float, pattern: str) -> SimpleNamespace:
        return SimpleNamespace(
            artwork_text=text,
            funny_score=score,
            pattern=pattern,
            spoof_brand="Subway" if pattern == "brand_logo_spoof" else "",
            brand_fits=score >= 8.5,
            brand_joke_link=(
                "The brand's product is why this is funny for this buyer."
                if score >= 8.5
                else ""
            ),
            humor_mechanism="gallows" if pattern == "dark_twist_scene" else "",
        )

    kept = order_kept_lines(
        [
            line("SUBZZZ", 6.0, "brand_logo_spoof"),
            line("WEAK LINE", 4.1, "confession"),
            line("KENTUCKY FRIED COUCH", 7.6, "wordplay_pun"),
            line("TACO ZZZ", 7.4, "wordplay_pun"),
            line("EAT YOUR FRIENDS", 7.2, "dark_twist_scene"),
            line("MID STACK", 5.0, "absurd_identity_stack"),
        ],
        5,
    )
    names = [item.artwork_text for item in kept]
    assert names[0] == "EAT YOUR FRIENDS"
    assert "KENTUCKY FRIED COUCH" in names
    assert "TACO ZZZ" in names
    assert "SUBZZZ" not in names
    assert names[-1] == "WEAK LINE"
    used: set[str] = set()
    assert sticker_download_name("KENTUCKY FRIED COUCH", used) == "kentucky-fried-couch.png"
    assert sticker_download_name("KENTUCKY FRIED COUCH", used) == "kentucky-fried-couch-2.png"
