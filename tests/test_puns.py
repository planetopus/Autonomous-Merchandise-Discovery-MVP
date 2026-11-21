"""Puns and spoofs are word-and-image pairs, not a caption with a literal picture."""

from types import SimpleNamespace

from merchandise_discovery.domain.humor import (
    HumorCritiqueItem,
    LineReview,
    apply_line_critic,
    humor_prompt_suffix,
    line_is_pun,
    pun_examples_block,
    pun_share,
    pun_share_is_thin,
)
from merchandise_discovery.domain.humor_playbook import build_playbook, playbook_prompt
from merchandise_discovery.domain.models.common import HumorTone
from merchandise_discovery.domain.pipelines.social_behavior_text.pipeline import (
    SocialBehaviorTextCandidate,
)
from merchandise_discovery.domain.pipelines.social_identity_focused.pipeline import (
    SocialIdentityTextCandidate,
)


def _review(**overrides) -> LineReview:
    values = {
        "humor_landed": 8,
        "novelty": 8,
        "tone_match": 8,
        "reddit_upvote_score": 8,
        "sticker_buy_score": 8,
        "instantly_understandable": 8,
        "word_image_synergy": 9,
    }
    values.update(overrides)
    return LineReview(0, **values)


def test_best_seller_anchors_name_the_pattern_the_picture_and_the_format() -> None:
    """The few-shot block is the pairing, including the later best sellers."""

    block = pun_examples_block()

    for line in (
        "TOAST MALONE",
        "THIS MIGHT BE VODKA",
        "BACK & BODY HURTS",
        "WHY DON'T YOU BLOW ME",
        "SOMETIMES I WET MY PLANTS",
        "SUC MY CAC",
        "DON'T BE A CUNTASAURUS",
        "JUST THE TIP",
        "SHOW ME YOUR KITTIES",
        "PEACE WAS NEVER AN OPTION",
        "BRING A COMPASS",
        "THICK THIGHS SAVE LIVES",
        "GOLF CART",
        "patients, not patience",
        "BOLDLY GOING NOWHERE",
        "CAN WE FIX IT? NO. IT'S FUCKED.",
        "BEN DRANKIN",
        "ALDEEZ NUTS",
        "D.A.M.M. DRUNKS AGAINST MAD MOTHERS",
        "WARNING: DANGEROUS GASSES",
        "MASTER BAITER - World Class",
        "SEND NOODS",
        "NOT MY PASTURE, NOT MY BULLSHIT",
        "FIGHT CRIME, SHOOT BACK",
        "DON'T FORGET THE VASOLINE WHEN YOU GET THE GASOLINE",
    ):
        assert line in block
    for pattern in (
        "celebrity_food_pun",
        "brand_logo_spoof",
        "innocent_image_innuendo",
        "cute_but_menacing",
        "dark_twist_scene",
        "catchphrase_flip",
        "relatable_confession_action",
        "pop_culture_quote_flip",
        "historical_name_pun",
        "fake_acronym_org",
        "fake_warning_sign",
        "slogan_twist",
        "rhyme_innuendo",
    ):
        assert pattern in block
    for layout in (
        "retro sunset badge",
        "logo spoof",
        "circle badge",
        "bold text stack",
        "bumper sticker strip",
        "warning sign",
        "plaque",
    ):
        assert layout in block
    assert "Do not reprint" in block
    assert "Do not generate an image" in block
    assert len(block) // 4 < 2_000


