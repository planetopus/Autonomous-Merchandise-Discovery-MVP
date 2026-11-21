"""Turn the humor CSV into weighted joke patterns.

The patterns are structure guidance for the writer. Example lines show the shape
and are not text to copy. `data/humor_playbook.json` is the snapshot a nightly
job can regenerate; a run builds the same object from the rows it just loaded
and does not cache it.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from merchandise_discovery.domain.humor_references import HumorReference


class HumorPlaybookPattern(BaseModel):
    """One joke shape. Examples are optional and are never required slogans."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    guidance: str
    weight: int | None = None
    priority: bool = False
    examples: list[str] = Field(default_factory=list)


class HumorPlaybook(BaseModel):
    """The stored playbook. Strict so a nightly file can also be a response schema."""

    model_config = ConfigDict(extra="forbid")

    source: str
    patterns: list[HumorPlaybookPattern]

# Hand-authored shapes. Guidance only: do not store sample slogans here.
PRIORITY_PATTERNS = [
    {
        "id": "absurd_identity_stack",
        "label": "Absurd identity stack",
        "guidance": (
            "A sincere club or bumper-sticker name for a REAL group whose traits "
            "genuinely co-occur. Build it from this run's two niches, not from a random "
            "combo. Name that group in a younger generation's words or habits they would "
            "not use about themselves, and keep the line wholesome enough that a member "
            "thinks 'that's me' and would buy it. This is the top pattern. At least two "
            "lines in the batch use it."
        ),
    },
    {
        "id": "self_defeating_sign",
        "label": "Self-defeating sign",
        "guidance": (
            "A sign or notice whose instruction makes itself impossible to obey, "
            "said in a straight official voice."
        ),
    },
    {
        "id": "cheerful_dark_label",
        "label": "Cheerful dark label",
        "guidance": (
            "A bright, enthusiastic label for something bleak. Dark humor is welcome. "
            "The cheer is the joke."
        ),
    },
    {
        "id": "seasonal_character_trash_talk",
        "label": "Seasonal character trash talk",
        "guidance": (
            "A holiday or seasonal character is told off, as if they were crowding "
            "someone else's month or job."
        ),
    },
    {
        "id": "sensory_insult",
        "label": "Oddly specific sensory insult",
        "guidance": (
            "An insult that names one strangely precise smell, sound, or texture "
            "instead of a generic slur."
        ),
    },
    {
        "id": "dark_comparison",
        "label": "Relatable observation with a dark comparison",
        "guidance": (
            "A mundane observation, then a comparison that makes it suddenly bleak. "
            "The everyday half has to be recognizable."
        ),
    },
    {
        "id": "fake_warning_sign",
        "label": "Fake warning sign",
        "guidance": (
            "An official caution sign about a type of person, written as if the "
            "personality were a hazard."
        ),
    },
]


PATTERN_GUIDANCE = {
    "setup_turn": (
        "Setup then a turn",
        "An ordinary premise that snaps to an unexpected conclusion in the same line.",
    ),
    "confession": (
        "Confession",
        "A first-person admission that is the joke, not an explanation of the joke.",
    ),
    "deadpan_absurd": (
        "Deadpan absurd",
        "A flat statement of something impossible, said as if it were a normal fact.",
    ),
    "dark_turn": (
        "Dark turn",
        "A bleak or gallows turn that stays a joke. Dark humor is welcome.",
    ),
    "insider": (
        "Insider",
        "A line only people inside the niche recognize, with no glossary for outsiders.",
    ),
}


def classify_pattern(reference: HumorReference) -> str:
    """Map one upvoted line onto a single joke shape."""

    types = {part.strip().casefold() for part in reference.humor_type.split("/") if part.strip()}
    text = reference.text.strip()
    lowered = text.casefold()
    niche = reference.niche.strip().casefold()
    specific_niche = niche not in {"", "general"}
    if lowered.startswith(("i ", "i'", "i’m", "we ")):
        return "confession"
    if "dark" in types or "unhinged" in types:
        return "dark_turn"
    if specific_niche:
        return "insider"
    if "absurd" in types:
        return "deadpan_absurd"
    if "," in text or " is " in lowered:
        return "setup_turn"
    return "setup_turn"


def build_playbook(references: list[HumorReference]) -> dict:
    """Weight each pattern by the upvotes of the lines that use it."""

    grouped: dict[str, list[HumorReference]] = {key: [] for key in PATTERN_GUIDANCE}
    for reference in references:
        if reference.is_theme:
            continue
        grouped[classify_pattern(reference)].append(reference)
    patterns = []
    for key, (label, guidance) in PATTERN_GUIDANCE.items():
        rows = sorted(grouped[key], key=lambda item: (-item.upvotes, item.text.casefold()))
        if not rows:
            continue
        patterns.append(
            {
                "id": key,
                "label": label,
                "guidance": guidance,
                "weight": sum(item.upvotes for item in rows),
                "examples": [item.text for item in rows[:2]],
            }
        )
    patterns.sort(key=lambda item: (-item["weight"], item["id"]))
    priority = [
        {
            "id": item["id"],
            "label": item["label"],
            "guidance": item["guidance"],
            "weight": None,
            "priority": True,
            "examples": [],
        }
        for item in PRIORITY_PATTERNS
    ]
    return HumorPlaybook.model_validate(
        {"source": "data/humor_references.csv", "patterns": priority + patterns}
    ).model_dump()


def playbook_prompt(playbook: dict) -> str:
    """Tell the writer which shapes earned the upvotes, without offering lines to copy."""

    patterns = playbook.get("patterns") or []
    if not patterns:
        return ""
    lines = [
        (
            "Humor playbook. These are structures, not lines to copy. "
            "Do not reuse any existing sticker slogan. "
            "Set each candidate's pattern to one of these ids. "
            "At least two candidates must use absurd_identity_stack. "
            "An identity stack names a real group whose traits co-occur, in a register "
            "that group would not use about themselves, and stays wholesome enough to buy. "
            "A generational or register mismatch is a key comedy lever. "
            "Never stack unrelated words just because they sound odd."
        )
    ]
    priority = [item for item in patterns if item.get("priority")]
    learned = [item for item in patterns if not item.get("priority")]
    if priority:
        lines.append("High-priority shapes. There is no sample line; invent the shape:")
        for pattern in priority:
            lines.append(f"- {pattern['id']}: {pattern['label']}. {pattern['guidance']}")
    if learned:
        lines.append("Shapes weighted by upvotes. The samples show the shape only:")
        for pattern in learned[:5]:
            samples = " | ".join(pattern.get("examples") or [])
            lines.append(
                f"- {pattern['id']} (weight {pattern['weight']}): {pattern['guidance']} "
                f"Shape only, not lines to reuse: {samples}"
            )
    return "\n".join(lines) + "\n"


def write_playbook(references: list[HumorReference], path: Path) -> dict:
    """Write the nightly snapshot. The run itself does not call this."""

    playbook = build_playbook(references)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(playbook, indent=2) + "\n", encoding="utf-8")
    return playbook
