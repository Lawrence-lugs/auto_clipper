from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from autoclipper.live_chat import ChatEvent, parse_live_chat, split_preroll
from autoclipper.rate import bin_events, format_hms, gaussian_smooth, top_peaks


def event(offset_s: float, text: str = "hi") -> ChatEvent:
    return ChatEvent(offset_s=offset_s, kind="liveChatTextMessageRenderer", text=text)


def test_bin_events_counts_and_centers():
    events = [event(0.5), event(1.5), event(9.9), event(10.1)]
    series = bin_events(events, duration_s=30, bin_s=10, sigma_s=0)

    assert series.counts.tolist() == [3, 1, 0]
    assert series.centers_s.tolist() == [5, 15, 25]
    assert series.per_min.tolist() == [18, 6, 0]


def test_events_after_duration_are_clipped_into_last_bin():
    series = bin_events([event(31)], duration_s=30, bin_s=10, sigma_s=0)
    assert series.counts.tolist() == [0, 0, 1]


def test_gaussian_smooth_keeps_a_flat_signal_flat():
    values = np.full(50, 7.0)
    smoothed = gaussian_smooth(values, sigma_bins=3)
    assert np.allclose(smoothed[10:-10], 7.0, atol=0.01)
    assert smoothed[0] < 7.0


def test_gaussian_smooth_spreads_a_spike():
    values = np.zeros(101)
    values[50] = 100.0
    smoothed = gaussian_smooth(values, sigma_bins=2)
    assert smoothed[50] == pytest.approx(smoothed.max())
    assert smoothed[50] < 100.0
    assert smoothed.sum() == pytest.approx(100.0, rel=1e-6)


def test_gaussian_smooth_at_edge_is_not_inflated():
    values = np.concatenate([np.zeros(100), [100.0]])
    smoothed = gaussian_smooth(values, sigma_bins=2)
    assert 0 < smoothed[-1] < 100
    assert smoothed[-1] > smoothed[-3]


def test_top_peaks_respects_separation():
    values = np.array([1, 9, 2, 8, 1, 10, 0], dtype=float)
    peaks = top_peaks(values, bin_s=10, min_separation_s=30, limit=3)
    assert peaks == [5, 1]


def test_format_hms():
    assert format_hms(0) == "0:00"
    assert format_hms(65) == "1:05"
    assert format_hms(3661) == "1:01:01"


def test_parse_live_chat_skips_banners_and_dedupes(tmp_path: Path):
    text_item = {
        "liveChatTextMessageRenderer": {
            "id": "a",
            "authorName": {"simpleText": "@viewer"},
            "message": {
                "runs": [
                    {"text": "hello "},
                    {"emoji": {"shortcuts": [":wave:"]}},
                ]
            },
        }
    }
    banner = {
        "liveChatViewerEngagementMessageRenderer": {
            "id": "banner",
            "message": {"runs": [{"text": "Live chat replay is on."}]},
        }
    }
    paid = {
        "liveChatPaidMessageRenderer": {
            "id": "paid",
            "authorName": {"simpleText": "@supporter"},
            "purchaseAmountText": {"simpleText": "$5.00"},
            "message": {"runs": [{"text": "nice"}]},
        }
    }

    def line(item, offset_ms):
        return json.dumps(
            {
                "replayChatItemAction": {
                    "videoOffsetTimeMsec": str(offset_ms),
                    "actions": [{"addChatItemAction": {"item": item}}],
                }
            }
        )

    path = tmp_path / "chat.live_chat.json"
    path.write_text(
        "\n".join(
            [
                line(banner, 0),
                line(text_item, 1200),
                line(text_item, 1200),
                line(paid, 30000),
            ]
        ),
        encoding="utf-8",
    )

    events, duplicates = parse_live_chat(path)

    assert duplicates == 1
    assert [(event.offset_s, event.kind) for event in events] == [
        (1.2, "liveChatTextMessageRenderer"),
        (30.0, "liveChatPaidMessageRenderer"),
    ]
    assert events[0].text == "hello :wave:"
    assert events[0].author == "@viewer"
    assert events[1].amount == "$5.00"


def test_split_preroll_detects_waiting_room_collapse():
    preroll = [
        ChatEvent(offset_s=0.0, kind="chat", wallclock_us=1_000_000),
        ChatEvent(offset_s=0.0, kind="chat", wallclock_us=121_000_000),
    ]
    live = [ChatEvent(offset_s=30.0, kind="chat", wallclock_us=121_500_000)]
    in_stream, excluded = split_preroll(preroll + live)
    assert excluded == preroll
    assert in_stream == live


def test_split_preroll_keeps_a_genuine_first_second():
    events = [
        ChatEvent(offset_s=0.2, kind="chat", wallclock_us=1_000_000),
        ChatEvent(offset_s=0.4, kind="chat", wallclock_us=1_200_000),
        ChatEvent(offset_s=30.0, kind="chat", wallclock_us=31_000_000),
    ]
    in_stream, excluded = split_preroll(events)
    assert excluded == []
    assert in_stream == events
