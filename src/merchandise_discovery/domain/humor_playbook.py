"""Hand-authored joke shapes for the writer.

Selling lines in the market CSV are not examples and do not set these weights.
`data/humor_playbook.json` is a snapshot a nightly job can regenerate.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


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
# These stay in a trimmed prompt. The few-shot lines live in pun_examples_block.
_PINNED_SHAPE_IDS = (
    "clarity_beats_cleverness",
    "absurd_identity_stack",
    "wordplay_pun",
    "image_pun",
    "celebrity_food_pun",
    "brand_logo_spoof",
    "innocent_image_innuendo",
    "cute_but_menacing",
    "dark_twist_scene",
    "catchphrase_flip",
    "relatable_confession_action",
    "pop_culture_quote_flip",
    "historical_name_pun",
    "fake_acronym_org",
    "fake_warning_sign",
    "slogan_twist",
    "rhyme_innuendo",
    "holiday_pun",
)

PRIORITY_PATTERNS = [
    {
        "id": "clarity_beats_cleverness",
        "label": "Clarity beats cleverness",
        "guidance": (
            "A line must be instantly understood in under 2 seconds. "
            "Abstract or long compound club names are penalized. "
            "If a stranger needs the backstory, the line fails."
        ),
    },
    {
        "id": "absurd_identity_stack",
        "label": "Absurd identity stack",
        "guidance": (
            "A sincere club name for a real group whose traits co-occur. ALL CAPS, "
            "6 words maximum, in a younger register that group would not use about "
            "themselves. A long literal list of duties is not this pattern. Keep it "
            "wholesome enough that a member would buy it. At least two lines use it."
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
        "id": "wordplay_pun",
        "label": "Word pun",
        "guidance": (
            "A double meaning or sound-alike the target group gets in 2 seconds. "
            "The picture completes the second meaning. About 30 to 40 percent of "
            "the batch is a pun or spoof in this family."
        ),
    },
    {
        "id": "image_pun",
        "label": "Image pun",
        "guidance": (
            "The picture carries the joke and the words only set it up. "
            "A literal illustration of the words is not this shape."
        ),
    },
    {
        "id": "celebrity_food_pun",
        "label": "Celebrity food pun",
        "guidance": (
            "A food renamed as a celebrity. The picture is that food wearing the "
            "celebrity's look. Format is often a bold text stack."
        ),
    },
    {
        "id": "brand_logo_spoof",
        "label": "Brand logo spoof",
        "guidance": (
            "A famous logo layout whose ring text flips the brand. Format is logo spoof. "
            "Parody is allowed."
        ),
    },
    {
        "id": "innocent_image_innuendo",
        "label": "Innocent image innuendo",
        "guidance": (
            "The words sound adult and the picture reveals the innocent object, or the "
            "object makes the innuendo land. Mild crude humor is allowed. "
            "Retro sunset badges are a common format."
        ),
    },
    {
        "id": "cute_but_menacing",
        "label": "Cute but menacing",
        "guidance": (
            "A cute character doing something threatening. The picture flips the sweetness. "
            "A circle badge is a common format."
        ),
    },
    {
        "id": "dark_twist_scene",
        "label": "Dark twist scene",
        "guidance": (
            "A wholesome outdoor scene whose caption turns dark. "
            "Often a retro sunset badge. The scene completes the threat."
        ),
    },
    {
        "id": "catchphrase_flip",
        "label": "Catchphrase flip",
        "guidance": (
            "A known phrase, then a second line that overturns it. "
            "Often a circle warning badge. The picture shows the flip."
        ),
    },
    {
        "id": "relatable_confession_action",
        "label": "Relatable confession action",
        "guidance": (
            "A blunt confession. The picture shows the action in progress, "
            "not a portrait that only restates the words."
        ),
    },
    {
        "id": "pop_culture_quote_flip",
        "label": "Pop culture quote flip",
        "guidance": (
            "A famous catchphrase that answers or stalls itself. The picture is the "
            "character or the world the quote came from, and it has to finish the flip."
        ),
    },
    {
        "id": "historical_name_pun",
        "label": "Historical name pun",
        "guidance": (
            "A historical name respelled as the joke. The portrait wears the pun: "
            "costume, prop, and expression have to make the second reading obvious."
        ),
    },
    {
        "id": "fake_acronym_org",
        "label": "Fake acronym organization",
        "guidance": (
            "A parody of a real organization's initials. Format is a plain plaque. "
            "The letters spell the joke. The plaque makes it look official."
        ),
    },
    {
        "id": "slogan_twist",
        "label": "Slogan twist",
        "guidance": (
            "A civic or product slogan turned to the opposite advice. "
            "Format is often a bumper sticker strip. The picture shows the twist."
        ),
    },
    {
        "id": "rhyme_innuendo",
        "label": "Rhyme innuendo",
        "guidance": (
            "Two rhyming objects, one of them rude. Draw both icons into the lettering. "
            "The rhyme is not enough if the picture does not show both things."
        ),
    },
    {
        "id": "holiday_pun",
        "label": "Holiday pun",
        "guidance": (
            "A holiday word with a second everyday meaning. The costume or prop "
            "has to make that second reading obvious. A cute seasonal character is enough."
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
        "id": "competence_vs_tiny_fear",
        "label": "Competence versus a tiny fear",
        "guidance": (
            "A joke shape, not a topic. High competence in a big crisis, then panic "
            "over a tiny thing. Fill it with whatever identity is chosen, including "
            "ones that have not been used yet."
        ),
    },
    {
        "id": "identity_plus_vivid_habit",
        "label": "Identity plus a vivid habit",
        "guidance": (
            "A joke shape, not a topic. One real identity plus one vivid specific habit. "
            "Do not reuse dads, nurses, or morticians just because a rating used them."
        ),
    },
    {
        "id": "elders_in_younger_slang",
        "label": "Older group in younger slang",
        "guidance": (
            "A joke shape, not a topic. An older group using a younger generation's slang. "
            "Apply it across the atlas, not only to the people in the example lines."
        ),
    },
    {
        "id": "gen_z_slang_mismatch",
        "label": "Gen Z slang on the wrong group",
        "guidance": (
            "A joke shape, not a topic. Put Gen Z slang on a real group that does not "
            "talk that way. Words such as big back, rizz, era, and crash out are the "
            "device. Fill the shape with identities across the atlas, not only the "
            "groups in the ratings."
        ),
    },
    {
        "id": "polite_excuse_quotes",
        "label": "Quotes around a polite excuse",
        "guidance": (
            "A joke shape, not a topic. Put quotation marks around the polite word the "
            "group uses to excuse the habit, such as test. The excuse is the turn. "
            "Use it for any identity, not only the one in the example."
        ),
    },
    {
        "id": "parenthetical_twist",
        "label": "Parenthetical twist",
        "guidance": (
            "A joke shape, not a topic. End the line with a parenthetical that flips "
            "the boast, such as against his will or damaged. The aside is the joke. "
            "Apply it across identities instead of repeating the sample groups."
        ),
    },
    {
        "id": "fake_warning_sign",
        "label": "Fake warning sign",
        "guidance": (
            "A fake official warning. Either a personality treated as a hazard, "
            "or a standard warning pictogram whose picture is the punchline. "
            "Format is warning sign."
        ),
    },
]


def build_playbook(references: list | None = None) -> dict:
    """Hand-authored joke shapes. Selling lines are not examples and do not set weights."""

    # The sales CSV used to weight these shapes. Funniness now comes from the humor lab.
    _ = references
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
        {"source": "hand-authored shapes", "patterns": priority}
    ).model_dump()


def playbook_prompt(playbook: dict, *, limit: int | None = None) -> str:
    """Tell the writer which shapes earned the upvotes, without offering lines to copy."""

    patterns = playbook.get("patterns") or []
    if not patterns:
        return ""
    lines = [
        (
            "Lesson: clarity beats cleverness. A line must be instantly understood "
            "in under 2 seconds. Abstract or long compound club names are penalized. "
            "Humor playbook. These are structures, not lines to copy. "
            "Do not reuse any existing sticker slogan. "
            "Set each candidate's pattern to one of these ids. "
            "At least two candidates must use absurd_identity_stack. "
            "An identity stack names a real group whose traits co-occur, in a register "
            "that group would not use about themselves, and stays wholesome enough to buy. "
            "A generational or register mismatch is a key comedy lever. "
            "Never stack unrelated words just because they sound odd. "
            "About 30 to 40 percent of candidates are puns or spoofs. "
            "Each one is a word-and-image pair. Set format to the layout, such as "
            "retro sunset badge, logo spoof, circle badge, bold text stack, "
            "bumper sticker strip, warning sign, plaque, or oval outdoor badge."
        )
    ]
    priority = [item for item in patterns if item.get("priority")]
    learned = [item for item in patterns if not item.get("priority")]
    if limit is not None:
        by_id: dict = {}
        for item in priority:
            by_id.setdefault(item.get("id"), item)
        pinned = [by_id[name] for name in _PINNED_SHAPE_IDS if name in by_id]
        pinned_ids = {item.get("id") for item in pinned}
        others = [item for item in priority if item.get("id") not in pinned_ids]
        priority = pinned + others[:limit]
        learned = learned[: max(0, limit - len(priority))]
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


def write_playbook(references: list | None, path: Path) -> dict:
    """Write the nightly snapshot. The run itself does not call this."""

    playbook = build_playbook(references)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(playbook, indent=2) + "\n", encoding="utf-8")
    return playbook
