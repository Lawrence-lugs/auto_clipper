"""Command line entry point."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .live_chat import (
    ChatEvent,
    VideoInfo,
    fetch_live_chat,
    load_live_chat,
    split_preroll,
    video_id_from_url,
)
from .plot import plot_rate
from .rate import RateSeries, bin_events, format_hms, top_peaks


def _normalise_source(source: str) -> str:
    if video_id_from_url(source) and "/" not in source:
        return f"https://youtu.be/{source}"
    return source


def _cached(
    source: str,
    data_dir: Path,
    *,
    force: bool = False,
) -> tuple[VideoInfo, Path]:
    url = _normalise_source(source)
    video_id = video_id_from_url(url)
    if video_id and not force:
        info_path = data_dir / f"{video_id}.info.json"
        chat_path = data_dir / f"{video_id}.live_chat.json"
        if info_path.exists() and chat_path.exists():
            info = VideoInfo(**json.loads(info_path.read_text(encoding="utf-8")))
            return info, chat_path
    return fetch_live_chat(url, data_dir, force=force)


def _window_count(events: list[ChatEvent], center_s: float, half_width_s: float) -> int:
    return sum(
        1 for event in events if abs(event.offset_s - center_s) <= half_width_s
    )


def _write_series_csv(path: Path, series: RateSeries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "offset_s",
                "offset_hms",
                "messages",
                "raw_per_min",
                "smoothed_per_min",
            ]
        )
        for center, count, raw, smooth in zip(
            series.centers_s,
            series.counts,
            series.per_min,
            series.smooth_per_min,
        ):
            writer.writerow(
                [
                    f"{center:.1f}",
                    format_hms(center),
                    int(count),
                    f"{raw:.3f}",
                    f"{smooth:.3f}",
                ]
            )


def _write_peaks_csv(
    path: Path,
    events: list[ChatEvent],
    series: RateSeries,
    peak_indices: list[int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(peak_indices, key=lambda index: series.smooth_per_min[index], reverse=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "offset_s",
                "offset_hms",
                "smoothed_per_min",
                "messages_within_5min",
            ]
        )
        for rank, index in enumerate(ordered, start=1):
            center = float(series.centers_s[index])
            writer.writerow(
                [
                    rank,
                    f"{center:.1f}",
                    format_hms(center),
                    f"{series.smooth_per_min[index]:.3f}",
                    _window_count(events, center, 300.0),
                ]
            )


def _summary(
    info: VideoInfo,
    events: list[ChatEvent],
    series: RateSeries,
    peak_indices: list[int],
    duplicates: int,
    preroll: list[ChatEvent],
) -> dict:
    ordered = sorted(
        peak_indices, key=lambda index: series.smooth_per_min[index], reverse=True
    )
    kinds = Counter(event.kind for event in events)
    top_moments = []
    for rank, index in enumerate(ordered, start=1):
        center = float(series.centers_s[index])
        top_moments.append(
            {
                "rank": rank,
                "offset_s": round(center, 1),
                "time": format_hms(center),
                "smoothed_per_min": round(float(series.smooth_per_min[index]), 2),
                "messages_within_5min": _window_count(events, center, 300.0),
            }
        )
    return {
        "video": asdict(info),
        "chat_items": len(events) + len(preroll),
        "chat_items_analyzed": len(events),
        "chat_items_by_kind": dict(kinds),
        "duplicates_skipped": duplicates,
        "preroll_messages_excluded": len(preroll),
        "preroll_wallclock_span_s": round(
            (
                max(e.wallclock_us for e in preroll)
                - min(e.wallclock_us for e in preroll)
            )
            / 1e6,
            1,
        )
        if preroll
        else 0.0,
        "duration_s": round(info.duration_s, 3),
        "duration_hms": format_hms(info.duration_s),
        "mean_per_min": round(len(events) / (info.duration_s / 60.0), 2)
        if info.duration_s
        else None,
        "median_smoothed_per_min": round(float(np_median(series.smooth_per_min)), 2),
        "bin_s": series.bin_s,
        "sigma_s": series.sigma_s,
        "top_moments": top_moments,
    }


def np_median(values) -> float:
    # Small helper keeps the summary code above readable without importing numpy.
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def cmd_fetch(args: argparse.Namespace) -> int:
    info, chat_path = fetch_live_chat(
        _normalise_source(args.source), args.data_dir, force=args.force
    )
    print(f"{info.title} ({info.id}) — {format_hms(info.duration_s)}")
    print(f"chat replay: {chat_path} ({chat_path.stat().st_size / 1e6:.1f} MB)")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    info, chat_path = _cached(args.source, args.data_dir, force=args.force_fetch)
    chat = load_live_chat(info, chat_path)
    if not chat.events:
        print("No chat items found in the replay.", file=sys.stderr)
        return 2

    events = chat.events
    preroll: list[ChatEvent] = []
    if not args.keep_preroll:
        events, preroll = split_preroll(events)
    if not events:
        print("No in-stream chat items found in the replay.", file=sys.stderr)
        return 2

    duration_s = info.duration_s or chat.duration_s
    series = bin_events(
        events,
        duration_s,
        bin_s=args.bin_s,
        sigma_s=args.sigma_s,
    )
    peak_indices = top_peaks(
        series.smooth_per_min,
        bin_s=series.bin_s,
        min_separation_s=args.min_separation_s,
        limit=args.top,
    )

    out_dir: Path = args.out_dir
    chart_path = out_dir / "chat_rate.png"
    series_path = out_dir / "chat_rate.csv"
    peaks_path = out_dir / "peaks.csv"
    summary_path = out_dir / "summary.json"

    plot_rate(
        series,
        info,
        chart_path,
        peak_indices=peak_indices,
        preroll_count=len(preroll),
    )
    _write_series_csv(series_path, series)
    _write_peaks_csv(peaks_path, events, series, peak_indices)
    summary = _summary(
        info, events, series, peak_indices, chat.duplicates_skipped, preroll
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    top = summary["top_moments"][0]
    print(f"{info.title} ({info.id})")
    print(f"stream   {format_hms(duration_s)} · {len(events):,} in-stream chat items")
    if preroll:
        span = summary["preroll_wallclock_span_s"] / 60.0
        print(
            f"preroll  excluded {len(preroll)} waiting-room messages "
            f"(collapsed to t=0, {span:.0f} min of wall clock)"
        )
    print(
        f"rate     mean {summary['mean_per_min']:.1f}/min · "
        f"median (smoothed) {summary['median_smoothed_per_min']:.1f}/min"
    )
    print(f"peak     {top['time']} · {top['smoothed_per_min']:.0f} msg/min")
    print(f"wrote    {chart_path}, {series_path}, {peaks_path}, {summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoclipper",
        description="Graph YouTube live-chat speed over the video timeline.",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subs.add_parser(
        "fetch", help="download metadata and the live_chat replay"
    )
    fetch_parser.add_argument("source", help="YouTube URL or 11-character video id")
    fetch_parser.add_argument("--data-dir", type=Path, default=Path("data"))
    fetch_parser.add_argument("--force", action="store_true", help="re-download")
    fetch_parser.set_defaults(func=cmd_fetch)

    analyze_parser = subs.add_parser(
        "analyze", help="build the rate series, CSV files and chart"
    )
    analyze_parser.add_argument("source", help="YouTube URL or 11-character video id")
    analyze_parser.add_argument("--data-dir", type=Path, default=Path("data"))
    analyze_parser.add_argument("--out-dir", type=Path, default=Path("out"))
    analyze_parser.add_argument(
        "--bin-s", type=float, default=10.0, help="raw bin width in seconds (10)"
    )
    analyze_parser.add_argument(
        "--sigma-s",
        type=float,
        default=90.0,
        help="Gaussian smoothing sigma in seconds (90)",
    )
    analyze_parser.add_argument(
        "--min-separation-s",
        type=float,
        default=600.0,
        help="minimum distance between reported peaks in seconds (600)",
    )
    analyze_parser.add_argument(
        "--top", type=int, default=5, help="number of peaks to keep (5)"
    )
    analyze_parser.add_argument(
        "--force-fetch", action="store_true", help="re-download even if cached"
    )
    analyze_parser.add_argument(
        "--keep-preroll",
        action="store_true",
        help="keep waiting-room messages collapsed onto t=0",
    )
    analyze_parser.set_defaults(func=cmd_analyze)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