def test_pun_shapes_survive_a_short_playbook_and_the_old_leaders_stay_first() -> None:
    """A trimmed prompt still teaches the spoof family. The first three shapes do not move."""

    playbook = build_playbook([])
    ids = [item["id"] for item in playbook["patterns"]]
    assert ids[:3] == [
        "clarity_beats_cleverness",
        "absurd_identity_stack",
        "self_defeating_sign",
    ]
    assert "dark_twist_scene" in ids
    assert "catchphrase_flip" in ids
    assert "pop_culture_quote_flip" in ids
    assert "rhyme_innuendo" in ids
    assert "slogan_twist" in ids
    crowded = [
        {"id": f"lab_{index}", "label": "Lab", "guidance": "Lab shape.", "priority": True, "examples": []}
        for index in range(12)
    ]
    crowded.append(
        {
            "id": "brand_logo_spoof",
            "label": "Brand logo spoof",
            "guidance": "A famous logo whose text flips the brand.",
            "priority": True,
            "examples": [],
        }
    )
    prompt = playbook_prompt({"patterns": crowded}, limit=8)
    assert "brand_logo_spoof" in prompt
    suffix = humor_prompt_suffix(HumorTone.DRY)
    assert "30 to 40" in suffix
    assert "image_idea" in suffix
    assert "why_it_works" in suffix
    assert "word-and-image pair" in suffix
    packed = suffix + pun_examples_block() + playbook_prompt(playbook, limit=8)
    assert len(packed) // 4 < 60_000


def test_spoof_patterns_count_toward_the_pun_share() -> None:
    """About a third of a batch should be one of the pun or spoof shapes."""

    puns = [
        SimpleNamespace(pattern="brand_logo_spoof", humor_mechanism=""),
        SimpleNamespace(pattern="dark_twist_scene", humor_mechanism=""),
        SimpleNamespace(pattern="catchphrase_flip", humor_mechanism=""),
        SimpleNamespace(pattern="relatable_confession_action", humor_mechanism="spoof"),
    ]
    other = [SimpleNamespace(pattern="confession", humor_mechanism="irony") for _ in range(6)]
    batch = puns + other

    assert pun_share(batch) == 0.4
    assert not pun_share_is_thin(batch)
    assert pun_share_is_thin(other + other)
    assert line_is_pun(SimpleNamespace(pattern="image_pun", humor_mechanism=""))
    assert line_is_pun(SimpleNamespace(pattern="fake_acronym_org", humor_mechanism=""))
    assert line_is_pun(SimpleNamespace(pattern="slogan_twist", humor_mechanism=""))
    assert not line_is_pun(SimpleNamespace(pattern="confession", humor_mechanism="recognition"))


def test_synergy_and_a_forced_pun_cap_the_line_a_clear_pair_stays() -> None:
    """The picture has to finish the joke. A literal illustration and a groan do not."""

    pair = SimpleNamespace(
        artwork_text="JUST THE TIP",
        pattern="innocent_image_innuendo",
        comic_turn="straight",
        phrase="",
        humor_mechanism="pun",
    )
    kept = apply_line_critic([pair], [_review()], keep_count=1, tone=HumorTone.DRY)
    assert kept == [pair]

    literal = _review(word_image_synergy=9, literal_image=True)
    assert apply_line_critic([pair], [literal], keep_count=1, tone=HumorTone.DRY) == []

    weak = _review(word_image_synergy=3)
    assert apply_line_critic([pair], [weak], keep_count=1, tone=HumorTone.DRY) == []
    assert weak.sticker_buy_score == 4

    groan = _review(pun_forced=True)
    assert apply_line_critic([pair], [groan], keep_count=1, tone=HumorTone.DRY) == []
    assert groan.sticker_buy_score == 4

    obscure = _review(pun_lands=False)
    assert apply_line_critic([pair], [obscure], keep_count=1, tone=HumorTone.DRY) == []

    straight = SimpleNamespace(
        artwork_text="I did the chore",
        pattern="confession",
        comic_turn="straight",
        phrase="",
        humor_mechanism="recognition",
    )
    assert apply_line_critic([straight], [_review()], keep_count=1, tone=HumorTone.DRY) == []


def test_new_pair_fields_default_so_older_lines_still_validate() -> None:
    """Scripted critic rows and candidates omit the new fields and stay valid."""

    critique = HumorCritiqueItem(index=0, humor_landed=8, novelty=8, tone_match=8)
    assert critique.word_image_synergy == 8
    assert critique.pun_lands is True
    assert critique.pun_forced is False
    assert critique.literal_image is False

    behavior = SocialBehaviorTextCandidate.model_fields
    identity = SocialIdentityTextCandidate.model_fields
    for fields in (behavior, identity):
        assert fields["image_idea"].default == ""
        assert fields["why_it_works"].default == ""
        assert fields["format"].default == ""
