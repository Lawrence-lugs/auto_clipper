# Top chat segments: algorithm and related work

Status: first baseline, 2026-11-21. Implemented in
`src/autoclipper/segments.py`; CLI options live in `src/autoclipper/cli.py`.

## What it does

The segmentation layer takes the 10-second chat-rate series produced by the
replay parser and returns ranked time ranges: the stretches of the video where
chat is fastest. For the sample stream it finds 10 candidate stretches above
the threshold and reports the top 5.

Example output (`out/segments.csv`):

| Rank | Range | Duration | Messages | Mean rate | Score above baseline |
|-----:|-------|---------:|---------:|----------:|---------------------:|
| 1 | 4:47:20–4:50:00 | 2.7 min | 211 | 79.1/min | +52.4/min |
| 2 | 3:32:00–3:37:30 | 5.5 min | 298 | 54.2/min | +27.4/min |
| 3 | 1:19:20–1:24:00 | 4.7 min | 250 | 53.6/min | +26.8/min |
| 4 | 2:44:40–2:48:00 | 3.3 min | 178 | 53.4/min | +26.6/min |
| 5 | 0:12:30–0:14:40 | 2.2 min | 114 | 52.6/min | +25.9/min |

The score is **mean messages per minute above the stream's median rate**. It
measures intensity, not length. A quiet 20-minute stretch cannot win just by
being long; a sustained 5-minute conversation can.

## Review of related work

Chat is an implicit crowd signal. The literature broadly agrees that message
volume rises around interesting moments, then diverges on how to turn that
into boundaries, scores, and clips.

