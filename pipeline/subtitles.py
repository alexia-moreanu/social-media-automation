"""Subtitles: transcribe Romanian speech locally and burn it into the video.

Transcription runs on this Mac with faster-whisper, so it costs nothing per video and
no footage leaves the machine. Styling follows the brand guide: Montserrat SemiBold,
white with a heavy outline, sitting above the Instagram UI.
"""

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "brand" / "fonts"
FONT_NAME = "Montserrat SemiBold"
FONT_FILE = FONT_DIR / "Montserrat-SemiBold-static.ttf"

# "small" mangles Romanian names and loanwords ("hat-placen" for "Happy Place"),
# so medium is the default despite being slower.
MODEL_SIZE = "medium"
MAX_CHARS_PER_CUE = 34        # short cues: two lines maximum, readable at phone size
MAX_SECONDS_PER_CUE = 2.2

# Whisper guesses proper nouns badly ("Hap Place", "tambuil din Dumârș"). Priming it with
# the vocabulary it will actually hear fixes most of that.
VOCABULARY = (
    "Happy Place, Căsuța Verde, Căsuța Albastră, Căsuța Galbenă, Domnești, Ilfov, "
    "București, Mihaela, Adrian, Lola, botez, tăierea moțului, cununie, team building, "
    "grătar, piscină, trambulină, foișor, curte, petrecere, workshop."
)

# Applied after transcription, for the handful of terms that still come back wrong.
CORRECTIONS = {
    "hap place": "Happy Place",
    "hepi place": "Happy Place",
    "hapi place": "Happy Place",
    "tambuil": "team building",
    "tim biuld": "team building",
    "casuta verde": "Căsuța Verde",
    "domnesti": "Domnești",
}

_model = None


def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        # int8 on CPU: fast enough on Apple Silicon and accurate for clean phone audio
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def has_audio(video_path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True,
    )
    return "audio" in result.stdout


def transcribe(video_path: Path, language="ro"):
    """Return cues: [{start, end, text}] grouped into short, readable chunks."""
    segments, _info = _load_model().transcribe(
        str(video_path), language=language, word_timestamps=True, vad_filter=True,
        initial_prompt=VOCABULARY,
    )

    cues, current = [], None
    for segment in segments:
        for word in (segment.words or []):
            token = word.word.strip()
            if not token:
                continue
            if current is None:
                current = {"start": word.start, "end": word.end, "text": token}
                continue
            too_long = len(current["text"]) + 1 + len(token) > MAX_CHARS_PER_CUE
            too_slow = word.end - current["start"] > MAX_SECONDS_PER_CUE
            if too_long or too_slow:
                cues.append(current)
                current = {"start": word.start, "end": word.end, "text": token}
            else:
                current["text"] += " " + token
                current["end"] = word.end
    if current:
        cues.append(current)

    for cue in cues:
        cue["text"] = _apply_corrections(cue["text"])
    return cues


def _apply_corrections(text: str) -> str:
    import re

    for wrong, right in CORRECTIONS.items():
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
    return text


def _timestamp(seconds: float) -> str:
    hours, rest = divmod(max(0.0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def write_ass(cues, path: Path, video_height=1920):
    """ASS rather than SRT: it carries the styling, so ffmpeg needs no extra flags."""
    font_size = round(video_height * 0.042)
    margin_v = round(video_height * 0.18)  # keep clear of the Instagram caption overlay
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: {video_height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HP,{FONT_NAME},{font_size},&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,4,2,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [
        f"Dialogue: 0,{_timestamp(cue['start'])},{_timestamp(cue['end'])},HP,,0,0,0,,{cue['text']}"
        for cue in cues
    ]
    path.write_text(header + "\n".join(lines) + "\n")
    return path


def _cue_image(text: str, width: int, font: ImageFont.FreeTypeFont, path: Path) -> Path:
    """One transparent strip carrying a cue, with a heavy outline for legibility."""
    scratch = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    max_text_width = int(width * 0.84)

    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if scratch.textlength(candidate, font=font) <= max_text_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    ascent, descent = font.getmetrics()
    line_height = ascent + descent + 10
    height = line_height * len(lines) + 20
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        text_width = draw.textlength(line, font=font)
        x = (width - text_width) / 2
        y = 10 + index * line_height
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=max(3, font.size // 9), stroke_fill=(0, 0, 0, 235))
    image.save(path)
    return path


def burn_overlays(video_path: Path, cues, output: Path) -> Path:
    """Burn cues in by overlaying rendered PNGs.

    This ffmpeg build has neither libass nor libfreetype, so the usual `subtitles` and
    `drawtext` filters do not exist. Pillow already has the brand font, so the text is
    rendered here and composited as images.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", str(video_path)],
        capture_output=True, text=True,
    )
    width, height = (int(v) for v in probe.stdout.strip().split("x"))
    font = ImageFont.truetype(str(FONT_FILE), max(22, round(height * 0.042)))
    bottom_margin = round(height * 0.16)  # clear of the Instagram caption overlay

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs, filters, previous = ["-i", str(video_path)], [], "[0:v]"
        for index, cue in enumerate(cues):
            strip = _cue_image(cue["text"], width, font,
                               Path(tmpdir) / f"cue_{index:03d}.png")
            inputs += ["-i", str(strip)]
            label = f"[v{index}]"
            filters.append(
                f"{previous}[{index + 1}:v]overlay=x=0:y=H-h-{bottom_margin}:"
                f"enable='between(t,{cue['start']:.2f},{cue['end']:.2f})'{label}"
            )
            previous = label

        args = ["ffmpeg", "-y", "-v", "error", *inputs]
        if filters:
            args += ["-filter_complex", ";".join(filters), "-map", previous]
        else:
            args += ["-map", "0:v"]
        args += ["-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                 "-movflags", "+faststart", str(output)]
        result = subprocess.run(args, capture_output=True, text=True)
    if not output.exists():
        raise RuntimeError(f"ffmpeg could not burn subtitles: {result.stderr[-400:]}")
    return output


def write_srt(cues, path: Path) -> Path:
    """Plain SRT so a human can fix the wording in any text editor."""
    def stamp(seconds):
        hours, rest = divmod(max(0.0, seconds), 3600)
        minutes, secs = divmod(rest, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}".replace(".", ",")

    blocks = [
        f"{index}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n{cue['text']}\n"
        for index, cue in enumerate(cues, start=1)
    ]
    path.write_text("\n".join(blocks))
    return path


def read_srt(path: Path):
    """Read cues back after a human has corrected them."""
    def seconds(stamp):
        hours, minutes, rest = stamp.replace(",", ".").split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(rest)

    cues = []
    for block in path.read_text().strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        start, end = lines[1].split(" --> ")
        cues.append({"start": seconds(start), "end": seconds(end),
                     "text": " ".join(lines[2:])})
    return cues


def burn(video_path: Path, ass_path: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    # Quote the paths: ffmpeg treats ':' and '=' inside filter arguments as syntax.
    # fontsdir lets libass find our brand font without installing it system-wide.
    subtitle_filter = (
        f"subtitles=filename='{ass_path}':fontsdir='{FONT_DIR}'"
    )
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video_path),
         "-vf", subtitle_filter,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output)],
        capture_output=True, text=True,
    )
    if not output.exists():
        raise RuntimeError(f"ffmpeg could not burn subtitles: {result.stderr[-400:]}")
    return output
