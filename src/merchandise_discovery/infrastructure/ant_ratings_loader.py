"""Owner taste ratings used to calibrate the humor critic.

`data/ant_ratings.csv` is append-friendly: keep the header and add one row per
rating. Extra columns are ignored. The file is read on every run and is not cached.
"""

import csv
import io
import random
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


def sample_ant_ratings(
    ratings: list[AntRating],
    *,
    high: int = 4,
    low: int = 4,
    rng: random.Random | None = None,
) -> list[AntRating]:
    """A few top and bottom anchors. Mid scores stay out of the prompt."""

    chooser = rng or random.Random()
    highs = [item for item in ratings if item.score >= 8]
    lows = [item for item in ratings if item.score <= 3]

    def take(pool: list[AntRating], count: int) -> list[AntRating]:
        if len(pool) <= count:
            return list(pool)
        return chooser.sample(pool, count)

    chosen = take(highs, high) + take(lows, low)
    chosen.sort(key=lambda item: (-item.score, item.line.casefold()))
    return chosen


def style_examples_block(
    ratings: list[AntRating],
    *,
    limit: int = 8,
    rng: random.Random | None = None,
) -> str:
    """Top-rated lines as style, not text to copy. Shapes a through d plus sarcasm."""

    pool = [item for item in ratings if item.score >= 7]
    if not pool:
        return ""
    chooser = rng or random.Random()
    chosen = pool if len(pool) <= limit else chooser.sample(pool, limit)
    chosen.sort(key=lambda item: (-item.score, item.line.casefold()))
    samples = "\n".join(f"- {item.line}" for item in chosen)
    return (
        "Style examples from lines that already worked. Learn the shape. "
        "Never copy a line or a close paraphrase.\n"
        f"{samples}\n"
        "Spread the batch across these shapes: "
        "(a) a CAPS identity stack of 2 or 3 traits that co-occur in one real person; "
        "(b) high competence versus a tiny fear; "
        "(c) a fake WARNING or NOTICE sign; "
        "(d) a deadpan dark one-liner; "
        "plus sarcastic or ironic one-liners. "
        "Do not write a behavior paragraph, a job procedure, or a scenario about two groups meeting.\n"
    )


def ant_calibration_block(ratings: list[AntRating]) -> str:
    """Few-shot owner taste. This block is meant to sit above every other critic instruction."""

    if not ratings:
        return ""
    lines = [
        (
            "OWNER CALIBRATION. These scores are not one person's taste. "
            "They record whether the target group and most people would find the line funny. "
            "This outweighs every other scoring instruction. "
            "The catalog should cover every kind of person. "
            "Reuse joke shapes. Do not cluster on the example identities, and do not "
            "give dads, nurses, or morticians extra weight. "
            "Liked shapes: high competence in a big crisis versus panic over a tiny thing; "
            "a real identity plus one vivid habit; an older group using younger slang; "
            "Gen Z slang on a group that does not talk that way; "
            "quotation marks around a polite excuse; "
            "a parenthetical twist at the end. "
            "Disliked: vague sigma with no vivid detail, tired ex jokes, weak comparisons, "
            "and a line that only describes the behavior with no ironic twist. "
            "A behavior description with no twist scores under 7. "
            "Insider jargon a random adult would not know scores at most 5. "
            "A universal hook, such as Karen or printer hell, can still be kind of funny "
            "inside a niche. "
            "A single tired trope scores at most 6 unless it stacks a second identity "
            "or a fresh twist. Stacking 2 or 3 traits is the original shape and should "
            "score higher. "
            "The template 'X is [adj]. My Y isn't.' scores at most 5 unless both halves "
            "are concrete and surprising. "
            "Does every word earn its place in the joke? Outside or common words are "
            "allowed when everyone knows them and they serve the setup or the punchline. "
            "Random filler disconnected from the joke scores at most 4."
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
