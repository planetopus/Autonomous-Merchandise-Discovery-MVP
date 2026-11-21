"""Optional humor-lab files written by a separate job.

Nothing here is required. When data/humor_lab/ exists, the engine uses
playbook.json, niche_pairs.json, gold_lines.json, and critic_rubric.md.
Missing files leave the built-in playbook, pair request, and critic unchanged.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from merchandise_discovery.infrastructure.humor_reference_loader import humor_csv_search_starts


@dataclass
class HumorLab:
    """Files the humor lab has published, or empty stand-ins when it has not."""

    playbook: dict | None = None
    niche_pairs: list[dict] = field(default_factory=list)
    gold_lines: list[str] = field(default_factory=list)
    rubric: str = ""


def find_humor_lab_dir(starts: list[Path] | None = None) -> Path | None:
    """Find data/humor_lab by walking up from the app, the package, and the working directory."""

    seen: set[str] = set()
    for start in starts if starts is not None else humor_csv_search_starts():
        current = start if start.is_dir() else start.parent
        for _ in range(10):
            key = str(current)
            if key in seen:
                break
            seen.add(key)
            candidate = current / "data" / "humor_lab"
            if candidate.is_dir() and any(candidate.iterdir()):
                return candidate
            if current.parent == current:
                break
            current = current.parent
    return None


def load_humor_lab(directory: Path | None = None) -> HumorLab:
    """Read the lab directory when it exists. A missing directory is an empty lab."""

    folder = directory if directory is not None else find_humor_lab_dir()
    if folder is None or not folder.is_dir():
        return HumorLab()
    return HumorLab(
        playbook=_read_playbook(folder / "playbook.json"),
        niche_pairs=_read_pairs(folder / "niche_pairs.json"),
        gold_lines=_read_gold_lines(folder / "gold_lines.json"),
        rubric=_read_text(folder / "critic_rubric.md"),
    )


def merge_lab_playbook(built: dict, lab_playbook: dict | None) -> dict:
    """Let a published playbook override matching shapes and add any new ones first."""

    if not lab_playbook:
        return built
    incoming = [_normalize_pattern(item) for item in lab_playbook.get("patterns") or []]
    incoming = [item for item in incoming if item["id"]]
    if not incoming:
        return built
    by_id = {item["id"]: dict(item) for item in built.get("patterns") or []}
    front: list[dict] = []
    for item in incoming:
        current = by_id.get(item["id"])
        if current is None:
            front.append(item)
            continue
        for key, value in item.items():
            if value not in (None, "", []):
                current[key] = value
        by_id[item["id"]] = current
    ordered: list[dict] = []
    seen: set[str] = set()
    for item in front + list(built.get("patterns") or []):
        current = by_id.get(item["id"], item)
        if current["id"] in seen:
            continue
        seen.add(current["id"])
        ordered.append(current)
    return {**built, "patterns": ordered}


def gold_lines_block(lines: list[str]) -> str:
    """Few-shot style examples. The writer is told not to emit them."""

    cleaned = [line.strip() for line in lines if line and line.strip()]
    if not cleaned:
        return ""
    samples = "\n".join(f"- {line}" for line in cleaned[:12])
    return (
        "Humor-lab style examples. Learn the voice and the shape. "
        "Never output these lines or a close paraphrase.\n"
        f"{samples}\n"
    )


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _read_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_playbook(path: Path) -> dict | None:
    payload = _read_json(path)
    if isinstance(payload, dict) and isinstance(payload.get("patterns"), list):
        return payload
    if isinstance(payload, list):
        return {"patterns": payload}
    return None


def _read_pairs(path: Path) -> list[dict]:
    payload = _read_json(path)
    rows = payload.get("pairs") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    pairs = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        first = str(item.get("niche_a") or item.get("a") or "").strip()
        second = str(item.get("niche_b") or item.get("b") or "").strip()
        if not first or not second:
            continue
        pairs.append({"niche_a": first, "niche_b": second})
    return pairs[:12]


def _read_gold_lines(path: Path) -> list[str]:
    payload = _read_json(path)
    rows = payload.get("lines") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    lines = []
    for item in rows:
        if isinstance(item, str) and item.strip():
            lines.append(item.strip())
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("line") or "").strip()
            if text:
                lines.append(text)
    return lines[:12]


def _normalize_pattern(item: dict) -> dict:
    return {
        "id": str(item.get("id") or "").strip(),
        "label": str(item.get("label") or item.get("id") or "").strip(),
        "guidance": str(item.get("guidance") or "").strip(),
        "weight": item.get("weight"),
        "priority": bool(item.get("priority", True)),
        "examples": [
            str(example)
            for example in (item.get("examples") or [])
            if str(example).strip()
        ][:2],
    }
