# auto_clipper

**Experiment: can we graph a YouTube chat's speed over time from a video whose chat replay actually exists?**

**Yes.** Here is the chat rate of
[`LJgPVaZbTgI`](https://youtu.be/LJgPVaZbTgI) (八雲べに, 2026-11-14, 4 h 49 min)
reconstructed from its live-chat replay:

![Chat messages per minute over the stream](out/chat_rate.png)

The grey spikes are raw counts in 10-second bins; the blue line is a 90-second
Gaussian smoothing. No transcript, video download, or YouTube Data API key was
needed — just the `live_chat` subtitle track and its video offsets.

## What the data says

- **8,153** chat items in the replay; **49** waiting-room messages were
  collapsed onto `t=0` and excluded, leaving **8,104** in-stream items.
- Average **27.9 messages/min**, median smoothed rate **26.8/min**.
- The stream is not uniformly chatty: quiet stretches sit near 10/min while
  reaction bursts reach **50–60/min** for a sustained minute.

| # | Time | Smoothed rate | Messages in ±5 min | What chat was reacting to (spot check) |
|---|------|---------------|--------------------|----------------------------------------|
| 1 | 1:21:25 | 60.3/min | 374 | A wave of agreement about "ひなーの派" |
| 2 | 2:20:15 | 57.6/min | 482 | The "final last" ending joke |
| 3 | 4:48:55 | 54.5/min | 281 | Goodbyes as the stream wraps up |
| 4 | 3:34:05 | 53.8/min | 367 | A QTE / "ガキィ！" moment |
| 5 | 0:01:45 | 48.5/min | 301 | Opening greetings |

The spot checks are informal: I read the messages in a ±20 s window around each
peak. They are enough to show the peaks are real content reactions, not just
noise from the replay parser.

## Fastest chat segments

A first segmentation baseline turns the smoothed curve into ranked candidate
ranges: contiguous stretches above a robust threshold, with short gaps merged
and blips removed. Intensity is scored as mean messages/min above the stream
median, so a long quiet stretch cannot win on length alone.

| # | Range | Length | Mean rate | Score | What it looks like |
|---|-------|--------|-----------|-------|--------------------|
| 1 | 4:47:20-4:50:00 | 2.7 min | 79.1/min | +52.4 | end-of-stream goodbyes |
| 2 | 3:32:00-3:37:30 | 5.5 min | 54.2/min | +27.4 | a QTE / "ガキィ！" moment |
| 3 | 1:19:20-1:24:00 | 4.7 min | 53.6/min | +26.8 | the "ひなーの派" agreement wave |
| 4 | 2:44:40-2:48:00 | 3.3 min | 53.4/min | +26.6 | story reactions |
| 5 | 0:12:30-0:14:40 | 2.2 min | 52.6/min | +25.9 | an early gameplay reaction |

![Top chat segments shaded on the smoothed rate](out/segments.png)

The end-of-stream burst ranks first, which is correct for raw chat speed but
wrong for clip selection. The algorithm is documented, with the related-work
review and known failure modes, in
[`docs/segmentation.md`](docs/segmentation.md).

## Method

1. **Fetch** — `yt-dlp --write-subs --sub-langs live_chat --sub-format json`
   downloads the replay as JSON Lines. Each line is a replay batch with a
   `replayChatItemAction.videoOffsetTimeMsec`.
2. **Parse** — keep text, superchat, sticker, and membership renderers; skip
   viewer-engagement banners; de-duplicate by renderer id.
3. **Drop waiting-room chat** — YouTube collapses pre-stream messages onto
   offset 0 but keeps their wall-clock `timestampUsec`. 49 messages at `t≈0`
   spanning 34 minutes of wall clock are waiting-room chat, not a 190/min burst
   at the start of the video.
4. **Bin and smooth** — count messages in 10 s bins, convert to messages/min,
   then convolve with a Gaussian kernel (σ = 90 s). Zero padding outside the
   stream keeps the ends from growing fake plateaus; the curve tapers there.
5. **Export** — PNG chart, full 10 s series, peak table, ranked segments, and
   a JSON summary.

Why smoothing at all? A live chat is a point process: per-second counts are
almost all zeros with occasional spikes. Binning to 10 s makes the spikes
visible; smoothing makes the trend readable without hiding the raw signal.

## Reproduce

Requirements: Python ≥ 3.11, [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) on
`PATH`, and network access to YouTube.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install yt-dlp

python -m autoclipper fetch   https://youtu.be/LJgPVaZbTgI
python -m autoclipper analyze https://youtu.be/LJgPVaZbTgI
python -m pytest
```

If you do not install the package, prefix commands with `$env:PYTHONPATH="src"`
(PowerShell) and run `python -m autoclipper ...` from the repository root.

Useful options:

```text
--bin-s 10              raw bin width in seconds
--sigma-s 90            Gaussian smoothing sigma in seconds
--min-separation-s 600  minimum distance between reported peaks
--top 5                 number of peaks to keep
--keep-preroll          do not drop waiting-room messages at t=0
--threshold 40          absolute segment threshold in msg/min
--top-segments 5        number of ranked segments to emit
```

## Documents

- [`docs/chat_rate.html`](docs/chat_rate.html) - rendered Quarto report with
  interactive Plotly charts, summary, and segment table (source:
  `docs/chat_rate.qmd`).
- [`docs/segmentation.md`](docs/segmentation.md) - segmentation algorithm,
  parameter table, related work, results, and limitations.

Render the report through the repository's ephemeral Quarto container (it
includes Plotly):

```powershell
. $PROFILE
quarto render docs/chat_rate.qmd
```

For a local Python environment, install the docs extra with
`pip install -e ".[dev,docs]"`.

A Dev Container is included for a clean environment:

```powershell
# VS Code: "Dev Containers: Reopen in Container"
# or: docker build -f .devcontainer/Dockerfile -t auto-clipper . && docker run --rm -it -v ${PWD}:/workspace auto-clipper
```

## Outputs

| File | Contents |
|------|----------|
| `out/chat_rate.png` | chart shown above |
| `out/chat_rate.csv` | 10 s bins: raw count, raw/min, smoothed/min |
| `out/peaks.csv` | top peaks with messages in a ±5 min window |
| `out/segments.csv` | ranked segment ranges, rates, messages, scores |
| `out/segments.json` | segments plus threshold, baseline, candidate count |
| `out/segments.png` | top segments shaded on the smoothed rate |
| `out/summary.json` | video metadata, counts, rates, peaks, segments |

Raw replays land in `data/` and are git-ignored (13 MB for this stream).

## Caveats

- **A replay must exist.** Videos with chat disabled, cleared chat, or no
  archive simply have no `live_chat` track; `yt-dlp` will report that.
- **Replays are not complete archives.** Deleted, held-for-review, or filtered
  messages are absent, and very large streams can have gaps.
- **Offsets are video time**, not wall-clock time. The waiting-room collapse is
  detected heuristically (near-zero offset plus a wall-clock span ≥ 60 s); it
  can be disabled with `--keep-preroll`.
- **Edge tapering.** Zero padding means the first and last minutes are smoothed
  with less context. Treat boundary values as lower bounds; segment means use
  raw counts, so an end-of-stream segment can score above the smoothed curve.
- **Segments are chat energy, not clip quality.** Greetings and goodbyes can
  outrank content reactions. Exclude stream boundaries or add content features
  before using segments as clip candidates.
- **Counts ≠ people.** One excited viewer can post many messages, and bots or
  spam are included. Use unique authors for an audience-size proxy.
- This is a research tool. Respect YouTube's Terms of Service and do not hammer
  the service with repeated downloads.

## Next steps

The experiment proves the data source; the analytics can now be built on top:

- burst detection from chat alone (repeated tokens, emoji walls, superchats);
- correlate chat spikes with audio loudness or scene cuts to find highlight
  moments for clipping;
- compare the threshold baseline with Kleinberg/HMM burst detection and label a
  few clips to measure precision;
- unique chatters, message length, and emote distributions per window;
- compare many streams to learn channel-specific baselines;
- serve the series to a web dashboard instead of a static PNG.

## Layout

```text
src/autoclipper/
  live_chat.py   fetch + parse live-chat JSONL, waiting-room split
  rate.py        10 s bins, Gaussian smoothing, peak picking
  segments.py    threshold segmentation, duration bounds, ranking
  plot.py        dark-theme matplotlib charts
  cli.py         `fetch` / `analyze` commands
tests/           parser, binning, smoothing, segmentation tests
docs/            Quarto report + segmentation note
out/             committed example outputs
data/            raw downloads (git-ignored)
```
