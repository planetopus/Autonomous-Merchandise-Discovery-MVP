"""Die-cut outline post-processing on a sample image."""

from io import BytesIO
from pathlib import Path

from PIL import Image

from merchandise_discovery.infrastructure.sticker_outline import add_die_cut_outline
from merchandise_discovery.infrastructure.storage import LocalArtworkStorage


def _sample_image() -> Image.Image:
    """White field with one red disc, so the die-cut corners stay transparent."""

    image = Image.new("RGB", (48, 48), (255, 255, 255))
    for y in range(48):
        for x in range(48):
            if (x - 24) ** 2 + (y - 24) ** 2 <= 8**2:
                image.putpixel((x, y), (220, 30, 40))
    return image


def _opaque_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    bounds = image.getchannel("A").getbbox()
    assert bounds is not None
    return bounds


def test_die_cut_removes_white_background_and_adds_a_white_outline() -> None:
    """A plain background becomes transparent and the subject gains a thick white border."""

    sticker = add_die_cut_outline(_sample_image(), outline_px=4)

    assert sticker.mode == "RGBA"
    assert sticker.getpixel((0, 0))[3] == 0
    red_pixels = [
        pixel
        for pixel in sticker.getdata()
        if pixel[3] > 200 and pixel[0] > 180 and pixel[1] < 80 and pixel[2] < 80
    ]
    white_pixels = [
        pixel
        for pixel in sticker.getdata()
        if pixel[3] > 200 and pixel[0] > 240 and pixel[1] > 240 and pixel[2] > 240
    ]
    assert red_pixels
    assert len(white_pixels) > len(red_pixels)
    # The cropped sticker's outer edge is the outline, not the red subject or a scene.
    width, height = sticker.size
    assert sticker.getpixel((width - 1, height // 2))[:3] == (255, 255, 255)
    assert width > 16 and height > 16


def test_die_cut_removes_a_plain_nonwhite_background() -> None:
    """A flat navy field is treated as background so the subject can still be cut out."""

    image = Image.new("RGB", (40, 40), (12, 28, 92))
    for y in range(40):
        for x in range(40):
            if (x - 20) ** 2 + (y - 20) ** 2 <= 7**2:
                image.putpixel((x, y), (240, 180, 20))
    sticker = add_die_cut_outline(image, outline_px=4)

    navy = [
        pixel
        for pixel in sticker.getdata()
        if pixel[3] > 0 and pixel[2] > pixel[0] and pixel[2] > 60 and pixel[0] < 40
    ]
    assert not navy
    assert sticker.getpixel((0, 0))[3] == 0
    assert any(pixel[0] > 200 and pixel[1] > 140 and pixel[2] < 80 for pixel in sticker.getdata())


def test_local_storage_keeps_the_original_and_writes_a_transparent_png(tmp_path: Path) -> None:
    """The provider file stays on disk and the returned key points at the die-cut PNG."""

    sample = _sample_image()
    source = tmp_path / "source.png"
    sample.save(source)
    storage = LocalArtworkStorage(tmp_path / "artifacts")

    stored = storage.persist(
        source_url=source.as_uri(),
        storage_key="xai-artwork/sample/variant-1.png",
        reported_size_bytes=1,
    )

    original = tmp_path / "artifacts" / "xai-artwork" / "sample" / "variant-1.png"
    sticker_path = tmp_path / "artifacts" / "xai-artwork" / "sample" / "variant-1.diecut.png"
    assert original.read_bytes() == source.read_bytes()
    assert sticker_path.is_file()
    assert stored.storage_key == "xai-artwork/sample/variant-1.diecut.png"
    assert stored.raw_storage_key == "xai-artwork/sample/variant-1.png"
    assert stored.mime_type == "image/png"
    with Image.open(BytesIO(sticker_path.read_bytes())) as sticker:
        assert sticker.mode == "RGBA"
        assert sticker.getpixel((0, 0))[3] == 0
        assert _opaque_bounds(sticker)
