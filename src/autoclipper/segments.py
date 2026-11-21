"""Turn the smoothed chat-rate curve into ranked candidate segments."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rate import RateSeries


@dataclass(frozen=True, slots=True)
class Segment:
    rank: int
    start_s: float
    end_s: float
    peak_s: float  # centre of the busiest 60-second window
    duration_s: float
    messages: int
    mean_per_min: float
    peak_per_min: float  # busiest 60-second window, from raw counts
    baseline_per_min: float
    score: float  # mean messages/min above baseline


@dataclass(frozen=True, slots=True)
class Segmentation:
    threshold_per_min: float
    low_threshold_per_min: float
    baseline_per_min: float
    candidates: int
    segments: list[Segment]


def robust_baseline(values: np.ndarray) -> float:
    """Median rate, resistant to the bursts we are trying to find."""

    return float(np.median(values)) if len(values) else 0.0


def robust_sigma(values: np.ndarray) -> float:
    """MAD scaled to a Gaussian-equivalent standard deviation."""

    if not len(values):
        return 0.0
    median = float(np.median(values))
    return float(1.4826 * np.median(np.abs(values - median)))


def auto_threshold(values: np.ndarray, sigma_multiplier: float = 1.25) -> float:
    """Baseline plus a multiple of robust sigma (≈40/min for this stream)."""

    return robust_baseline(values) + sigma_multiplier * robust_sigma(values)


def _hysteresis_mask(values: np.ndarray, high: float, low: float) -> np.ndarray:
    """Stay active until the rate falls below ``low``; enter at ``high``."""

    mask = np.zeros(values.size, dtype=bool)
    active = False
    for index, value in enumerate(values):
        if active:
            if value < low:
                active = False
        elif value >= high:
            active = True
        mask[index] = active
    return mask


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate(mask):
        if active and start is None:
            start = index
        elif not active and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, mask.size - 1))
    return runs


def _merge_runs(
    runs: list[tuple[int, int]], max_gap_bins: int
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in runs:
        if merged and start - merged[-1][1] - 1 <= max_gap_bins:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _split_run(
    start: int,
    end: int,
    values: np.ndarray,
    max_bins: int,
    min_bins: int,
) -> list[tuple[int, int]]:
    """Split an over-long run at its quietest point near the size limit.

    The cut is chosen from the lowest smoothed values in the allowed window,
    so a long elevated stretch is divided between bursts rather than through
    the middle of the strongest one.
    """

    pieces: list[tuple[int, int]] = []
    while end - start + 1 > max_bins:
        # Prefer a quiet point in the last 40% of the allowed window so the
        # split produces clip-sized chunks instead of many minimum-length ones.
        low = max(start + min_bins - 1, start + int(max_bins * 0.6))
        high = min(start + max_bins - 1, end - min_bins)
        if high < low:
            break
        cut = low + int(np.argmin(values[low : high + 1]))
        pieces.append((start, cut))
        start = cut + 1
    pieces.append((start, end))
    return pieces


def segment_rate(
    series: RateSeries,
    *,
    threshold_per_min: float | None = None,
    threshold_sigma: float = 1.25,
    low_factor: float = 0.8,
    merge_gap_s: float = 60.0,
    min_duration_s: float = 120.0,
    max_duration_s: float = 900.0,
    top_n: int = 5,
) -> Segmentation:
    """Find contiguous high-chat stretches and rank them by excess intensity.

    Steps: enter above threshold / leave below ``threshold * low_factor``,
    merge short gaps, split over-long runs, drop short runs, then score by the
    average rate above the stream's median rate.
    """

    if low_factor <= 0 or low_factor > 1:
        raise ValueError("low_factor must be in (0, 1]")
    if min_duration_s <= 0:
        raise ValueError("min_duration_s must be positive")
    if max_duration_s < min_duration_s:
        raise ValueError("max_duration_s must be >= min_duration_s")
    if top_n <= 0:
        raise ValueError("top_n must be positive")

    values = np.asarray(series.smooth_per_min, dtype=float)
    bin_s = float(series.bin_s)
    baseline = robust_baseline(values)
    threshold = (
        float(threshold_per_min)
        if threshold_per_min is not None
        else auto_threshold(values, threshold_sigma)
    )
    low = threshold * low_factor

    runs = _runs(_hysteresis_mask(values, threshold, low))
    runs = _merge_runs(runs, max_gap_bins=int(round(merge_gap_s / bin_s)))

    min_bins = max(1, int(np.ceil(min_duration_s / bin_s)))
    max_bins = max(min_bins, int(np.floor(max_duration_s / bin_s)))
    split_runs: list[tuple[int, int]] = []
    for start, end in runs:
        split_runs.extend(_split_run(start, end, values, max_bins, min_bins))

    candidates = 0
    segments: list[Segment] = []
    for start, end in split_runs:
        if end - start + 1 < min_bins:
            continue
        candidates += 1

        start_s = max(0.0, float(series.centers_s[start] - bin_s / 2.0))
        end_s = float(series.centers_s[end] + bin_s / 2.0)
        duration_s = end_s - start_s
        messages = int(series.counts[start : end + 1].sum())
        mean_per_min = messages * 60.0 / duration_s if duration_s else 0.0

        # Busiest one-minute window inside the segment, from raw counts.  This
        # stays meaningful at stream boundaries where the smoothed curve tapers.
        window_bins = max(1, int(round(60.0 / bin_s)))
        window_bins = min(window_bins, end - start + 1)
        counts = series.counts[start : end + 1]
        if window_bins == counts.size:
            peak_count = float(counts.sum())
            peak_start = start
        else:
            cumulative = np.concatenate(([0.0], np.cumsum(counts)))
            totals = cumulative[window_bins:] - cumulative[:-window_bins]
            best = int(np.argmax(totals))
            peak_count = float(totals[best])
            peak_start = start + best
        peak_per_min = peak_count * 60.0 / (window_bins * bin_s)
        peak_s = float(
            series.centers_s[peak_start] + (window_bins - 1) * bin_s / 2.0
        )

        segments.append(
            Segment(
                rank=0,
                start_s=start_s,
                end_s=end_s,
                peak_s=peak_s,
                duration_s=duration_s,
                messages=messages,
                mean_per_min=mean_per_min,
                peak_per_min=peak_per_min,
                baseline_per_min=baseline,
                score=mean_per_min - baseline,
            )
        )

    segments.sort(
        key=lambda segment: (
            segment.score,
            segment.peak_per_min,
            segment.duration_s,
        ),
        reverse=True,
    )
    ranked = [
        Segment(
            rank=rank,
            start_s=segment.start_s,
            end_s=segment.end_s,
            peak_s=segment.peak_s,
            duration_s=segment.duration_s,
            messages=segment.messages,
            mean_per_min=segment.mean_per_min,
            peak_per_min=segment.peak_per_min,
            baseline_per_min=segment.baseline_per_min,
            score=segment.score,
        )
        for rank, segment in enumerate(segments[:top_n], start=1)
    ]
    return Segmentation(
        threshold_per_min=threshold,
        low_threshold_per_min=low,
        baseline_per_min=baseline,
        candidates=candidates,
        segments=ranked,
    )
