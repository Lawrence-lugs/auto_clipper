"""Render the chat-rate chart."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter, MultipleLocator

from .live_chat import VideoInfo
from .rate import RateSeries, format_hms

_BG = "#0d1117"
_PANEL = "#111820"
_GRID = "#26303b"
_TEXT = "#e6edf3"
_MUTED = "#8b949e"
_RAW = "#7d8590"
_LINE = "#4cc9f0"
_FILL = "#1f6feb"
_ACCENT = "#f78166"


def _configure_fonts() -> None:
    """Prefer a CJK-capable font when one is installed, without requiring it."""

    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in (
        "Yu Gothic",
        "Meiryo",
        "Noto Sans CJK JP",
        "Noto Sans JP",
        "MS Gothic",
        "DejaVu Sans",
    ):
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


def _hms_tick(value: float, _position: float) -> str:
    return format_hms(value * 60.0)


def plot_rate(
    series: RateSeries,
    info: VideoInfo,
    out_path: Path,
    *,
    peak_indices: list[int],
    title: str | None = None,
    preroll_count: int = 0,
) -> Path:
    """Write a dark-theme chart of raw and smoothed chat rate."""

    _configure_fonts()
    minutes = series.centers_s / 60.0
    smoothed = series.smooth_per_min
    raw = series.per_min
    peak_set = set(peak_indices)

    fig, ax = plt.subplots(figsize=(16, 7.5), dpi=150)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_PANEL)

    ax.fill_between(
        minutes,
        smoothed,
        color=_FILL,
        alpha=0.18,
        linewidth=0,
        zorder=1,
    )
    ax.plot(
        minutes,
        raw,
        color=_RAW,
        linewidth=0.55,
        alpha=0.55,
        label=f"raw ({series.bin_s:g} s bins)",
        zorder=2,
    )
    ax.plot(
        minutes,
        smoothed,
        color=_LINE,
        linewidth=1.9,
        label=f"smoothed (Gaussian, {series.sigma_s:g} s)",
        zorder=3,
    )

    median = float(np.median(smoothed))
    ax.axhline(
        median,
        color=_MUTED,
        linewidth=0.9,
        linestyle=(0, (4, 4)),
        alpha=0.8,
        zorder=1,
    )
    ax.annotate(
        f"median {median:.1f}/min",
        xy=(minutes[0], median),
        xytext=(8, -10),
        textcoords="offset points",
        ha="left",
        va="top",
        color=_MUTED,
        fontsize=8.5,
        bbox=dict(
            boxstyle="round,pad=0.25",
            facecolor=_PANEL,
            edgecolor="none",
            alpha=0.7,
        ),
    )

    ymax = max(float(np.percentile(raw, 99.5)), float(smoothed.max())) * 1.12
    ax.set_ylim(0, ymax)

    ranked = sorted(
        peak_indices, key=lambda index: float(smoothed[index]), reverse=True
    )
    for rank, index in enumerate(ranked[:3], start=1):
        x = minutes[index]
        y = float(smoothed[index])
        position = (x - minutes[0]) / max(minutes[-1] - minutes[0], 1e-9)
        if position < 0.08:
            align, offset = "left", (10, 16)
        elif position > 0.92:
            align, offset = "right", (-10, 16)
        else:
            align, offset = "center", (0, 16)
        ax.scatter([x], [y], s=34, color=_ACCENT, edgecolor=_BG, linewidth=0.8, zorder=5)
        ax.annotate(
            f"#{rank}  {format_hms(series.centers_s[index])} · {y:.0f}/min",
            xy=(x, y),
            xytext=offset,
            textcoords="offset points",
            ha=align,
            va="bottom",
            color=_ACCENT,
            fontsize=9,
            fontweight="bold",
            annotation_clip=False,
            bbox=dict(
                boxstyle="round,pad=0.35",
                facecolor=_BG,
                edgecolor=_ACCENT,
                linewidth=0.6,
                alpha=0.9,
            ),
            zorder=6,
        )

    peak_y = float(smoothed[ranked[0]]) if ranked else 0.0
    stats = (
        f"{len(series.centers_s) * series.bin_s / 3600:.2f} h stream\n"
        f"peak {peak_y:.0f} msg/min\n"
        f"mean {raw.mean():.1f} msg/min"
    )
    ax.text(
        0.012,
        0.97,
        stats,
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=_TEXT,
        fontsize=10,
        linespacing=1.5,
        bbox=dict(
            boxstyle="round,pad=0.5",
            facecolor=_BG,
            edgecolor=_GRID,
            alpha=0.85,
        ),
        zorder=7,
    )

    ax.set_title(
        title or f"{info.title} — chat messages per minute",
        loc="left",
        color=_TEXT,
        fontsize=15,
        fontweight="bold",
        pad=14,
    )
    ax.set_xlabel("video time", color=_MUTED, fontsize=10)
    ax.set_ylabel("messages per minute", color=_MUTED, fontsize=10)
    ax.xaxis.set_major_locator(MultipleLocator(30))
    ax.xaxis.set_major_formatter(FuncFormatter(_hms_tick))
    ax.tick_params(colors=_MUTED, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(_GRID)
    ax.grid(axis="y", color=_GRID, linewidth=0.7, alpha=0.7)
    ax.grid(axis="x", color=_GRID, linewidth=0.5, alpha=0.35)
    ax.margins(x=0.005)

    legend = ax.legend(
        loc="upper right",
        frameon=True,
        facecolor=_BG,
        edgecolor=_GRID,
        labelcolor=_TEXT,
        fontsize=9,
    )
    legend.get_frame().set_alpha(0.85)

    fig.text(
        0.008,
        0.012,
        f"source: youtube.com/watch?v={info.id} · live chat replay · "
        "raw bins: in-stream chat items; smoothed line is mean-based"
        + (
            f" · {preroll_count} waiting-room messages at t=0 excluded"
            if preroll_count
            else ""
        ),
        color=_MUTED,
        fontsize=8,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=_BG, bbox_inches="tight")
    plt.close(fig)
    return out_path
