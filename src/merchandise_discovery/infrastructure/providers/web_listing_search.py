"""Check final sticker lines against stores with the app's OpenAI web search.

One search per final candidate, for the exact phrase in quotes plus
``sticker OR shirt OR decal``. A missing provider, a rate limit, or a
network error skips that line. The eBay Browse API remains a separate extra.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from merchandise_discovery.domain.models.usage import UsageMetrics, combine_usage

MIN_INTERVAL_SECONDS = 0.5

# Print-on-demand shops are merchandise even when the title omits the word sticker.
_MERCH_STORES = (
    "redbubble.",
    "teepublic.",
    "zazzle.",
    "society6.",
    "spreadshirt.",
    "threadless.",
    "lookhuman.",
    "bonfire.com",
    "teespring.",
    "cafepress.",
    "printful.",
    "printify.",
    "stickermule.",
)
# General marketplaces sell everything, so the page also has to be merchandise.
_GENERAL_STORES = ("ebay.", "etsy.", "amazon.", "walmart.", "shopify.")
_MERCH_WORDS = ("sticker", "shirt", "decal", "vinyl", "t-shirt", "tshirt", "tee ")


@dataclass(frozen=True)
class SaleListing:
    """One page that already sells a near-duplicate of the line."""

    url: str
    title: str


class WebListingSearch:
    """Search the public web for a phrase that is already for sale."""

    def __init__(
        self,
        search,
        *,
        sleep=time.sleep,
        clock=time.monotonic,
        min_interval_seconds: float = MIN_INTERVAL_SECONDS,
    ):
        self._search = search
        self._sleep = sleep
        self._clock = clock
        self._min_interval = min_interval_seconds
        self._last_at: float | None = None
        self._lock = threading.Lock()
        self.usage = UsageMetrics()

    @property
    def enabled(self) -> bool:
        return self._search is not None

    def find_listing(self, phrase: str) -> SaleListing | None:
        """Return the selling page, or None when the line is clear or the search was skipped."""

        cleaned = " ".join(phrase.split())
        if not self.enabled or len(cleaned) < 3:
            return None
        query = f'"{cleaned}" sticker OR shirt OR decal'
        try:
            self._reserve()
            citations, usage = self._search(query)
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
        self._add_usage(usage)
        for item in citations or []:
            url = str(item.get("url") or "")
            title = str(item.get("title") or "")
            if _sold_as_merch(url, title) and _near_phrase(cleaned, title, url):
                return SaleListing(url=url, title=title)
        return None

    def _add_usage(self, usage: UsageMetrics | None) -> None:
        if usage is None:
            return
        with self._lock:
            if self.usage.request_count == 0 and self.usage.total_tokens == 0:
                self.usage = usage
                return
            self.usage = combine_usage(self.usage, usage)

    def find_listings(self, phrases: list[str], *, workers: int = 4) -> list[SaleListing | None]:
        """Search several exact phrases. Starts are staggered so the provider is not stampeded."""

        if not phrases:
            return []
        if workers <= 1 or len(phrases) == 1:
            return [self.find_listing(phrase) for phrase in phrases]
        count = max(1, min(workers, len(phrases)))
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(self.find_listing, phrases))

    def _reserve(self) -> None:
        """Leave a short gap between search starts, including across threads."""

        with self._lock:
            if self._last_at is not None:
                remaining = self._min_interval - (self._clock() - self._last_at)
                if remaining > 0:
                    self._sleep(remaining)
            self._last_at = self._clock()


def _sold_as_merch(url: str, title: str) -> bool:
    """A result counts when a store is selling it as a sticker, shirt, or decal."""

    host = urlparse(url).netloc.casefold()
    blob = f"{url} {title}".casefold()
    if any(store in host for store in _MERCH_STORES):
        return True
    if any(store in host for store in _GENERAL_STORES):
        return any(word in blob for word in _MERCH_WORDS)
    return any(word in blob for word in ("sticker", "decal", "vinyl", "t-shirt", "tshirt"))


def _near_phrase(phrase: str, title: str, url: str) -> bool:
    slug = unquote(urlparse(url).path).replace("-", " ").replace("_", " ").replace("/", " ")
    return _near_duplicate(phrase, title) or _near_duplicate(phrase, slug)


def _near_duplicate(phrase: str, title: str) -> bool:
    phrase_norm = " ".join(phrase.casefold().split())
    title_norm = " ".join(title.casefold().split())
    if phrase_norm and phrase_norm in title_norm:
        return True
    phrase_tokens = {token for token in phrase_norm.split() if len(token) > 2}
    title_tokens = set(title_norm.split())
    if not phrase_tokens:
        return False
    return len(phrase_tokens & title_tokens) / len(phrase_tokens) >= 0.75
