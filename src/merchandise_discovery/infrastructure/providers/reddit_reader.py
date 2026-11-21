"""Polite reader for public Reddit JSON listings and their top comments.

Reddit's public JSON endpoints do not need an API key. This client stays slow on purpose:
one request at a time, a pause between calls, and a single retry when Reddit asks us to wait.
"""

import time
from dataclasses import dataclass

import httpx

USER_AGENT = (
    "autonomous-merchandise-discovery/0.1 "
    "(die-cut sticker research; +https://github.com/planetopus/Autonomous-Merchandise-Discovery-MVP)"
)


@dataclass(frozen=True)
class RedditComment:
    """One public comment the merchandise writer is allowed to quote."""

    body: str
    url: str
    score: int
    post_title: str


class RedditReader:
    """Fetch a few top comments for a query without bursting Reddit's public endpoints."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        min_interval_seconds: float = 2.0,
        sleep=time.sleep,
        clock=time.monotonic,
        post_limit: int = 3,
        comments_per_post: int = 6,
    ):
        self._client = client
        self._min_interval = min_interval_seconds
        self._sleep = sleep
        self._clock = clock
        self._post_limit = post_limit
        self._comments_per_post = comments_per_post
        self._last_request_at: float | None = None

    def collect(self, query: str) -> list[RedditComment]:
        """Return top comments for the query, or an empty list when Reddit has nothing usable."""

        client = self._client or httpx.Client(
            timeout=20.0,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        owns_client = self._client is None
        try:
            listing = self._get(
                client,
                "https://www.reddit.com/search.json",
                {"q": query, "sort": "relevance", "type": "link", "limit": self._post_limit},
            )
            posts = _posts(listing)[: self._post_limit]
            comments: list[RedditComment] = []
            for post in posts:
                payload = self._get(
                    client,
                    f"https://www.reddit.com/comments/{post['id']}.json",
                    {"sort": "top", "limit": self._comments_per_post + 2},
                )
                comments.extend(
                    _comments(payload, post["title"], post["permalink"])[: self._comments_per_post]
                )
            comments.sort(key=lambda item: item.score, reverse=True)
            return comments
        finally:
            if owns_client:
                client.close()

    def _get(self, client: httpx.Client, url: str, params: dict) -> dict | list:
        """Perform one GET, waiting out the local interval and one Reddit 429."""

        self._wait_turn()
        response = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        self._last_request_at = self._clock()
        if response.status_code == 429:
            retry_after = _retry_after_seconds(response.headers)
            self._sleep(retry_after)
            self._last_request_at = self._clock()
            response = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
            self._last_request_at = self._clock()
        if response.status_code >= 400:
            raise RuntimeError(f"Reddit request failed with status {response.status_code}.")
        return response.json()

    def _wait_turn(self) -> None:
        """Sleep until the minimum gap since the previous request has elapsed."""

        if self._last_request_at is None:
            return
        remaining = self._min_interval - (self._clock() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)


def _retry_after_seconds(headers) -> float:
    """Read Retry-After and cap it so a hostile value cannot stall the stage."""

    try:
        requested = float(headers.get("Retry-After", "2"))
    except (TypeError, ValueError):
        requested = 2.0
    return max(0.0, min(requested, 10.0))


def _posts(payload: dict | list) -> list[dict]:
    """Pull non-stickied link posts out of a Reddit listing."""

    children = _children(payload)
    posts = []
    for child in children:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict) or data.get("stickied"):
            continue
        post_id = str(data.get("id") or "")
        permalink = str(data.get("permalink") or "")
        if not post_id or not permalink:
            continue
        posts.append(
            {
                "id": post_id,
                "title": str(data.get("title") or "Reddit post"),
                "permalink": permalink,
                "score": int(data.get("score") or 0),
            }
        )
    posts.sort(key=lambda item: item["score"], reverse=True)
    return posts


def _comments(payload: dict | list, post_title: str, permalink: str) -> list[RedditComment]:
    """Pull top-level comments from a comments JSON response."""

    listings = payload if isinstance(payload, list) else [payload]
    comment_listing = listings[1] if len(listings) > 1 else {"data": {"children": []}}
    comments: list[RedditComment] = []
    for child in _children(comment_listing):
        if child.get("kind") not in {None, "t1"}:
            continue
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        author = str(data.get("author") or "")
        body = " ".join(str(data.get("body") or "").split())
        if author in {"AutoModerator", "[deleted]"} or body in {"", "[deleted]", "[removed]"}:
            continue
        if len(body) < 20:
            continue
        comment_permalink = str(data.get("permalink") or permalink)
        url = comment_permalink if comment_permalink.startswith("http") else f"https://www.reddit.com{comment_permalink}"
        comments.append(
            RedditComment(
                body=body[:500],
                url=url,
                score=int(data.get("score") or 0),
                post_title=post_title,
            )
        )
    comments.sort(key=lambda item: item.score, reverse=True)
    return comments


def _children(payload: dict | list) -> list:
    """Return the listing children, or nothing when the payload is not a listing."""

    if isinstance(payload, list):
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    children = data.get("children") if isinstance(data, dict) else None
    return children if isinstance(children, list) else []
