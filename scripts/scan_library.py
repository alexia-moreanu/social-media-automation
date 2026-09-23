"""Look at everything in Drive and record what it shows.

    python3 scripts/scan_library.py --limit 40      # try it on a few first
    python3 scripts/scan_library.py                 # the whole library
    python3 scripts/scan_library.py --report        # just show what's catalogued

Each asset is looked at once and cached in state/catalog.json, so reruns only cost
money for new files.
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import catalog  # noqa: E402


def report(data):
    summary = catalog.summary(data)
    print(f"\nCatalogued: {summary['total_catalogued']} unused assets, "
          f"{summary['usable']} good enough to post (quality 6+)")
    print(f"  with people: {summary['with_people']}   with kids: {summary['with_kids']}")
    for label, key in (("By event", "by_event"), ("By season", "by_season"),
                       ("By kind", "by_kind")):
        print(f"\n{label}:")
        for name, count in summary[key].items():
            print(f"  {name:<22} {count}")
    print("\nBest assets:")
    for asset in summary["top"][:12]:
        print(f"  {asset['quality']:>2}/10 [{asset['kind']:<5}] {asset['subject'][:52]:<52} "
              f"{asset['folder'][:18]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="how many new assets to look at")
    parser.add_argument("--photos-only", action="store_true")
    parser.add_argument("--report", action="store_true", help="don't scan, just report")
    parser.add_argument("--rescan", action="store_true", help="redo assets already done")
    args = parser.parse_args()

    load_dotenv()
    if args.report:
        report(catalog.load())
        return

    kinds = ("image",) if args.photos_only else ("image", "video")
    data = catalog.scan(limit=args.limit, only_new=not args.rescan, kinds=kinds)
    report(data)


if __name__ == "__main__":
    main()
