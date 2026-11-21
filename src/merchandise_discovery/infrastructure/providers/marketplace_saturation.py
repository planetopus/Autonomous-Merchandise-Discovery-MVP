"""Count existing sticker listings so crowded lines can be dropped before artwork.

Etsy is used when ETSY_API_KEY is configured. Otherwise a public web result count is
used in live mode. Fixture mode and failed requests skip the check instead of failing
the run.
"""

from dataclasses import dataclass

import httpx

DROP_COUNT = 40
DOWNRANK_COUNT = 15


@dataclass(frozen=True)
class PhraseSaturation:
    """How crowded one merchandise phrase already is."""

    item_id: str
    count: int | None
    source: str
    note: str

    @property
    def drop(self) -> bool:
        """A very crowded phrase should not reach artwork when another line exists."""

        return self.count is not None and self.count >= DROP_COUNT

    @property
    def downrank(self) -> bool:
        """A moderately crowded phrase stays, but it should rank below a fresher line."""

        return self.count is not None and self.count >= DOWNRANK_COUNT


class MarketplaceChecker:
    """Look up sticker saturation, or report that the check was skipped."""

    def __init__(
        self,
        *,
        etsy_api_key: str | None = None,
        live: bool = False,
        client: httpx.Client | None = None,
        sleep=lambda _seconds: None,
    ):
        self._etsy_api_key = (etsy_api_key or "").strip() or None
        self._live = live
        self._client = client
        self._sleep = sleep

    def check(self, items: list[tuple[str, str]]) -> list[PhraseSaturation]:
        """Return one finding per phrase. Missing keys and network errors skip that phrase."""

        if not self._live:
            return [
                PhraseSaturation(item_id, None, "skipped", "Marketplace check skipped outside live mode.")
                for item_id, _phrase in items
            ]
        client = self._client or httpx.Client(timeout=20.0, follow_redirects=True)
        owns_client = self._client is None
        findings: list[PhraseSaturation] = []
        try:
            for index, (item_id, phrase) in enumerate(items):
                if index:
                    self._sleep(0.5 if self._etsy_api_key else 1.0)
                findings.append(self._one(client, item_id, phrase))
        finally:
            if owns_client:
                client.close()
        return findings

    def _one(self, client: httpx.Client, item_id: str, phrase: str) -> PhraseSaturation:
        cleaned = " ".join(phrase.split())
        if not cleaned:
            return PhraseSaturation(item_id, None, "skipped", "No phrase to check.")
        try:
            if self._etsy_api_key:
                count = _etsy_count(client, cleaned, self._etsy_api_key)
                return PhraseSaturation(item_id, count, "etsy", f"Etsy active listings for '{cleaned} sticker': {count}.")
            count = _web_result_count(client, cleaned)
            return PhraseSaturation(item_id, count, "web", f"Web results for '{cleaned} sticker': {count}.")
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return PhraseSaturation(item_id, None, "skipped", "Marketplace check failed and was skipped.")


def _etsy_count(client: httpx.Client, phrase: str, api_key: str) -> int:
    """Return Etsy's reported active-listing count for the phrase plus sticker."""

    response = client.get(
        "https://openapi.etsy.com/v3/application/listings/active",
        params={"keywords": f"{phrase} sticker", "limit": 1},
        headers={"x-api-key": api_key},
    )
    response.raise_for_status()
    payload = response.json()
    return int(payload.get("count") or 0)


def _web_result_count(client: httpx.Client, phrase: str) -> int:
    """Count public search-result markers for the phrase plus the word sticker."""

    response = client.get(
        "https://html.duckduckgo.com/html/",
        params={"q": f"\"{phrase}\" sticker"},
        headers={"User-Agent": "autonomous-merchandise-discovery/0.1"},
    )
    response.raise_for_status()
    return response.text.count("result__a")
