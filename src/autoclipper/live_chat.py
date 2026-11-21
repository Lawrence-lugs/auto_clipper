"""Fetch and parse YouTube live-chat replays.

YouTube exposes a ``live_chat`` subtitle track on videos whose live chat was
kept.  ``yt-dlp`` downloads it as JSON Lines: one line per replay batch, each
carrying a ``videoOffsetTimeMsec`` (position in the video, not wall clock).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Renderers that represent something a viewer did in chat.  Viewer engagement
# banners ("Live chat replay is on...") are intentionally absent.
_CHAT_RENDERERS = {
    "liveChatTextMessageRenderer",
    "liveChatPaidMessageRenderer",
    "liveChatPaidStickerRenderer",
    "liveChatMembershipItemRenderer",
}

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIDEO_URL_RES = (
    re.compile(r"(?:youtu\.be/|v=|/shorts/|/live/)([A-Za-z0-9_-]{11})"),
)

_METADATA_TEMPLATE = (
    "%(.{id,title,channel,duration,upload_date,was_live,webpage_url})j"
)


@dataclass(frozen=True, slots=True)
class VideoInfo:
    id: str
    title: str = ""
    channel: str = ""
    duration_s: float = 0.0
    upload_date: str = ""
    was_live: bool = False
    url: str = ""


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """One viewer action, positioned by its offset into the video."""

    offset_s: float
    kind: str
    author: str = ""
    text: str = ""
    amount: str = ""
    item_id: str = ""
    wallclock_us: int = 0


@dataclass(slots=True)
class LiveChat:
    info: VideoInfo
    events: list[ChatEvent] = field(default_factory=list)
    duplicates_skipped: int = 0

    @property
    def duration_s(self) -> float:
        last = max((e.offset_s for e in self.events), default=0.0)
        return max(self.info.duration_s, last)


def video_id_from_url(url: str) -> str | None:
    """Return the 11-character video id, or ``None`` if it cannot be found."""

    if _VIDEO_ID_RE.match(url):
        return url
    for pattern in _VIDEO_URL_RES:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def _run_yt_dlp(args: Iterable[str]) -> str:
    command = ["yt-dlp", "--no-warnings", "--no-update", *args]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "yt-dlp is not installed or not on PATH; install it with "
            "`pip install yt-dlp`."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"yt-dlp failed: {(exc.stderr or exc.stdout or '').strip()}"
        ) from exc
    return result.stdout


def _metadata(url: str) -> VideoInfo:
    raw = _run_yt_dlp(["--skip-download", "--print", _METADATA_TEMPLATE, url])
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"yt-dlp returned no metadata for {url}")
    data: dict[str, Any] = json.loads(lines[-1])
    return VideoInfo(
        id=data["id"],
        title=data.get("title") or "",
        channel=data.get("channel") or "",
        duration_s=float(data.get("duration") or 0.0),
        upload_date=data.get("upload_date") or "",
        was_live=bool(data.get("was_live")),
        url=data.get("webpage_url") or url,
    )


def fetch_live_chat(
    url: str,
    data_dir: Path,
    *,
    force: bool = False,
) -> tuple[VideoInfo, Path]:
    """Download the ``live_chat`` track (cached) and return info plus path."""

    data_dir.mkdir(parents=True, exist_ok=True)
    info = _metadata(url)
    info_path = data_dir / f"{info.id}.info.json"
    chat_path = data_dir / f"{info.id}.live_chat.json"

    info_path.write_text(
        json.dumps(asdict(info), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if force or not chat_path.exists():
        _run_yt_dlp(
            [
                "--skip-download",
                "--write-subs",
                "--sub-langs",
                "live_chat",
                "--sub-format",
                "json",
                "-o",
                str(data_dir / "%(id)s.%(ext)s"),
                url,
            ]
        )

    if not chat_path.exists():
        raise RuntimeError(
            "This video has no downloadable live-chat replay. Either chat was "
            "disabled, cleared, or is not offered for this video."
        )
    return info, chat_path


def _renderer_text(renderer: dict[str, Any]) -> str:
    message = renderer.get("message") or {}
    parts: list[str] = []
    for run in message.get("runs") or []:
        if run.get("text"):
            parts.append(run["text"])
        elif shortcut := (run.get("emoji") or {}).get("shortcuts"):
            parts.append(shortcut[0])
    return "".join(parts)


def parse_live_chat(path: Path) -> tuple[list[ChatEvent], int]:
    """Parse a ``*.live_chat.json`` (JSONL) file into events.

    Returns ``(events, duplicates_skipped)``.  Messages are de-duplicated by
    renderer id because replay batches can overlap.
    """

    events: list[ChatEvent] = []
    seen_ids: set[str] = set()
    duplicates = 0

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            replay = payload.get("replayChatItemAction") or {}
            offset_s = float(replay.get("videoOffsetTimeMsec") or 0) / 1000.0

            for action in replay.get("actions") or []:
                item = (action.get("addChatItemAction") or {}).get("item") or {}
                for kind, renderer in item.items():
                    if kind not in _CHAT_RENDERERS:
                        continue
                    item_id = renderer.get("id") or ""
                    if item_id:
                        if item_id in seen_ids:
                            duplicates += 1
                            continue
                        seen_ids.add(item_id)

                    amount = (
                        (renderer.get("purchaseAmountText") or {}).get("simpleText")
                        or ""
                    )
                    text = _renderer_text(renderer)
                    if not text:
                        header = renderer.get("headerSubtext") or {}
                        text = "".join(
                            run.get("text", "") for run in header.get("runs") or []
                        )

                    events.append(
                        ChatEvent(
                            offset_s=offset_s,
                            kind=kind,
                            author=(
                                (renderer.get("authorName") or {}).get("simpleText")
                                or ""
                            ),
                            text=text,
                            amount=amount,
                            item_id=item_id,
                            wallclock_us=int(renderer.get("timestampUsec") or 0),
                        )
                    )

    events.sort(key=lambda event: event.offset_s)
    return events, duplicates


def load_live_chat(info: VideoInfo, chat_path: Path) -> LiveChat:
    events, duplicates = parse_live_chat(chat_path)
    return LiveChat(info=info, events=events, duplicates_skipped=duplicates)


def split_preroll(
    events: list[ChatEvent],
    *,
    offset_threshold_s: float = 1.0,
    wallclock_span_s: float = 60.0,
) -> tuple[list[ChatEvent], list[ChatEvent]]:
    """Separate pre-stream "waiting room" chat from in-stream chat.

    YouTube collapses waiting-room messages onto offset 0 while keeping their
    wall-clock ``timestampUsec``.  A group of near-zero-offset events whose
    wall-clock timestamps span minutes is therefore pre-roll chat, not a burst
    at the very start of the video.  Returns ``(in_stream, preroll)``.
    """

    near_zero = [e for e in events if e.offset_s < offset_threshold_s]
    wallclocks = [e.wallclock_us for e in near_zero if e.wallclock_us]
    is_preroll = bool(
        len(near_zero) >= 2
        and wallclocks
        and (max(wallclocks) - min(wallclocks)) / 1e6 >= wallclock_span_s
    )
    if not is_preroll:
        return list(events), []
    preroll_ids = {id(event) for event in near_zero}
    in_stream = [event for event in events if id(event) not in preroll_ids]
    return in_stream, near_zero


# Backwards-friendly alias for ad-hoc use.
parse_chat = parse_live_chat
