"""Shop categories come from the tagger, and a topic tag cannot name another identity."""

import json

from merchandise_discovery.infrastructure.line_categorizer import categorize_line


def _tagger():
    import importlib.util
    from pathlib import Path

    path = Path("scripts/categorize.py").resolve()
    spec = importlib.util.spec_from_file_location("merch_categorize", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    taxonomy = json.loads(Path("data/categories/taxonomy.json").read_text(encoding="utf-8"))
    module.merge_atlas(taxonomy, module.load_atlas("data/identity_atlas"))
    return module.Tagger(taxonomy)


def test_a_nurse_line_does_not_inherit_a_mom_topic_tag() -> None:
    """Night shift can be a secondary topic without borrowing 'tired mom sticker'."""

    tagged = _tagger().tag(
        "FERAL NIGHT SHIFT NURSES WHO FALL ASLEEP TO MURDER PODCASTS",
        "nurses x true crime",
        "true_identity_stack",
        1,
        "irony",
    )

    assert tagged["primary_category"]["slug"] == "nurses"
    assert "tired mom sticker" not in tagged["etsy_tags"]
    assert "tired mom sticker" not in tagged["seo_phrases"]
    assert len(tagged["ebay_title"]) <= 80
    topics = [item["id"] for item in tagged["secondary_categories"] if item["id"].startswith("topic/")]
    assert topics


def test_a_mom_line_can_keep_the_tired_mom_tag() -> None:
    """The same topic tag stays when the line's main identity is mom."""

    tagged = _tagger().tag(
        "TIRED MOM RUNNING ON THREE HOURS",
        "moms x coffee",
        "confession",
        0,
        "irony",
    )

    assert "mom" in tagged["primary_category"]["slug"]
    assert "tired mom sticker" in tagged["etsy_tags"]


def test_final_candidate_export_fields_include_shop_categories() -> None:
    """The engine stamps the fields the run page and the download show."""

    fields = categorize_line(
        "WARNING: OFF-DUTY NURSE. DO NOT SHOW ME YOUR RASH.",
        "nurses x off-duty",
        "official_warning_sign",
        "irony",
    )

    assert fields["main_category"]
    assert isinstance(fields["secondary_categories"], list) and fields["secondary_categories"]
    assert fields["tags"]
    assert "tired mom sticker" not in fields["tags"]
    assert fields["website_title"]
    assert len(fields["ebay_title"]) <= 80
    assert fields["slug"]
