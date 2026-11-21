"""Optional eBay Browse API check for sticker lines that are already for sale.

The search runs only when EBAY_APP_TOKEN is set. A missing token, a rate-limit
response, or a network error skips the phrase instead of failing the run.
Calls are spaced so a batch of lines does not burst the Browse API.
"""

import time

import httpx

SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
MIN_INTERVAL_SECONDS = 0.5


class EbayStickerSearch:
    """Look up an exact sticker phrase and flag a near-duplicate listing."""

    def __init__(
        self,
        app_token: str | None = None,
        *,
        client: httpx.Client | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
        min_interval_seconds: float = MIN_INTERVAL_SECONDS,
    ):
        self._token = (app_token or "").strip() or None
        self._client = client
        self._sleep = sleep
        self._clock = clock
        self._min_interval = min_interval_seconds
        self._last_at: float | None = None

    @property
    def enabled(self) -> bool:
        return self._token is not None

    def already_for_sale(self, phrase: str) -> bool | None:
        """Return True, False, or None when the check is skipped."""

        cleaned = " ".join(phrase.split())
        if not self._token or len(cleaned) < 3:
            return None
        client = self._client or httpx.Client(timeout=15.0)
        owns_client = self._client is None
        try:
            self._wait()
            response = client.get(
                SEARCH_URL,
                params={"q": f'"{cleaned}"', "limit": 10},
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                },
            )
            self._last_at = self._clock()
            if response.status_code == 429:
                return None
            response.raise_for_status()
            summaries = response.json().get("itemSummaries") or []
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return None
        finally:
            if owns_client:
                client.close()
        for item in summaries:
            title = str(item.get("title") or "")
            if _is_sticker_listing(title) and _near_duplicate(cleaned, title):
                return True
        return False

    def _wait(self) -> None:
        if self._last_at is None:
            return
        remaining = self._min_interval - (self._clock() - self._last_at)
        if remaining > 0:
            self._sleep(remaining)


def _is_sticker_listing(title: str) -> bool:
    lowered = title.casefold()
    return any(word in lowered for word in ("sticker", "decals", "decal", "vinyl"))


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