1. **Chat-traffic peak detection.** Kim and Lee (2018) detect highlights in
   Twitch game streams from chat traffic alone: extract the message-rate
   signal, remove noise, select peaks, then set intervals around them. This is
   the closest ancestor of the baseline here. It validates the core
   assumption, but the interval-setting details are tuned to their data.
   [paper](https://www.kibme.org/resources/journal/20180731135151283.pdf)

2. **Sliding-window classification with hand features.** LIGHTOR (Jiang et
   al., ICDE 2020) classifies 25-second windows using message count, average
   message length, and message similarity, then adjusts the predicted start
   point. More features improve precision, but the method needs labelled
   highlights and a trained model.
   [paper](https://conferences.computer.org/icde/2020/pdfs/ICDE2020-5acyuqhpJ6L9P042wmjY1p/290300b810/290300b810.pdf)

3. **Interaction-weighted intervals.** CatchLive (Yang et al., CHI 2022) sums
   weighted chat messages and snapshots per interval, normalises by the log of
   concurrent viewers, and merges consecutive peak intervals. It is a strong
   reminder that raw message count conflates audience size and reaction
   intensity; viewer counts are not present in a replay, so this version cannot
   apply that correction.
   [paper](https://dl.acm.org/doi/10.1145/3491102.3517461)

4. **Probabilistic burst detection.** Kleinberg's model (KDD 2002) treats
   message arrivals as an infinite-state hidden Markov process over
   inter-arrival gaps, with a cost for raising the burst state. It produces
   hierarchical bursts and is less brittle than a fixed threshold, at the cost
   of two hard-to-tune parameters (`s`, `gamma`). It is the natural next
   algorithm to compare against this baseline.
   [paper](https://www.cs.cornell.edu/home/kleinber/bhs.pdf)

5. **Learned and multimodal approaches.** Ringer's thesis (2022) and related
   work on chat-based highlight detection use frequency, diversity, sentiment,
   and audio/visual features. They outperform count-only baselines, but require
   labels, training, and usually the video itself. That is out of scope for a
   replay-only experiment.
   [thesis](https://etheses.whiterose.ac.uk/id/eprint/32406/1/PhD_Thesis__Revised_.pdf)

6. **Practical rolling windows.** Public clip-finder tools commonly use a
   5-minute rolling window over the replay and return the top peaks with a
   small negative offset because chat reacts after the event. That is a useful
   sanity check for the time scale: a highlight is usually discussed for
   minutes, not seconds.
   [example](https://apify.com/hitokawa/youtube-livechat-highlights)

### Why this baseline

This project has one stream, no human labels, and a requirement to stay
explainable. A fixed-threshold segmentation with hysteresis is cheap, has no
training step, and exposes its decisions. It is not the most accurate method in
the literature; it is the method that can be reviewed and calibrated now. The
obvious next comparison is Kleinberg burst detection or a two-state HMM on the
same series, evaluated on hand-labelled clips.

## Algorithm

Inputs: smoothed rate `r[i]` in messages/minute at 10-second centres, raw counts
`c[i]`, and the video duration.

1. **Baseline.** `b = median(r)`. Robust to the bursts being detected. For the
   sample stream `b = 26.8/min`.
2. **Threshold.** `T = b + k * 1.4826 * MAD(r)` with `k = 1.25` by default, or
   an absolute `--threshold` value. For the sample stream `T = 40.0/min`.
   `1.4826 * MAD` is a Gaussian-equivalent robust standard deviation.
3. **Hysteresis.** Enter a segment when `r[i] >= T`; leave only when
   `r[i] < 0.8T`. This prevents a one-bin dip from splitting a single
   conversation into several fragments.
4. **Merge short gaps.** Merge adjacent runs separated by at most 60 seconds.
5. **Bound duration.** Drop runs shorter than 120 seconds. Split runs longer
   than 900 seconds at the quietest point in the last 40% of the allowed split
   window, so over-long elevated stretches become clip-sized pieces without
   cutting through their strongest moment.
6. **Score.** For each segment:
   - `start` / `end` are the outer edges of the first/last included bin.
   - `messages` is the sum of raw counts.
   - `mean_rate = messages * 60 / duration`.
   - `score = mean_rate - b` (messages/minute above baseline).
   - `peak_rate` is the busiest 60-second window from raw counts, used for
     inspection; the score deliberately uses the whole segment so a single
     spike does not win.
7. **Rank.** Sort by score descending and keep the top N (default 5).

### Parameters

| Option | Default | Effect |
|--------|--------:|--------|
| `--threshold` | auto | Absolute entry threshold in messages/min. Auto is `median + 1.25 * 1.4826 * MAD`. |
| `--low-factor` | 0.8 | Hysteresis exit threshold as a fraction of the entry threshold. |
| `--merge-gap-s` | 60 | Merge runs separated by at most this many seconds. |
| `--min-segment-s` | 120 | Discard shorter runs. |
| `--max-segment-s` | 900 | Split longer runs. |
| `--top-segments` | 5 | Number of ranked segments to emit. |

## Outputs

- `out/segments.csv` — rank, start/end in seconds and `h:mm:ss`, duration,
  peak offset, message count, mean rate, peak rate, score.
- `out/segments.json` — the same segments plus the threshold, baseline, and
  candidate count.
- `out/segments.png` — smoothed rate with the top segments shaded and a
  horizontal line for each segment's mean rate.
- `summary.json` also embeds `segmentation` and `top_segments`.

## Reading the sample result

The top five mix content reactions and structural chat bursts:

- **4:47–4:50** is the end-of-stream goodbye flood. It is genuinely the fastest
  chat in the video, but it is probably not a clip candidate.
- **3:32–3:37** overlaps a QTE / "ガキィ！" moment.
- **1:19–1:24** overlaps the "ひなーの派" agreement wave.
- **2:44–2:48** contains story reactions ("迷探偵か？", "サイコパスパターンか").
- **0:12–0:14** is an early gameplay reaction ("閃いた！？", "溶けたのか").

This is a useful property of the baseline: it finds *chat energy*, not
*interesting content*. For clipping, the next layer should either exclude
stream boundaries or classify segments by chat content and audio/visual change.

## Known limitations

- **Boundary bias.** The smoothed curve tapers at the stream edges (zero
  padding), while segment means use raw counts. That is why segment 1's mean
  (79/min) is above the smoothed curve there (~54/min). The segmentation score
  is still correct; the chart explains the difference in its footer.
- **Intensity vs volume.** A 2-minute intense burst outranks a 10-minute lively
  conversation. If the goal is total reaction volume, rank by
  `messages` or `score * duration` instead.
- **No semantics.** Emote walls, spam, and repetition all count. A unique-author
  or message-diversity feature would improve precision.
- **Threshold scale.** Absolute thresholds do not transfer between channels;
  the auto threshold is the more portable option, but it still assumes the
  baseline is stable.
- **Replay gaps.** Deleted/filtered messages are missing, so a segment can
  under-count reactions.

## Next experiments

1. Compare against Kleinberg burst detection and a two-state HMM on the same
   series.
2. Hand-label 10–20 candidate ranges for this video and measure precision at
   the top 5; tune the threshold and minimum duration against that.
3. Add unique-author rate and message-diversity features, then test whether
   they separate content bursts from greeting/goodbye bursts.
4. Add a `--context-s` padding option for clip extraction and a `--exclude-head`
   / `--exclude-tail` option for structural bursts.
5. Once several videos are processed, compare normalized scores across
   channels instead of using absolute messages/minute.
