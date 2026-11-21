"""eBay sticker search is optional, rate-limited, and flags near-duplicate listings."""

from unittest.mock import Mock

from merchandise_discovery.domain.humor import LineReviewRecord
from merchandise_discovery.infrastructure.identity_atlas_loader import IdentityAtlas
from merchandise_discovery.infrastructure.providers.ebay_browse import EbayStickerSearch
from tests.test_social_behavior_pipeline import _executor


class _Line:
    def __init__(self, text: str) -> None:
        self.artwork_text = text
        self.pattern = "confession"
        self.who_its_for = ["DIY"]
        self.comic_turn = "ironic"

    def model_copy(self, update=None):
        clone = _Line(self.artwork_text)
        clone.who_its_for = list(self.who_its_for)
        for key, value in (update or {}).items():
            setattr(clone, key, value)
        return clone


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get(self, url, params=None, headers=None):
        self.calls += 1
        return _Response(self.payload)

    def close(self):
        return None


def test_missing_token_skips_the_search() -> None:
    checker = EbayStickerSearch(app_token=None, client=_Client({}))

    assert checker.already_for_sale("My coffee gets tenure") is None
    assert checker.enabled is False


def test_a_matching_sticker_listing_is_already_for_sale() -> None:
    client = _Client(
        {"itemSummaries": [{"title": "I teach water-only. My coffee gets tenure. vinyl sticker"}]}
    )
    slept: list[float] = []
    now = {"value": 0.0}

    def clock() -> float:
        return now["value"]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now["value"] += seconds

    checker = EbayStickerSearch(
        app_token="token",
        client=client,
        sleep=sleep,
        clock=clock,
        min_interval_seconds=0.5,
    )

    assert checker.already_for_sale("My coffee gets tenure") is True
    assert checker.already_for_sale("A completely different joke") is False
    assert slept == [0.5]


def test_a_listed_line_is_dropped_when_a_clean_line_remains() -> None:
    """Near-duplicate sticker listings leave the run, and every row names who it is for."""

    executor = _executor(Mock())

    class _Checker:
        enabled = True

        def already_for_sale(self, phrase: str) -> bool:
            return "shop vac" in phrase.casefold()

    executor._ebay_checker = _Checker()
    drafted = [_Line("Deploy the shop vac for one crumb."), _Line("Hands off the pegboard.")]
    reviews = [
        LineReviewRecord(artwork_text=line.artwork_text, pattern="confession", kept=True, reason="kept")
        for line in drafted
    ]
    stamped, reviews = executor._apply_who_its_for(
        drafted,
        reviews,
        IdentityAtlas(),
        ["garage dads", "beer"],
    )
    kept, reviews, note = executor._drop_already_for_sale(stamped, reviews)

    assert [line.artwork_text for line in kept] == ["Hands off the pegboard."]
    assert "already for sale" in note
    assert any(review.reason == "already for sale" and review.kept is False for review in reviews)
    assert all(2 <= len(line.who_its_for) <= 4 for line in kept)
    assert all(2 <= len(review.who_its_for) <= 4 for review in reviews)
