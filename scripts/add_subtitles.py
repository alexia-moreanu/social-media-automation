"""Burn Romanian subtitles into a video and send it to Telegram.

    python3 scripts/add_subtitles.py --file media/interviu.mov
    python3 scripts/add_subtitles.py --drive            # pick a clip with speech from Drive

Transcription runs locally (faster-whisper) — free, and nothing is uploaded.
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import approval, library, subtitles, video  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "output"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="local video file")
    parser.add_argument("--drive", action="store_true", help="pick a clip from Drive instead")
    parser.add_argument("--folder")
    parser.add_argument("--model", default=subtitles.MODEL_SIZE,
                        help="whisper model: small (fast) or medium (better Romanian)")
    parser.add_argument("--keep-text", action="store_true", help="print the transcript")
    parser.add_argument("--from-srt", help="skip transcription, burn this corrected .srt")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    subtitles.MODEL_SIZE = args.model

    if args.file:
        path = Path(args.file)
    elif args.drive:
        asset = library.pick_asset("video", folder=args.folder)
        print(f"1. {asset['folder']}/{asset['name']}")
        path = library.download(asset)
    else:
        sys.exit("Pass --file <path> or --drive")

    if not subtitles.has_audio(path):
        sys.exit("That clip has no audio track — nothing to transcribe.")

    if args.from_srt:
        print(f"2. Using your corrected subtitles from {args.from_srt}")
        cues = subtitles.read_srt(Path(args.from_srt))
    else:
        print(f"2. Transcribing with whisper '{args.model}' (this runs locally)...")
        cues = subtitles.transcribe(path)
    if not cues:
        sys.exit("No speech detected in the audio.")
    print(f"   {len(cues)} cues, {cues[-1]['end']:.1f}s of speech")
    if args.keep_text:
        for cue in cues:
            print(f"   [{cue['start']:6.2f}] {cue['text']}")

    print("3. Burning them in...")
    height = 1920
    ass = OUTPUT / f"{path.stem}.ass"
    OUTPUT.mkdir(exist_ok=True)
    subtitles.write_ass(cues, ass, video_height=height)  # for editing by hand later
    srt = subtitles.write_srt(cues, OUTPUT / f"{path.stem}.srt")
    output = subtitles.burn_overlays(path, cues, OUTPUT / f"{path.stem}_subtitrat.mp4")
    print(f"   {output} ({video.duration(output):.1f}s)")
    print(f"   Wrong words? Edit {srt} and rerun with --from-srt {srt}")

    if not args.no_telegram:
        print("4. Sending to Telegram...")
        preview = " ".join(cue["text"] for cue in cues[:6])
        approval.send_video(output, f"💬 Subtitrat automat — {len(cues)} replici\n\n„{preview}...”")
        print("   Sent.")


if __name__ == "__main__":
    main()
