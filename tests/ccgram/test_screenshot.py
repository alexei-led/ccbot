import io

import pytest
from PIL import Image

from ccgram.screenshot import text_to_image

SAMPLE_TEXT = "hello world\nfoo bar"
SAMPLE_ANSI = "\x1b[32mgreen\x1b[0m normal \x1b[31mred\x1b[0m"


@pytest.mark.asyncio
async def test_default_produces_valid_png():
    png = await text_to_image(SAMPLE_TEXT, with_ansi=False)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.mode == "RGB"


@pytest.mark.asyncio
async def test_ansi_produces_valid_png():
    png = await text_to_image(SAMPLE_ANSI, with_ansi=True)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"


@pytest.mark.asyncio
async def test_live_mode_produces_valid_png():
    png = await text_to_image(SAMPLE_TEXT, with_ansi=False, live_mode=True)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.mode == "P"


@pytest.mark.asyncio
async def test_live_mode_smaller_than_default():
    regular = await text_to_image(SAMPLE_TEXT, with_ansi=False, live_mode=False)
    live = await text_to_image(SAMPLE_TEXT, with_ansi=False, live_mode=True)
    assert len(live) < len(regular)


@pytest.mark.asyncio
async def test_live_mode_smaller_dimensions():
    regular = await text_to_image(SAMPLE_TEXT, with_ansi=False, live_mode=False)
    live = await text_to_image(SAMPLE_TEXT, with_ansi=False, live_mode=True)
    reg_img = Image.open(io.BytesIO(regular))
    live_img = Image.open(io.BytesIO(live))
    assert live_img.width < reg_img.width
    assert live_img.height < reg_img.height


@pytest.mark.asyncio
async def test_default_unchanged_without_live_mode():
    png = await text_to_image(SAMPLE_TEXT, font_size=28, with_ansi=False)
    img = Image.open(io.BytesIO(png))
    assert img.mode == "RGB"
    assert img.format == "PNG"


@pytest.mark.asyncio
async def test_live_mode_with_ansi_colors():
    png = await text_to_image(SAMPLE_ANSI, with_ansi=True, live_mode=True)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.mode == "P"
