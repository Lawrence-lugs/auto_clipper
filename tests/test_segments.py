from __future__ import annotations

import numpy as np

from autoclipper.rate import RateSeries
from autoclipper.segments import auto_threshold, segment_rate


def series_from(values: list[float], bin_s: float = 10.0) -> RateSeries:
    per_min = np.asarray(values, dtype=float)
    counts = np.rint(per_min * bin_s / 60.0)
    centers = (np.arange(per_min.size) + 0.5) * bin_s
    return RateSeries(
        bin_s=bin_s,
        sigma_s=0.0,
        centers_s=centers,
        counts=counts,
        per_min=per_min.copy(),
        smooth_per_min=per_min.copy(),
    )


def test_auto_threshold_uses_baseline_and_mad():
    values = np.array([10, 10, 10, 10, 10, 30, 30], dtype=float)
    # median 10; absolute deviations are 0,0,0,0,0,20,20 -> MAD 0
    assert auto_threshold(values) == 10
    noisy = np.array([10, 11, 9, 10, 11, 9, 50], dtype=float)
    assert auto_threshold(noisy) > 10


def test_ranks_two_bursts_by_excess_intensity():
    values = [0] * 20 + [60] * 6 + [0] * 10 + [54] * 6 + [0] * 20
    result = segment_rate(
        series_from(values),
        threshold_per_min=40,
        min_duration_s=30,
        max_duration_s=600,
        merge_gap_s=60,
        top_n=5,
    )
    assert result.candidates == 2
    assert [segment.rank for segment in result.segments] == [1, 2]
    assert result.segments[0].mean_per_min == 60
    assert result.segments[1].mean_per_min == 54
    assert result.segments[0].score > result.segments[1].score


def test_hysteresis_merges_a_short_dip():
    values = [0] * 10 + [60] * 5 + [34] * 4 + [60] * 5 + [0] * 10
    result = segment_rate(
        series_from(values),
        threshold_per_min=40,
        low_factor=0.8,
        merge_gap_s=60,
        min_duration_s=30,
        max_duration_s=600,
    )
    assert result.candidates == 1
    assert result.segments[0].duration_s >= 130


def test_long_run_is_split_within_duration_bounds():
    values = [55] * 120
    result = segment_rate(
        series_from(values),
        threshold_per_min=40,
        min_duration_s=60,
        max_duration_s=300,
        top_n=10,
    )
    assert len(result.segments) > 1
    for segment in result.segments:
        assert 60 <= segment.duration_s <= 300


def test_short_blip_is_dropped():
    values = [0] * 20 + [70] * 2 + [0] * 20
    result = segment_rate(
        series_from(values),
        threshold_per_min=40,
        min_duration_s=120,
        max_duration_s=600,
    )
    assert result.candidates == 0
    assert result.segments == []


def test_top_n_limits_output():
    values = [0] * 5
    for _ in range(6):
        values += [60] * 20 + [0] * 10
    result = segment_rate(
        series_from(values),
        threshold_per_min=40,
        min_duration_s=60,
        max_duration_s=600,
        top_n=3,
    )
    assert result.candidates == 6
    assert len(result.segments) == 3
