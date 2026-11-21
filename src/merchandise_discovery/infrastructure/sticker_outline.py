"""Turn a generated image into a transparent die-cut sticker.

Image models are asked for one subject on a plain background. This step removes that
background and paints the thick white border a vinyl cutter would leave around the art.
The original file is left untouched by the caller.
"""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter


def render_die_cut_png(content: bytes, *, outline_px: int | None = None) -> tuple[bytes, int, int]:
    """Return a transparent PNG, plus its width and height, for one generated image."""

    try:
        with Image.open(BytesIO(content)) as loaded:
            sticker = add_die_cut_outline(loaded, outline_px=outline_px)
    except (OSError, ValueError) as error:
        raise ValueError("Die-cut post-processing could not read the generated image.") from error
    buffer = BytesIO()
    sticker.save(buffer, format="PNG")
    width, height = sticker.size
    return buffer.getvalue(), width, height


def add_die_cut_outline(image: Image.Image, *, outline_px: int | None = None) -> Image.Image:
    """Remove a plain background and stroke a thick white outline around the subject."""

    subject = _remove_plain_background(image)
    if subject.getchannel("A").getbbox() is None:
        raise ValueError("Die-cut post-processing found no subject on the plain background.")

    width, height = subject.size
    radius = _outline_radius(width, height, outline_px)
    pad = radius + 2
    canvas = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    canvas.paste(subject, (pad, pad))

    mask = canvas.getchannel("A").point(lambda value: 255 if value > 16 else 0)
    dilated = mask.filter(ImageFilter.MaxFilter(radius * 2 + 1))
    border = Image.new("RGBA", canvas.size, (255, 255, 255, 255))
    border.putalpha(dilated)
    sticker = Image.alpha_composite(border, canvas)
    bounds = sticker.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Die-cut post-processing found no subject on the plain background.")
    return sticker.crop(bounds)


def _outline_radius(width: int, height: int, outline_px: int | None) -> int:
    """Pick a thick border that still fits a small sample image and a 1024 render."""

    if outline_px is not None:
        radius = outline_px
    else:
        radius = round(min(width, height) * 0.04)
    return max(4, min(radius, 48))


def _remove_plain_background(image: Image.Image) -> Image.Image:
    """Clear a connected plain background while keeping enclosed subject colors."""

    rgba = image.convert("RGBA").copy()
    _flood_matching_border(rgba, (255, 255, 255), tolerance=22)
    plain_color = _uniform_border_color(rgba)
    if plain_color is not None and _color_distance(plain_color, (255, 255, 255)) > 22:
        _flood_matching_border(rgba, plain_color, tolerance=36)
    return rgba


def _uniform_border_color(image: Image.Image) -> tuple[int, int, int] | None:
    """Return the corner color when the opaque corners agree, otherwise no plain color."""

    width, height = image.size
    pixels = image.load()
    corners = [
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    ]
    opaque = [pixel[:3] for pixel in corners if pixel[3] >= 12]
    if len(opaque) < 3:
        return None
    reference = opaque[0]
    if all(_color_distance(reference, other) <= 24 for other in opaque[1:]):
        return reference
    return None


def _flood_matching_border(
    image: Image.Image,
    color: tuple[int, int, int],
    *,
    tolerance: int,
) -> None:
    """Flood-fill border pixels close to ``color`` so interior fills stay intact."""

    width, height = image.size
    seeds: list[tuple[int, int]] = []
    for x in range(width):
        seeds.append((x, 0))
        seeds.append((x, height - 1))
    for y in range(1, height - 1):
        seeds.append((0, y))
        seeds.append((width - 1, y))
    for x, y in seeds:
        pixel = image.getpixel((x, y))
        if pixel[3] < 12:
            continue
        if _color_distance(pixel[:3], color) > tolerance:
            continue
        ImageDraw.floodfill(image, (x, y), (0, 0, 0, 0), thresh=tolerance)


def _color_distance(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Return the largest per-channel gap, which tracks a flat background well."""

    return max(abs(int(left[channel]) - int(right[channel])) for channel in range(3))
