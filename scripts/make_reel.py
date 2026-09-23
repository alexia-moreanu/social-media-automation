"""Build one 10-15s reel from Drive clips and send it to Telegram for review.

    python3 scripts/make_reel.py --folder gradinarit
    python3 scripts/make_reel.py --candidates 10

Nothing is published. The finished .mp4 lands in output/ and is sent to the group.
"""

import argparse
import random
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import approval, curate, library, planner, video  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def drop_duplicates(clips):
    """Drive is full of 'IMG_1550.mov' next to 'IMG_1550 2.mov' — keep one of each."""
    seen, unique = {}, []
    for clip in clips:
        stem = Path(clip["name"]).stem
        stem = re.sub(r"[ _-]*(copy|copie)?[ _-]*\d?$", "", stem, flags=re.I).strip()
        key = (stem.casefold(), clip.get("size"))
        if key in seen:
            continue
        seen[key] = True
        unique.append(clip)
    return unique


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", help="only use clips from this Drive subfolder")
    parser.add_argument("--candidates", type=int, default=9,
                        help="how many clips to download and score")
    parser.add_argument("--shots", type=int, default=6, help="how many cuts in the reel")
    parser.add_argument("--from-plan", action="store_true",
                        help="take the folder and theme from the monthly plan")
    parser.add_argument("--slot", help="build this exact slot: YYYY-MM-DD/HH:MM")
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-curation", action="store_true",
                        help="rank by motion only, skip the visual judgement")
    parser.add_argument("--min-score", type=float, default=6.5,
                        help="average shot rating below this is flagged as weak")
    args = parser.parse_args()

    load_dotenv()

    plan, slot = None, None
    if args.from_plan or args.slot:
        plan = planner.load()
        slot = (planner.slot_by_key(plan, args.slot) if args.slot
                else (planner.next_slot(plan) if plan else None))
        if not slot:
            sys.exit("No such planned slot — run scripts/plan_month.py first.")
        args.folder = slot.get("folder") or args.folder
        print(f"0. Plan slot: {slot['date']} {slot['time']} · {slot['pillar']}\n"
              f"   temă: {slot['theme']}\n   {slot.get('note', '')}")
        if slot.get("audio"):
            print(f"   🎵 {slot['audio']}")

    if slot and slot.get("assets"):
        print(f"1. Using the {len(slot['assets'])} clips the plan chose...")
        clips = library.assets_by_ids(slot["assets"])
        args.candidates = len(clips)
        args.folder = None  # the plan already chose; folder filtering would drop them all
        # Cut to what the plan actually has: 4 good clips make a fine 4-shot reel.
        args.shots = min(args.shots, len(clips))
    else:
        print("1. Finding vertical clips in Drive...")
        clips = [c for c in library.list_media("video")
                 if (c.get("videoMediaMetadata") or {}) or True]
    if args.folder:
        wanted = args.folder.strip().casefold()
        clips = [c for c in clips if c["folder"].strip().casefold() == wanted]
    if len(clips) < args.shots:
        sys.exit(f"Only {len(clips)} clips available.")
    clips = drop_duplicates(clips)
    candidates = random.sample(clips, min(args.candidates, len(clips)))
    print(f"   {len(clips)} clips available, scoring {len(candidates)}")

    print("2. Downloading and scoring for motion...")
    scored = []
    for clip in candidates:
        path = library.download(clip)
        try:
            length = video.duration(path)
        except Exception:
            continue
        if length < 2.0 or length > 120:
            continue  # stray downloads and long unedited footage are not reel material
        score = video.score_clip(path)
        scored.append((score, length, path, clip))
        print(f"   {clip['name'][:34]:<34} {length:5.1f}s  motion {score:.2f}")

    # Drop identical footage (same byte count) before judging.
    deduped, used_sizes = [], set()
    for row in sorted(scored, reverse=True, key=lambda r: r[0]):
        size = row[3].get("size")
        if size in used_sizes:
            continue
        used_sizes.add(size)
        deduped.append(row)

    if args.no_curation:
        chosen = deduped[:args.shots]
    else:
        print("\n3. Asking Claude which shots belong in the reel...")
        order, ratings, opening = curate.choose_clips(
            [row[2] for row in deduped], shots=args.shots
        )
        by_index = {r["clip"] - 1: r for r in ratings}
        for index, row in enumerate(deduped):
            rating = by_index.get(index, {})
            mark = "✓" if index in order[:args.shots] else " "
            print(f"   {mark} {row[3]['name'][:30]:<30} {rating.get('score', '?')}/10"
                  f"  {rating.get('why', '')}")
        print(f"   opening: {opening}")
        chosen = [deduped[i] for i in order[:args.shots]] or deduped[:args.shots]
        scores = [by_index.get(i, {}).get("score") for i in order[:args.shots]]
        scores = [s for s in scores if isinstance(s, (int, float))]
        quality = round(sum(scores) / len(scores), 1) if scores else None
        if quality is not None:
            print(f"   average shot quality: {quality}/10")
    if len(chosen) < 2:
        sys.exit("Not enough usable clips.")

    weak_note = ""
    if not args.no_curation and quality is not None and quality < args.min_score:
        weak_note = (
            f"⚠️ Materialul disponibil e slab pentru tema asta (medie {quality}/10). "
            f"Cadrele din „{args.folder or 'toate folderele'}” nu prea se potrivesc — "
            f"poate merită filmat ceva nou în loc să postăm asta."
        )
        print(f"   {weak_note}")

    print("\n4. Cutting the reel...")
    for score, length, path, clip in chosen:
        print(f"   {clip['folder']}/{clip['name']}  (motion {score:.2f})")

    OUTPUT_DIR.mkdir(exist_ok=True)
    # Unique per draft: a month's reels sit side by side in the approval queue.
    stamp = (slot["date"].replace("-", "") if slot
             else __import__("datetime").datetime.now().strftime("%m%d-%H%M%S"))
    output = OUTPUT_DIR / f"reel_{stamp}.mp4"
    video.build_reel([row[2] for row in chosen], output)
    seconds = video.duration(output)
    size_mb = output.stat().st_size / 1e6
    print(f"   -> {output}  ({seconds:.1f}s, {size_mb:.1f} MB, 1080x1920)")

    if not args.no_telegram:
        print("5. Sending to Telegram...")
        shots = "\n".join(f"· {row[3]['name']}" for row in chosen)
        brief = ""
        if slot:
            brief = (f"📅 {slot['date']} {slot['time']} · {slot['pillar']}\n"
                     f"🎯 {slot['theme']}\n")
            if slot.get("audio"):
                brief += f"🎵 {slot['audio']}\n"
            brief += "\n"
        approval.send_video(
            output,
            f"🎬 Reel draft — {seconds:.0f}s, {len(chosen)} cadre\n\n{brief}{shots}\n\n"
            f"Fără sunet: muzica se adaugă în aplicație la postare."
            + (f"\n\n{weak_note}" if weak_note else ""),
        )
        if plan and slot:
            if weak_note:
                planner.mark(plan, slot, "planned",
                             note=f"draft slab ({quality}/10) — slotul rămâne deschis")
            else:
                planner.mark(plan, slot, "ready_manual",
                             note="reel trimis pe Telegram — se postează manual cu sunet")
        print("   Sent.")


if __name__ == "__main__":
    main()
