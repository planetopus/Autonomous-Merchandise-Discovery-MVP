"""Load humor references from the CSV, then add any optional Mongo rows.

The committed file is the source the sync can update. Each run fetches that CSV
again from HUMOR_REFERENCE_CSV_URL, or from the raw GitHub URL of the file on
main, and uses the copy in the repo when the fetch fails. Mongo is only an extra.
"""

import csv
import io
import logging
import sys
from pathlib import Path

import httpx

from merchandise_discovery.domain.humor_references import (
    HumorReference,
    HumorReferenceLoadError,
    humor_reference_id,
    text_is_theme,
)
from merchandise_discovery.infrastructure.mongo.repositories.humor_reference_repository import (
    HumorReferenceRepository,
)

logger = logging.getLogger(__name__)

DEFAULT_HUMOR_REFERENCE_CSV_URL = (
    "https://raw.githubusercontent.com/planetopus/"
    "Autonomous-Merchandise-Discovery-MVP/main/data/humor_references.csv"
)
CSV_FETCH_TIMEOUT_SECONDS = 5.0


def humor_csv_search_starts() -> list[Path]:
    """Directories to walk: this file, the process cwd, and the Streamlit script."""

    starts = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    if main:
        starts.append(Path(main).resolve().parent)
    return starts


def find_humor_reference_csv(starts: list[Path] | None = None) -> Path | None:
    """Find data/humor_references.csv above the working directory or the installed package.

    Streamlit may start in the app folder, and an installed package lives under
    site-packages. Walking upward finds the repo copy either way. Nothing is cached.
    """

    seen: set[str] = set()
    for start in starts if starts is not None else humor_csv_search_starts():
        current = start if start.is_dir() else start.parent
        for _ in range(10):
            key = str(current)
            if key in seen:
                break
            seen.add(key)
            candidate = current / "data" / "humor_references.csv"
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
            if current.parent == current:
                break
            current = current.parent
    return None


def bundled_humor_reference_csv() -> Path:
    """Return the repo copy of the humor CSV, searching upward from likely roots."""

    found = find_humor_reference_csv()
    if found is not None:
        return found
    return Path.cwd() / "data" / "humor_references.csv"


def load_fresh_humor_references(
    repository: HumorReferenceRepository | None = None,
    csv_url: str | None = None,
    *,
    http_get=None,
    bundled_path: Path | None = None,
) -> list[HumorReference]:
    """Fetch the CSV for this run, then append optional Mongo rows that are not already in it.

    Nothing here is cached. Each run calls this again.
    """

    url = (csv_url or "").strip() or DEFAULT_HUMOR_REFERENCE_CSV_URL
    rows: list[HumorReference] = []
    try:
        rows = load_humor_references_csv(url, http_get=http_get)
    except (OSError, httpx.HTTPError, ValueError, csv.Error) as error:
        logger.warning("Humor reference CSV fetch failed (%s); using the bundled file.", type(error).__name__)
    if not rows:
        rows = _read_bundled_csv(bundled_path)
    if not rows:
        raise HumorReferenceLoadError(
            "Market references loaded 0 rows. "
            f"The fetch of {url} returned no selling concepts, and data/humor_references.csv "
            f"was not found above the working directory ({Path.cwd()}). "
            "This run stopped instead of skipping the critic."
        )
    if repository is None:
        return rows
    try:
        extras = repository.list_all()
    except Exception as error:  # noqa: BLE001 - Mongo is optional and must not abort the run.
        logger.warning("Optional humor reference collection was skipped (%s).", type(error).__name__)
        return rows
    return _merge_extra(rows, extras)


def load_humor_references_csv(url: str, *, http_get=None) -> list[HumorReference]:
    """Download and parse one humor-reference CSV."""

    getter = http_get or _default_get
    return parse_humor_reference_csv(getter(url))


_TEXT_KEYS = ("sticker_text_or_idea", "text", "concept", "line", "title", "wording")
_NICHE_KEYS = ("niche", "identity", "identities", "audience")
_THEME_KEYS = ("theme", "themes", "topic")
_HOOK_KEYS = ("hook", "hooks")
_DEMAND_KEYS = ("demand", "sales", "units_sold", "units", "sold", "trend_score", "trend", "popularity")
_UPVOTE_KEYS = ("upvotes", "score", "votes")


def parse_humor_reference_csv(body: str) -> list[HumorReference]:
    """Parse CSV text. Unknown columns are ignored. A `(theme)` marker marks a theme row."""

    reader = csv.DictReader(io.StringIO(body.lstrip("\ufeff")))
    references: list[HumorReference] = []
    for raw in reader:
        row = {
            str(key).strip().casefold(): value
            for key, value in raw.items()
            if key is not None
        }
        text = _cell(row, _TEXT_KEYS)
        hook = _cell(row, _HOOK_KEYS)
        theme = _cell(row, _THEME_KEYS)
        if not text:
            text = hook or theme
        if not text:
            continue
        kind = _cell(row, ("row_type", "kind", "type")).casefold()
        references.append(
            HumorReference(
                text=text,
                upvotes=_csv_int(_cell(row, _UPVOTE_KEYS)),
                humor_type=_cell(row, ("humor_type",)),
                niche=_cell(row, _NICHE_KEYS),
                subreddit=_cell(row, ("subreddit", "source", "marketplace")),
                post_url=_cell(row, ("post_url", "url")),
                date_found=_cell(row, ("date_found", "date")),
                is_theme=text_is_theme(text, kind in {"theme", "topic"}),
                reference_id=humor_reference_id(text),
                hook=hook,
                theme=theme,
                sales=_csv_int(_cell(row, ("sales", "units_sold", "units", "sold"))),
                demand=_csv_int(_cell(row, _DEMAND_KEYS)) or _csv_int(_cell(row, _UPVOTE_KEYS)),
            )
        )
    return references


def _cell(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return " ".join(str(value).split())
    return ""


def _read_bundled_csv(bundled_path: Path | None) -> list[HumorReference]:
    """Read the committed CSV after a remote fetch fails or returns no rows."""

    if bundled_path is not None:
        path = bundled_path
    else:
        path = find_humor_reference_csv()
    if path is None or not path.is_file():
        return []
    return parse_humor_reference_csv(path.read_text(encoding="utf-8-sig"))


def _merge_extra(primary: list[HumorReference], extras: list[HumorReference]) -> list[HumorReference]:
    """Keep CSV rows first and append Mongo rows whose text hash is not already present."""

    seen = {item.reference_id or humor_reference_id(item.text) for item in primary}
    merged = list(primary)
    for item in extras:
        identity = item.reference_id or humor_reference_id(item.text)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(item)
    return merged


def _default_get(url: str) -> str:
    """Download one CSV with a short timeout so a slow host cannot stall run start."""

    response = httpx.get(url, timeout=CSV_FETCH_TIMEOUT_SECONDS, follow_redirects=True)
    response.raise_for_status()
    return response.text


def _csv_int(value: object) -> int:
    """Accept blank or non-numeric upvote cells as zero."""

    try:
        return int(float(str(value or "0").replace(",", "").strip() or "0"))
    except ValueError:
        return 0
