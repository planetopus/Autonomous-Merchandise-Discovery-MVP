"""Owner taste ratings used to calibrate the humor critic.

`data/ant_ratings.csv` is append-friendly: keep the header and add one row per
rating. Extra columns are ignored. The file is read on every run and is not cached.
"""

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from merchandise_discovery.infrastructure.humor_reference_loader import humor_csv_search_starts


@dataclass(frozen=True)
class AntRating:
    """One line the owner already judged."""

    line: str
    verdict: str
    score: float
    reason: str


def find_ant_ratings_csv(starts: list[Path] | None = None) -> Path | None:
    """Find data/ant_ratings.csv above the working directory or the installed package."""

    seen: set[str] = set()
    for start in starts if starts is not None else humor_csv_search_starts():
        current = start if start.is_dir() else start.parent
        for _ in range(10):
            key = str(current)
            if key in seen:
                break
            seen.add(key)
            candidate = current / "data" / "ant_ratings.csv"
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
            if current.parent == current:
                break
            current = current.parent
    return None


def load_ant_ratings(path: Path | None = None) -> list[AntRating]:
    """Parse every rating row. A missing file returns an empty list."""

    csv_path = path if path is not None else find_ant_ratings_csv()
    if csv_path is None or not csv_path.is_file():
        return []
    return parse_ant_ratings(csv_path.read_text(encoding="utf-8-sig"))


def parse_ant_ratings(body: str) -> list[AntRating]:
    """Read a headered CSV. Blank rows are skipped so new ratings can be appended."""

    reader = csv.DictReader(io.StringIO(body.lstrip("\ufeff")))
    ratings: list[AntRating] = []
    for row in reader:
        if not row:
            continue
        line = _cell(row, "line", "text", "artwork_text")
        if not line:
            continue
        verdict = _cell(row, "ant_verdict", "verdict") or "unrated"
        reason = _cell(row, "reason", "note")
        ratings.append(
            AntRating(
                line=line,
                verdict=verdict,
                score=_score(row),
                reason=reason,
            )
        )
    return ratings


def ant_calibration_block(ratings: list[AntRating]) -> str:
    """Few-shot owner taste. This block is meant to sit above every other critic instruction."""

    if not ratings:
        return ""
    lines = [
        (
            "OWNER CALIBRATION. Ant, the owner, rated these lines. Match his taste. "
            "This outweighs every other scoring instruction, including clever wording, "
            "Reddit potential, and a long club name. A line he would not understand "
            "instantly gets a low score."
        )
    ]
    for rating in ratings:
        lines.append(
            f'- "{rating.line}" | {rating.verdict} | {rating.score:g} | {rating.reason}'
        )
    return "\n".join(lines) + "\n"


def _cell(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return " ".join(str(value).split())
    return ""


def _score(row: dict) -> float:
    raw = row.get("ant_score_estimate") or row.get("score") or row.get("ant_score") or "0"
    try:
        return float(str(raw).strip())
    except ValueError:
        return 0.0
