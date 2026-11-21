"""Bin chat events on the video timeline and smooth the resulting spikes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .live_chat import ChatEvent


@dataclass(slots=True)
class RateSeries:
    bin_s: float
    sigma_s: float
    centers_s: np.ndarray
    counts: np.ndarray
    per_min: np.ndarray
    smooth_per_min: np.ndarray


def bin_events(
    events: list[ChatEvent],
    duration_s: float,
    *,
    bin_s: float = 10.0,
    sigma_s: float = 90.0,
) -> RateSeries:
    """Count events per bin and smooth the rate with a Gaussian kernel.

    ``per_min`` and ``smooth_per_min`` are expressed in messages per minute so
    numbers stay readable regardless of the bin width.
    """

    if bin_s <= 0:
        raise ValueError("bin_s must be positive")
    if sigma_s < 0:
        raise ValueError("sigma_s must be non-negative")

    duration_s = float(duration_s)
    if duration_s <= 0:
        duration_s = max((e.offset_s for e in events), default=0.0)
    n_bins = max(1, int(np.ceil(duration_s / bin_s)))
    centers = (np.arange(n_bins) + 0.5) * bin_s

    if events:
        offsets = np.fromiter((e.offset_s for e in events), dtype=float)
        indices = np.clip((offsets / bin_s).astype(int), 0, n_bins - 1)
        counts = np.bincount(indices, minlength=n_bins).astype(float)
    else:
        counts = np.zeros(n_bins, dtype=float)

    per_min = counts * (60.0 / bin_s)
    smooth = gaussian_smooth(per_min, sigma_s / bin_s) if sigma_s else per_min.copy()
    return RateSeries(
        bin_s=bin_s,
        sigma_s=sigma_s,
        centers_s=centers,
        counts=counts,
        per_min=per_min,
        smooth_per_min=smooth,
    )


def gaussian_smooth(values: np.ndarray, sigma_bins: float) -> np.ndarray:
    """Centered Gaussian smoothing with edge padding.

    Edge padding keeps the ends of the stream from being pulled toward zero,
    which matters when the stream starts or ends mid-conversation.
    """

    values = np.asarray(values, dtype=float)
    if values.size == 0 or sigma_bins <= 0:
        return values.copy()

    radius = max(1, int(round(4.0 * sigma_bins)))
    offsets = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (offsets / sigma_bins) ** 2)
    kernel /= kernel.sum()

    # Zero padding: outside the stream there are no messages.  This keeps the
    # first/last minutes from growing a fake plateau, at the cost of tapering
    # the curve toward the two ends.
    padded = np.pad(values, radius, mode="constant")
    smoothed = np.convolve(padded, kernel, mode="same")
    return smoothed[radius : radius + values.size]


def top_peaks(
    values: np.ndarray,
    *,
    bin_s: float,
    min_separation_s: float = 600.0,
    limit: int = 5,
) -> list[int]:
    """Greedily pick the highest bins, at least ``min_separation_s`` apart."""

    if values.size == 0:
        return []
    min_gap = max(1, int(round(min_separation_s / bin_s)))
    picked: list[int] = []
    for index in np.argsort(values)[::-1]:
        index = int(index)
        if all(abs(index - other) >= min_gap for other in picked):
            picked.append(index)
            if len(picked) >= limit:
                break
    return picked


def format_hms(seconds: float) -> str:
    """Format video time as ``h:mm:ss`` (or ``m:ss`` under an hour)."""

    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
