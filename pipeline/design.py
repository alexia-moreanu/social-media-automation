"""Design: puts branded text on a photo, following brand/brand_guide.md.

Style from the guide:
  short headline in Amatic SC (yellow or white) + one line in Montserrat (white),
  on a soft dark gradient at the bottom, with the small house icon as a corner watermark.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_HEADLINE = ROOT / "brand" / "fonts" / "AmaticSC-Bold.ttf"
FONT_BODY = ROOT / "brand" / "fonts" / "Montserrat.ttf"
ICON = ROOT / "brand" / "assets" / "icon-white.png"

YELLOW = (254, 210, 65)
WHITE = (255, 255, 255)

SIZES = {
    "post": (1080, 1350),    # 4:5, the tallest the feed allows
    "story": (1080, 1920),   # 9:16
    "square": (1080, 1080),
}


def _body_font(size):
    font = ImageFont.truetype(str(FONT_BODY), size)
    font.set_variation_by_name("SemiBold")  # the file defaults to Thin, unreadable on photos
    return font


def _cover(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale and centre-crop so the photo fills the canvas without distortion."""
    scale = max(width / image.width, height / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)),
                           Image.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _gradient(width: int, height: int, coverage=0.55, strength=238) -> Image.Image:
    """A soft dark band at the bottom so white text stays readable.

    Strong enough for the worst case: white text over sunlit grass.
    """
    gradient = Image.new("L", (1, height), 0)
    start = int(height * (1 - coverage))
    for y in range(start, height):
        progress = (y - start) / max(1, height - start)
        gradient.putpixel((0, y), int(strength * progress ** 1.25))
    alpha = gradient.resize((width, height))
    layer = Image.new("RGBA", (width, height), (16, 14, 13, 255))
    layer.putalpha(alpha)
    return layer


def _wrap(draw, text, font, max_width):
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def compose(image_path: Path, headline: str, subline: str = "", *,
            size="post", output: Path = None, headline_colour=YELLOW,
            watermark=True) -> Path:
    width, height = SIZES[size]
    photo = Image.open(image_path).convert("RGB")
    canvas = _cover(photo, width, height).convert("RGBA")
    if headline or subline:
        # the gradient exists to make text readable; a plain slide doesn't need it
        canvas.alpha_composite(_gradient(width, height))

    draw = ImageDraw.Draw(canvas)
    margin = round(width * 0.075)
    text_width = width - 2 * margin

    headline_font = ImageFont.truetype(str(FONT_HEADLINE), round(width * 0.135))
    subline_font = _body_font(round(width * 0.036))

    headline_lines = _wrap(draw, headline, headline_font, text_width)
    subline_lines = []
    if subline:
        # "a · b" is two facts: break on the separator before falling back to word wrap
        for part in [p.strip() for p in subline.split("·") if p.strip()]:
            subline_lines += _wrap(draw, part, subline_font, text_width)

    # Measure real glyph heights instead of guessing: Amatic is very tall and thin,
    # and guessed line steps made the headline collide with the subline.
    def line_height(font, sample="Hxgpăî"):
        box = font.getbbox(sample)
        return box[3] - box[1]

    headline_step = round(line_height(headline_font) * 1.18)
    subline_step = round(line_height(subline_font) * 1.55)
    gap = round(width * 0.035)

    block_height = (len(headline_lines) * headline_step
                    + (gap if subline_lines else 0)
                    + len(subline_lines) * subline_step)
    y = height - margin - block_height

    for line in headline_lines:
        box = headline_font.getbbox(line)
        draw.text((margin + 4 - box[0], y + 4 - box[1]), line,
                  font=headline_font, fill=(0, 0, 0, 130))
        draw.text((margin - box[0], y - box[1]), line,
                  font=headline_font, fill=headline_colour)
        y += headline_step

    if subline_lines:
        y += gap
        for line in subline_lines:
            box = subline_font.getbbox(line)
            draw.text((margin + 2 - box[0], y + 2 - box[1]), line,
                      font=subline_font, fill=(0, 0, 0, 130))
            draw.text((margin - box[0], y - box[1]), line,
                      font=subline_font, fill=WHITE)
            y += subline_step

    if watermark and ICON.exists():
        icon = Image.open(ICON).convert("RGBA")
        icon_width = round(width * 0.10)
        icon = icon.resize((icon_width, round(icon.height * icon_width / icon.width)),
                           Image.LANCZOS)
        faded = icon.copy()
        faded.putalpha(icon.getchannel("A").point(lambda a: int(a * 0.9)))
        # bottom-right, inside the gradient: a white icon on a bright sky is invisible
        canvas.alpha_composite(
            faded, (width - margin - icon.width, height - margin - icon.height)
        )

    output = output or ROOT / "output" / f"{image_path.stem}_{size}.jpg"
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, quality=92)
    return output
