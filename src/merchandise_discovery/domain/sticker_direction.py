"""Shared die-cut vinyl sticker direction for copy, prompts, and avoid lists.

The shop sells kiss-cut vinyl stickers. Image models otherwise default to full-bleed
T-shirt and poster art, so every artwork prompt and every upstream style field should
ask for the same isolated sticker treatment.
"""

STICKER_AVOID = (
    "scene or landscape background",
    "full-bleed background",
    "realistic shading",
    "semi-realistic comic shading",
    "poster layout",
    "T-shirt or poster graphic",
    "navy or blue scene background",
)

STICKER_STYLE_DIRECTION = (
    "Flat vector die-cut vinyl sticker: bold clean outlines, flat colors, "
    "one centered isolated subject, plain white background, no realistic shading."
)


def sticker_copy_rules() -> str:
    """Return the merchandise-text contract for a sticker, not a shirt paragraph."""

    return (
        "Write die-cut vinyl sticker copy, not T-shirt or poster copy. Each merchandise "
        "line must be joke-shaped: a setup plus a turn, a one-line confession, or a deadpan "
        "absurd statement, about 4 to 14 words. A clever title or pun alone is rejected. "
        "A pun, spoof, or name swap of 2 to 8 words is the product when the picture "
        "completes the second meaning. "
        "artwork_text may be an empty string when the joke should be visual only. "
        "Empty artwork_text is valid and means the sticker has no text. "
        "The line must still make sense when read alone. Avoid generic achievement "
        "statements, broad labels, and slogans that could fit any audience."
    )


def sticker_visual_rules() -> str:
    """Return the style, artwork-prompt, and avoid-list contract for sticker art."""

    avoid = ", ".join(STICKER_AVOID)
    return (
        "The artwork_prompt and style_direction must describe a die-cut vinyl sticker: "
        "flat vector-style illustration, bold clean outlines, flat colors, a single "
        "centered isolated subject, and a plain white background. Do not request a scene, "
        "landscape, full-bleed background, realistic or comic shading, poster layout, or "
        "a T-shirt graphic. The white die-cut border is added later, so do not draw a "
        "rectangular frame, sticker sheet, or fake white outline. "
        f"Always include these in things_to_avoid: {avoid}."
    )


def finished_sticker_direction(candidate) -> str:
    """Ask the image model for one finished die-cut sticker, text included."""

    text = " ".join(str(getattr(candidate, "artwork_text", "") or "").split())
    idea = " ".join(str(getattr(candidate, "image_idea", "") or "").split())
    layout = " ".join(str(getattr(candidate, "format", "") or "").split()) or "die-cut cartoon"
    why = " ".join(str(getattr(candidate, "why_it_works", "") or "").split())
    lettering = (
        "Merchandise text: none. Do not render any words."
        if not text
        else (
            f'Render this exact text in the image, once, in bold legible lettering: "{text}". '
            "Do not add any other words."
        )
    )
    return (
        "Finished sticker, this overrides any note that says not to draw an outline. "
        "Die-cut vinyl sticker, thick white outline, flat vector, plain white background. "
        f"Layout: {layout}. "
        f"Subject: {idea or 'one cute or iconic character that makes the joke land'}. "
        f"{lettering} "
        f"The picture completes the joke: {why or 'the character is the second meaning'}. "
        "No product mockup, no photo, no extra caption."
    )


def merchandise_text_clause(text: str) -> str:
    """Tell the image model to render a short line, or no lettering at all."""

    cleaned = " ".join(text.split())
    if not cleaned:
        return (
            "Merchandise text: none. Do not render any words, letters, numbers, or captions. "
            "This sticker is image-only."
        )
    return (
        f'Exact merchandise text: "{cleaned}". '
        "Render this short sticker line once, legibly, as part of the isolated subject. "
        "Do not add any other words."
    )


def crossover_block(niche_a: str, niche_b: str) -> str:
    """Describe a two-niche intersection, or return nothing when the pair is incomplete."""

    first = niche_a.strip()
    second = niche_b.strip()
    if not first or not second:
        return ""
    return (
        "One real person who is both "
        f'"{first}" and "{second}". Stack those co-occurring traits in the line. '
        "Do not write a scenario about the two groups meeting, and do not describe a job procedure. "
        "Fuse them into one centered sticker subject.\n"
    )


def artwork_preamble() -> str:
    """Return the deterministic image-model wrapper shared by the social artwork stages."""

    return (
        "Create a die-cut vinyl sticker design, not a T-shirt graphic, poster, product "
        "mockup, advertisement, or lifestyle illustration. Use flat vector-style "
        "illustration with bold clean outlines and flat colors. Show a single centered "
        "isolated subject on a plain white background. Do not use a scene, landscape, or "
        "full-bleed background. Do not use realistic shading, semi-realistic comic shading, "
        "gradients, or a poster layout. Leave the area around the subject empty white so "
        "it can be cut out. Do not draw a white sticker border, rectangular frame, or "
        "mockup; the die-cut outline is added separately. No logos, brands, or extra text."
    )


def merged_avoid_list(items: list[str]) -> str:
    """Join a candidate avoid list with the permanent sticker exclusions."""

    merged: list[str] = []
    for item in [*items, *STICKER_AVOID]:
        cleaned = item.strip()
        if cleaned and cleaned not in merged:
            merged.append(cleaned)
    return "; ".join(merged)
