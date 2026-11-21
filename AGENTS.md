# AGENTS.md

Instructions for agents working in this repository.

## What this project is

`auto_clipper` reconstructs a YouTube live chat's message rate over the video
timeline from the `live_chat` replay, smooths the spike train, and now includes
a first segmentation baseline that ranks the stretches of fastest chat.

The chat-rate experiment is done. The segmentation layer is a reviewed
baseline, not a finished highlight detector. The code is intentionally small
and is meant to be the foundation for chat-based analytics and, eventually,
highlight/clip detection. Do not add a web app, database, or scraper unless the
task explicitly asks.

## Environment

- Python 3.11+ (developed on 3.14, Windows; CI container uses 3.13).
- Runtime deps: `numpy`, `matplotlib`.
- Dev dep: `pytest`.
- Docs dep: `plotly` (the Quarto container already includes it).
- External: `yt-dlp` on `PATH` for downloading chat replays and metadata.
- Charts use the `Agg` backend and must work headless. The Quarto report uses
  interactive Plotly figures loaded from the CDN.
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
python -m autoclipper analyze https://youtu.be/LJgPVaZbTgI --threshold 50 --top-segments 10
python -m pytest -q
```

Render the Quarto report through the profile's ephemeral container:

```powershell
. $PROFILE
quarto render docs/chat_rate.qmd
```

The report uses Plotly from a CDN, so the committed HTML stays small; the
local `docs/chat_rate_files/` assets are committed alongside it.

Outputs are written to `out/`, including `segments.csv`, `segments.json`, and
`segments.png`. Raw downloads go to `data/` and are ignored by git. `fetch`
caches by video id; `analyze` reuses the cache unless `--force-fetch` is passed.

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
- **Segmentation:** entry threshold defaults to
  `median + 1.25 * 1.4826 * MAD` of the smoothed rate (≈40/min here); exit is
  `0.8 * threshold`. Merge gaps ≤ 60 s, drop runs < 120 s, split runs > 900 s
  at the quietest point in the allowed window. Score is mean raw
  messages/min above the median baseline. Keep these defaults in the CLI and
  document any change in `docs/segmentation.md`.
- **Segment stats:** `mean_per_min` uses raw counts, not the smoothed curve.
  `peak_per_min` is the busiest 60-second window from raw counts. The smoothed
  curve tapers at stream edges, so a boundary segment can have a mean above the
  curve there; this is expected.

## Layout

```text
src/autoclipper/live_chat.py  metadata fetch, JSONL parse, pre-roll split
src/autoclipper/rate.py       binning, Gaussian smoothing, peak picking, time format
src/autoclipper/segments.py   threshold segmentation, duration bounds, ranking
src/autoclipper/plot.py       chart rendering
src/autoclipper/cli.py        argparse commands and CSV/JSON writers
tests/test_rate.py            unit tests; no network access
tests/test_segments.py        synthetic segmentation tests; no network access
docs/chat_rate.qmd            Quarto report (rendered HTML + local assets committed)
docs/segmentation.md          algorithm, related work, limitations
out/                          committed chart + series + segments + summary
```

## Conventions

- Keep dependencies to numpy + matplotlib. Do not introduce pandas, scipy, or a
  plotting library for a one-off; small stdlib code is preferred.
- Use type hints and dataclasses; keep functions pure where possible.
- Tests must not hit the network. Build synthetic JSONL fixtures in `tmp_path`.
- Keep the chart readable at 1600×750: dark background, raw signal visible,
  smoothed line dominant, at most three annotated peaks.
- The Quarto report should use Plotly, not the matplotlib PNGs. Keep
  `embed-resources: false` and `include_plotlyjs="cdn"` so the HTML stays small;
  commit `docs/chat_rate_files/` with it.
- Preserve UTF-8 when writing CSV/JSON; Japanese messages and titles are expected.
- Generated artifacts in `out/` are committed so the README renders on GitHub.

## Verification before claiming a change is done

1. `python -m pytest -q` passes.
2. `python -m autoclipper analyze LJgPVaZbTgI` succeeds from cache.
3. `out/chat_rate.png` and `out/segments.png` open and annotations are not clipped.
4. `out/summary.json` numbers match the README table and the segment table.
5. `quarto render docs/chat_rate.qmd` succeeds if the report changed; open the
   HTML and confirm both Plotly charts render and the tables appear.
6. `git status --short` shows no `data/` files.

## Guardrails

- Never commit `data/` or any downloaded chat dump; the replay is ~13 MB and
  may contain user content.
- Do not download full video or audio unless the task explicitly requires it.
- Do not use authenticated YouTube APIs or cookies. Public replay data via
  `yt-dlp` is sufficient for this project.
- Do not present chat rate as viewer count or unique audience size.
- When adding analytics, document the interpretation and the known gaps
  (deleted messages, waiting-room collapse, bots/spam).
