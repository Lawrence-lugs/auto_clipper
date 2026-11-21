# AGENTS.md

Instructions for agents working in this repository.

## What this project is

`auto_clipper` currently contains one finished experiment: reconstructing a
YouTube live chat's message rate over the video timeline from the `live_chat`
replay, then smoothing the spike train into a readable curve.

The experiment is done. The code is intentionally small and is meant to be the
foundation for chat-based analytics and, eventually, highlight/clip detection.
Do not add a web app, database, or scraper unless the task explicitly asks.

## Environment

- Python 3.11+ (developed on 3.14, Windows; CI container uses 3.13).
- Runtime deps: `numpy`, `matplotlib`.
- Dev dep: `pytest`.
- External: `yt-dlp` on `PATH` for downloading chat replays and metadata.
- Charts use the `Agg` backend and must work headless.
- Windows PowerShell is the primary shell. Use `$env:PYTHONPATH="src"` when the
  package is not installed. Set `$env:PYTHONIOENCODING="utf-8"` before printing
  Japanese text, or the console codepage will raise `UnicodeEncodeError`.
- `.devcontainer/` provides a Docker image with Python, ffmpeg, `yt-dlp`, and
  CJK fonts for charts.

## Commands

```powershell
$env:PYTHONPATH="src"
python -m autoclipper fetch   https://youtu.be/LJgPVaZbTgI
python -m autoclipper analyze https://youtu.be/LJgPVaZbTgI
python -m pytest -q
```

Outputs are written to `out/`. Raw downloads go to `data/` and are ignored by
git. `fetch` caches by video id; `analyze` reuses the cache unless
`--force-fetch` is passed.

## Data model and invariants

- **Time base:** all series and event offsets are seconds from the start of the
  video, taken from `replayChatItemAction.videoOffsetTimeMsec` (milliseconds in
  the JSON, divided by 1000 in code).
- **Counted renderers:** `liveChatTextMessageRenderer`,
  `liveChatPaidMessageRenderer`, `liveChatPaidStickerRenderer`,
  `liveChatMembershipItemRenderer`. Skip `liveChatViewerEngagementMessageRenderer`
  and any unknown renderer.
- **De-duplication:** replay batches can overlap. Deduplicate by renderer `id`;
  never invent ids for items that lack one.
- **Waiting room:** YouTube maps pre-stream messages to offset 0 but preserves
  their wall-clock `timestampUsec`. `split_preroll()` classifies all near-zero
  events as pre-roll only when their wall-clock span is at least 60 s. Keep the
  heuristic configurable, not hard-coded into the parser.
- **Rate:** 10 s bins, expressed as messages per minute, Gaussian σ = 90 s.
  Smoothing uses zero padding outside the stream, so the ends taper. Changing
  these defaults is fine for experiments, but keep the CLI flags working and
  update the README numbers if the committed chart changes.
- **Peaks:** greedy top-N selection with a minimum separation (default 600 s).
  Do not report adjacent bins as separate moments.

## Layout

```text
src/autoclipper/live_chat.py  metadata fetch, JSONL parse, pre-roll split
src/autoclipper/rate.py       binning, Gaussian smoothing, peak picking, time format
src/autoclipper/plot.py       chart rendering
src/autoclipper/cli.py        argparse commands and CSV/JSON writers
tests/test_rate.py            unit tests; no network access
out/                          committed chart + series + summary
```

## Conventions

- Keep dependencies to numpy + matplotlib. Do not introduce pandas, scipy, or a
  plotting library for a one-off; small stdlib code is preferred.
- Use type hints and dataclasses; keep functions pure where possible.
- Tests must not hit the network. Build synthetic JSONL fixtures in `tmp_path`.
- Keep the chart readable at 1600×750: dark background, raw signal visible,
  smoothed line dominant, at most three annotated peaks.
- Preserve UTF-8 when writing CSV/JSON; Japanese messages and titles are expected.
- Generated artifacts in `out/` are committed so the README renders on GitHub.

## Verification before claiming a change is done

1. `python -m pytest -q` passes.
2. `python -m autoclipper analyze LJgPVaZbTgI` succeeds from cache.
3. `out/chat_rate.png` opens and annotations are not clipped.
4. `out/summary.json` numbers match the README table.
5. `git status --short` shows no `data/` files.

## Guardrails

- Never commit `data/` or any downloaded chat dump; the replay is ~13 MB and
  may contain user content.
- Do not download full video or audio unless the task explicitly requires it.
- Do not use authenticated YouTube APIs or cookies. Public replay data via
  `yt-dlp` is sufficient for this project.
- Do not present chat rate as viewer count or unique audience size.
- When adding analytics, document the interpretation and the known gaps
  (deleted messages, waiting-room collapse, bots/spam).
