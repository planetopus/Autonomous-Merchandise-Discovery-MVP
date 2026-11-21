"""Reddit comment reader with official OAuth and a public JSON fallback.

When a client id and secret are configured, requests use the app-only client-credentials
flow against oauth.reddit.com and back off from the X-Ratelimit headers. Without those
credentials the same comment parsing runs against the public www.reddit.com JSON endpoints.
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
    """Fetch a few top comments for a query without bursting Reddit."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str | None = None,
        min_interval_seconds: float = 2.0,
        sleep=time.sleep,
        clock=time.monotonic,
        post_limit: int = 3,
        comments_per_post: int = 6,
    ):
        self._client = client
        self._client_id = (client_id or "").strip() or None
        self._client_secret = (client_secret or "").strip() or None
        self._user_agent = (user_agent or "").strip() or USER_AGENT
        self._min_interval = min_interval_seconds
        self._sleep = sleep
        self._clock = clock
        self._post_limit = post_limit
        self._comments_per_post = comments_per_post
        self._last_request_at: float | None = None
        self._access_token: str | None = None
        self._token_deadline = 0.0

    @property
    def uses_oauth(self) -> bool:
        """Official API mode requires both the client id and the client secret."""

        return bool(self._client_id and self._client_secret)

    def collect(self, query: str) -> list[RedditComment]:
        """Return top comments for the query, or an empty list when Reddit has nothing usable."""

        client = self._client or httpx.Client(timeout=20.0, follow_redirects=True)
        owns_client = self._client is None
        try:
            if self.uses_oauth:
                search_url = "https://oauth.reddit.com/search"
                comments_url = "https://oauth.reddit.com/comments/{post_id}"
            else:
                search_url = "https://www.reddit.com/search.json"
                comments_url = "https://www.reddit.com/comments/{post_id}.json"
            listing = self._get(
                client,
                search_url,
                {"q": query, "sort": "relevance", "type": "link", "limit": self._post_limit},
            )
            posts = _posts(listing)[: self._post_limit]
            comments: list[RedditComment] = []
            for post in posts:
                payload = self._get(
                    client,
                    comments_url.format(post_id=post["id"]),
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
        """Perform one GET, waiting out the local interval, a 429, and a drained rate window."""

        headers = self._request_headers(client)
        self._wait_turn()
        response = client.get(url, params=params, headers=headers)
        self._last_request_at = self._clock()
        self._backoff_if_rate_limited(response.headers)
        if response.status_code == 429:
            self._sleep(_retry_after_seconds(response.headers))
            self._last_request_at = self._clock()
            response = client.get(url, params=params, headers=headers)
            self._last_request_at = self._clock()
            self._backoff_if_rate_limited(response.headers)
        if response.status_code >= 400:
            raise RuntimeError(f"Reddit request failed with status {response.status_code}.")
        return response.json()

    def _request_headers(self, client: httpx.Client) -> dict[str, str]:
        """Build the User-Agent header and, in OAuth mode, a bearer token."""

        headers = {"User-Agent": self._user_agent}
        if not self.uses_oauth:
            return headers
        headers["Authorization"] = f"Bearer {self._access_token_value(client)}"
        return headers

    def _access_token_value(self, client: httpx.Client) -> str:
        """Return a cached app-only token, refreshing it with client credentials."""

        if self._access_token and self._clock() < self._token_deadline:
            return self._access_token
        self._wait_turn()
        response = client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(self._client_id or "", self._client_secret or ""),
            headers={"User-Agent": self._user_agent},
        )
        self._last_request_at = self._clock()
        self._backoff_if_rate_limited(response.headers)
        if response.status_code >= 400:
            raise RuntimeError(f"Reddit token request failed with status {response.status_code}.")
        payload = response.json()
        token = str(payload.get("access_token") or "")
        if not token:
            raise RuntimeError("Reddit token response did not include an access token.")
        try:
            expires_in = float(payload.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_in = 3600.0
        self._access_token = token
        self._token_deadline = self._clock() + max(30.0, expires_in - 30.0)
        return token

    def _backoff_if_rate_limited(self, headers) -> None:
        """Sleep out the official window when X-Ratelimit-Remaining is exhausted."""

        remaining = _header_float(headers, "X-Ratelimit-Remaining")
        reset = _header_float(headers, "X-Ratelimit-Reset")
        if remaining is None or remaining >= 1 or reset is None:
            return
        self._sleep(max(0.0, min(reset, 60.0)))
        self._last_request_at = self._clock()

    def _wait_turn(self) -> None:
        """Sleep until the minimum gap since the previous request has elapsed."""

        if self._last_request_at is None:
            return
        remaining = self._min_interval - (self._clock() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)


def _header_float(headers, name: str) -> float | None:
    """Read one numeric Reddit header without failing the request when it is absent."""

    if headers is None:
        return None
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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
