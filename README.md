# social-media-automation

Automated Facebook + Instagram pipeline for **Happy Place** (happy-place.ro), a family-run
party venue in Domnești, Ilfov.

Content-first: the footage decides what gets posted. Every photo and video in Drive is
catalogued once by what it actually shows, ideas are built from that catalogue, and the
strategy only decides format, timing and seasonal hooks. Nothing reaches Facebook or
Instagram without a human tapping approve in Telegram.

```
Drive library ─► catalogue (what each asset really shows)
                      │
                      ▼
            ideas the library can deliver
                      │
  strategy + engagement + live trends ─► monthly plan (dated slots)
                      │
     ┌────────────────┼────────────────┐
     ▼                ▼                ▼
  photo post      carousel           reel
     └────────────────┼────────────────┘
                      ▼
        Telegram approval (approve / edit / reject)
                      │
     Facebook scheduled at Meta · Instagram queued locally
                      │
                      ▼
            engagement feeds next month's plan
```

## What's not in this repo

`brand/` and `docs/` hold the brand guide, the family's own texts, logos, fonts and the
content strategy. They are business material and stay off this public repo, but the
pipeline reads them at runtime. To run it you need:

- `brand/brand_guide.md` — facts, tone of voice, banned phrasings, visual identity
- `brand/about_ro.md` — source texts; captions may only state facts found here
- `brand/assets/` — logo and icon PNGs · `brand/fonts/` — Amatic SC + Montserrat
- `docs/content_strategy.md` — cadence, pillars, weekly rhythm

Secrets live in `.env` (see `.env.example`) and `credentials/`; both are gitignored.

## Setup

```bash
pip install requests python-dotenv pillow pillow-heif google-api-python-client google-auth faster-whisper
brew install ffmpeg          # reels and subtitles
cp .env.example .env         # then fill in the keys
python3 scripts/check_meta_connection.py
python3 scripts/check_drive_connection.py
```

## Everyday use

```bash
python3 scripts/scan_library.py          # catalogue new media (cached, incremental)
python3 scripts/plan_month.py            # next month's plan, from the catalogue
python3 scripts/plan_week.py --apply     # curate the coming week
python3 run_next.py                      # build whatever the plan asks for next
python3 scripts/produce_month.py         # build every planned slot at once
python3 scripts/process_approvals.py --watch 600   # act on Telegram decisions
python3 scripts/show_queue.py            # what's scheduled
```

Two background jobs (`scripts/*.plist` → `~/Library/LaunchAgents/`): the scheduler
publishes due Instagram posts every 15 minutes, and the planner writes next month's plan
on the 25th. Facebook scheduling happens on Meta's servers and needs nothing running.

## How it fits together

| Module | Does |
|---|---|
| `pipeline/library.py` | Reads Drive, downloads assets, converts HEIC |
| `pipeline/catalog.py` | Looks at every asset once, records subject/event/season/quality |
| `pipeline/ideas.py` | Turns the catalogue into post ideas the library can deliver |
| `pipeline/planner.py` | Dated plan from ideas + strategy + engagement + trends |
| `pipeline/trends.py` | Live web search for current audio, formats, local dates |
| `pipeline/caption.py` | Writes the caption, in one Romanian voice, never a price |
| `pipeline/factcheck.py` | Flags claims the brand documents do not support |
| `pipeline/design.py` | Branded 4:5 / 9:16 / 1:1 images with the real fonts |
| `pipeline/carousel.py` | Picks a coherent slide set and the cover text |
| `pipeline/video.py` | Cuts vertical reels: motion scoring, rhythm, push-ins |
| `pipeline/curate.py` | Judges which shots deserve to be in a reel |
| `pipeline/subtitles.py` | Local Whisper transcription, burned-in subtitles |
| `pipeline/approval.py` | Telegram drafts and decisions |
| `pipeline/voice.py` | Learns from every edit and rejection |
| `pipeline/publisher.py` | Meta Graph API: photos, carousels, scheduling |
| `pipeline/schedule.py` | The posting queue and weekly rhythm |
| `pipeline/analytics.py` | Engagement per pillar, format, weekday and hour |

## Rules the pipeline enforces

- **No prices in posts.** Offers are personalised by phone, WhatsApp or DM.
- **One Romanian caption**, with the English words Romanians actually say — never a
  bilingual duplicate.
- **Every caption carries something concrete**: a capacity, a date, a practical tip.
- **Only facts from the brand documents.** Anything else is flagged before you see it.
- **Quality over volume.** If the footage can't support the rhythm, it plans fewer posts
  and puts the rest on a shoot list.
- **Nothing publishes without a human tap.** Reels go out manually so they can carry
  trending audio, which the API cannot add.
