"""Store checks flag near-duplicate listings and stay optional when a search fails."""

from unittest.mock import Mock

from merchandise_discovery.domain.humor import LineReviewRecord
from merchandise_discovery.domain.models.usage import UsageMetrics
from merchandise_discovery.infrastructure.identity_atlas_loader import IdentityAtlas
from merchandise_discovery.infrastructure.providers.ebay_browse import EbayStickerSearch
from merchandise_discovery.infrastructure.providers.web_listing_search import WebListingSearch
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


def test_web_search_flags_a_store_listing_without_an_ebay_token() -> None:
    """The OpenAI web search quotes the line and keeps the selling URL."""

    queries: list[str] = []
    slept: list[float] = []
    now = {"value": 0.0}

    def search(query: str):
        queries.append(query)
        if "shop vac" in query:
            return (
                [
                    {
                        "url": "https://www.etsy.com/listing/9/deploy-the-shop-vac-for-one-crumb-sticker",
                        "title": "Deploy the shop vac for one crumb vinyl sticker",
                    }
                ],
                UsageMetrics(provider="openai", model="gpt-5", request_count=1, total_tokens=5),
            )
        return (
            [
                {
                    "url": "https://www.reddit.com/r/dads/comments/1/hands",
                    "title": "Hands off the pegboard.",
                }
            ],
            UsageMetrics(provider="openai", model="gpt-5", request_count=1, total_tokens=5),
        )

    def clock() -> float:
        return now["value"]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now["value"] += seconds

    listing_search = WebListingSearch(search=search, sleep=sleep, clock=clock, min_interval_seconds=0.5)
    executor = _executor(Mock())
    executor._listing_search = listing_search
    lines = [_Line("Deploy the shop vac for one crumb."), _Line("Hands off the pegboard.")]
    reviews = [
        LineReviewRecord(artwork_text=line.artwork_text, pattern="confession", kept=True, reason="kept")
        for line in lines
    ]

    kept, reviews, note = executor._drop_already_for_sale(lines, reviews)

    assert queries == [
        '"Deploy the shop vac for one crumb." sticker OR shirt OR decal',
        '"Hands off the pegboard." sticker OR shirt OR decal',
    ]
    assert slept == [0.5]
    assert [line.artwork_text for line in kept] == ["Hands off the pegboard."]
    assert "already for sale" in note
    flagged = next(review for review in reviews if review.kept is False and "shop vac" in review.artwork_text)
    assert flagged.reason == (
        "already for sale: "
        "https://www.etsy.com/listing/9/deploy-the-shop-vac-for-one-crumb-sticker"
    )
    assert listing_search.usage.request_count == 2


def test_a_failed_web_search_keeps_the_line() -> None:
    """A provider error skips the originality check instead of emptying the run."""

    def search(_query: str):
        raise RuntimeError("web search unavailable")

    listing_search = WebListingSearch(search=search)
    assert listing_search.find_listing("Deploy the shop vac for one crumb.") is None
