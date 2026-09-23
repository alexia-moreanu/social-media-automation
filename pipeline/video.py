"""Reel editor: turns a handful of phone clips into one short, fast-cut vertical video.

Design choices, so the cuts feel intentional rather than random:
  - clips are scored for motion, and the busiest window of each clip is used
  - cut lengths shorten as the reel goes on (2.6s -> 1.2s), which builds pace
  - the last shot is held slightly longer so it can carry the message
  - everything is normalised to 1080x1920 / 30fps, with a silent audio track
    (Instagram is happier with one, and music gets added in the app)
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

WIDTH, HEIGHT, FPS = 1080, 1920, 30
# Cut rhythm in seconds: opens wide, tightens, then holds the final shot.
RHYTHM = [2.6, 2.2, 1.8, 1.5, 1.2, 1.2, 2.4]


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, check=False)


def duration(path: Path) -> float:
    result = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "json", str(path)])
    return float(json.loads(result.stdout)["format"]["duration"])


def motion_profile(path: Path):
    """Timestamps where the picture changes a lot — used to find the lively part."""
    result = _run([
        "ffmpeg", "-v", "info", "-i", str(path),
        "-vf", "scale=160:-2,fps=6,select='gt(scene,0.04)',metadata=print",
        "-f", "null", "-",
    ])
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", result.stderr)]


def best_window(path: Path, length: float) -> float:
    """Start time of the most eventful `length` seconds of the clip."""
    total = duration(path)
    if total <= length + 0.6:
        return max(0.0, (total - length) / 2)

    events = motion_profile(path)
    # Ignore the first and last moments: hands reaching for the phone, wobble at the end.
    usable_start, usable_end = 0.5, max(0.5, total - length - 0.3)
    if not events:
        return min(usable_end, total * 0.25)

    best_start, best_count = usable_start, -1
    step = 0.25
    start = usable_start
    while start <= usable_end:
        count = sum(1 for t in events if start <= t <= start + length)
        if count > best_count:
            best_start, best_count = start, count
        start += step
    return best_start


def score_clip(path: Path) -> float:
    """Roughly how lively a clip is, per second — used to rank candidates."""
    events = motion_profile(path)
    return len(events) / max(1.0, duration(path))


def build_reel(clips, output: Path, rhythm=None) -> Path:
    """Cut the given clips together into one vertical reel."""
    rhythm = rhythm or RHYTHM
    pieces = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for index, (clip, length) in enumerate(zip(clips, rhythm)):
            start = best_window(clip, length)
            piece = tmp / f"piece_{index:02d}.mp4"
            # Fill the 9:16 frame: scale up so the short side covers, then centre-crop.
            video_filter = (
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT},fps={FPS},setsar=1"
            )
            if index % 2 == 1:
                # A slow push-in on every other shot keeps static clips from feeling dead.
                # d=1 is essential: any higher and zoompan duplicates every input frame.
                video_filter += (
                    f",zoompan=z='min(zoom+0.0012,1.10)':d=1"
                    f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={WIDTH}x{HEIGHT}:fps={FPS}"
                )
            result = _run([
                "ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(clip),
                "-vf", video_filter, "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", str(piece),
            ])
            if not piece.exists():
                raise RuntimeError(f"ffmpeg failed on {clip.name}: {result.stderr[-400:]}")
            pieces.append(piece)

        listing = tmp / "pieces.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in pieces))

        total = sum(rhythm[:len(pieces)])
        output.parent.mkdir(parents=True, exist_ok=True)
        result = _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
            # a silent track: Instagram prefers one, and music is added in the app
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest",
            "-vf", f"fade=t=in:st=0:d=0.3,fade=t=out:st={total - 0.4:.2f}:d=0.4",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            str(output),
        ])
        if not output.exists():
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-400:]}")
    return output
