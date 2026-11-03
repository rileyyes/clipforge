"""Versioned project schema — the single source of truth for an edit.

The timeline is non-destructive: every clip references a source media asset and
describes *which part* of it to use and *where* it sits on the timeline. Source
media is never modified.

Time values are seconds (float). Rendering quantises them to frame / sample
boundaries from absolute timeline positions so rounding never accumulates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .storage import ID_RE

SCHEMA_VERSION = 2
EPS = 1e-3  # 1 ms tolerance for float comparisons
MIN_CLIP_DURATION = 0.04  # ~1 frame at 25 fps


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_id(v: str) -> str:
    if not ID_RE.fullmatch(v):
        raise ValueError("ids must be 32 lowercase hex characters")
    return v


class MediaAsset(Strict):
    id: str
    original_name: str = Field(max_length=200)
    stored_name: str  # server-generated: <id><ext>
    kind: Literal["video", "audio"]
    duration: float = Field(gt=0)
    size_bytes: int = Field(ge=0)
    sha256: Optional[str] = None
    container: str = ""
    has_video: bool = False
    has_audio: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    variable_frame_rate: bool = False
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    thumbnail: Optional[str] = None
    proxy: Optional[str] = None
    waveform: Optional[str] = None
    imported_at: str = Field(default_factory=now_iso)

    @field_validator("id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)


class Transform(Strict):
    x: float = Field(default=0, ge=-10000, le=10000)  # px offset from centre
    y: float = Field(default=0, ge=-10000, le=10000)
    scale: float = Field(default=1, gt=0.01, le=10)
    rotation: float = 0

    @field_validator("rotation")
    @classmethod
    def _rotation_unsupported(cls, v: float) -> float:
        if abs(v) > EPS:
            raise ValueError("rotation is not supported yet")
        return 0.0


class Clip(Strict):
    id: str
    media_id: str
    start: float = Field(ge=0)  # timeline position (s)
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    volume: float = Field(default=1.0, ge=0.0, le=4.0)
    transform: Transform = Field(default_factory=Transform)
    link_id: Optional[str] = None
    label: Optional[str] = Field(default=None, max_length=200)

    @field_validator("id", "media_id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)

    @model_validator(mode="after")
    def _range(self) -> "Clip":
        if self.source_out - self.source_in < MIN_CLIP_DURATION * self.speed - EPS:
            raise ValueError("clip is shorter than the minimum duration")
        return self

    @property
    def duration(self) -> float:
        return (self.source_out - self.source_in) / self.speed

    @property
    def end(self) -> float:
        return self.start + self.duration


class Track(Strict):
    id: str
    kind: Literal["video", "audio"]
    name: str = Field(max_length=60)
    muted: bool = False
    hidden: bool = False
    locked: bool = False
    clips: list[Clip] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)


class Timeline(Strict):
    # Video tracks: index order = stacking order (first = bottom / V1).
    tracks: list[Track] = Field(default_factory=list, max_length=32)

    @property
    def duration(self) -> float:
        ends = [c.end for t in self.tracks for c in t.clips]
        return max(ends, default=0.0)


class OutputSettings(Strict):
    width: int = Field(default=1920, ge=16, le=7680)
    height: int = Field(default=1080, ge=16, le=4320)
    fps: float = Field(default=30, ge=10, le=120)
    fit_mode: Literal["fit", "fill"] = "fit"  # letterbox vs crop; never stretch

    @model_validator(mode="after")
    def _even(self) -> "OutputSettings":
        if self.width % 2 or self.height % 2:
            raise ValueError("width and height must be even numbers (H.264 4:2:0)")
        return self


SOUNDS = ("beep", "boing", "scratch", "honk", "quack", "mute", "boom", "whoosh", "ding", "pop", "airhorn")
COLOR_HEX = r"^#[0-9a-fA-F]{6}$"


class Effect(Strict):
    """A creative effect pinned to a moment in a *source* media file.

    Because it's anchored to the source (not the timeline), it follows the clip
    when you trim, move or reorder, and simply doesn't render if that moment is cut.
    """
    id: str
    kind: Literal["censor", "zoom", "shake", "flash", "text", "sfx", "image"]
    media_id: str
    source_time: float = Field(ge=0)
    duration: float = Field(ge=0.03, le=30)
    enabled: bool = True
    origin: Literal["auto", "user"] = "user"
    sound: Optional[Literal["beep", "boing", "scratch", "honk", "quack", "mute", "boom", "whoosh",
                            "ding", "pop", "airhorn"]] = None
    volume: float = Field(default=0.8, ge=0, le=2)
    text: Optional[str] = Field(default=None, max_length=40)
    word: Optional[str] = Field(default=None, max_length=60)
    context: Optional[str] = Field(default=None, max_length=160)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    needs_review: bool = False
    scale: float = Field(default=1.25, ge=1.02, le=2.5)
    intensity: float = Field(default=0.5, ge=0, le=1)
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.5, ge=0, le=1)
    size: float = Field(default=0.12, gt=0.02, le=0.9)  # fraction of output height (text) / width (image)
    color: str = Field(default="#ffffff", pattern=COLOR_HEX)
    asset: Optional[str] = None

    @field_validator("id", "media_id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)

    @field_validator("asset")
    @classmethod
    def _v_asset(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _check_id(v)

    @model_validator(mode="after")
    def _kind_fields(self) -> "Effect":
        if self.kind in ("censor", "sfx") and self.sound is None:
            raise ValueError(f"{self.kind} effects need a sound")
        if self.kind == "sfx" and self.sound == "mute":
            raise ValueError("a sound effect can't be 'mute'")
        if self.kind == "text" and not (self.text or "").strip():
            raise ValueError("text pop-ups need text")
        if self.kind == "image" and not self.asset:
            raise ValueError("image pop-ups need an image")
        return self


class CaptionSettings(Strict):
    enabled: bool = False
    style: Literal["bold_pop", "clean", "highlight"] = "bold_pop"
    position: Literal["bottom", "middle", "top"] = "bottom"
    size: float = Field(default=0.075, ge=0.03, le=0.2)  # fraction of output height
    color: str = Field(default="#ffffff", pattern=COLOR_HEX)
    highlight: str = Field(default="#ffde00", pattern=COLOR_HEX)
    max_words: int = Field(default=4, ge=1, le=12)
    uppercase: bool = True


class Project(Strict):
    schema_version: int = SCHEMA_VERSION
    id: str
    name: str = Field(min_length=1, max_length=120)
    revision: int = 0  # bumps on every save (server or client)
    edit_revision: int = 0  # bumps only on user timeline/output saves (conflict check)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    media: list[MediaAsset] = Field(default_factory=list)
    timeline: Timeline = Field(default_factory=Timeline)
    output: OutputSettings = Field(default_factory=OutputSettings)
    effects: list[Effect] = Field(default_factory=list, max_length=5000)
    captions: CaptionSettings = Field(default_factory=CaptionSettings)

    @field_validator("id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)

    @model_validator(mode="after")
    def _semantic(self) -> "Project":
        validate_timeline(self)
        return self

    def media_by_id(self) -> dict[str, MediaAsset]:
        return {m.id: m for m in self.media}


def validate_timeline(project: Project) -> None:
    """Cross-object rules Pydantic field validation can't express."""
    media = project.media_by_id()
    eids: set[str] = set()
    for e in project.effects:
        if e.id in eids:
            raise ValueError("duplicate effect id")
        eids.add(e.id)
        m = media.get(e.media_id)
        if m is None:
            raise ValueError(f"effect {e.id} references unknown media")
        if e.source_time > m.duration + 0.05:
            raise ValueError(f"effect {e.id} is past the end of its media")
    seen_ids: set[str] = set()
    track_ids: set[str] = set()
    for track in project.timeline.tracks:
        if track.id in track_ids:
            raise ValueError("duplicate track id")
        track_ids.add(track.id)
        ordered = sorted(track.clips, key=lambda c: c.start)
        prev_end = -1.0
        for clip in ordered:
            if clip.id in seen_ids:
                raise ValueError("duplicate clip id")
            seen_ids.add(clip.id)
            asset = media.get(clip.media_id)
            if asset is None:
                raise ValueError(f"clip {clip.id} references unknown media")
            if clip.source_out > asset.duration + 0.05:
                raise ValueError(
                    f"clip {clip.id} source_out {clip.source_out:.3f}s exceeds media "
                    f"duration {asset.duration:.3f}s"
                )
            if track.kind == "video" and not asset.has_video:
                raise ValueError("audio-only media cannot be placed on a video track")
            if track.kind == "audio" and not asset.has_audio:
                raise ValueError("media without audio cannot be placed on an audio track")
            if clip.start < prev_end - EPS:
                raise ValueError(f"clips overlap on track {track.name}")
            prev_end = clip.end


def default_timeline(new_id) -> Timeline:
    return Timeline(
        tracks=[
            Track(id=new_id(), kind="video", name="V1"),
            Track(id=new_id(), kind="video", name="V2"),
            Track(id=new_id(), kind="audio", name="A1"),
            Track(id=new_id(), kind="audio", name="A2"),
        ]
    )


def migrate(data: dict) -> dict:
    """Upgrade older project documents to SCHEMA_VERSION.

    v1 is the first version; future migrations are chained here, e.g.
    ``if v == 1: data = _v1_to_v2(data)``.
    """
    v = data.get("schema_version", 1)
    if v > SCHEMA_VERSION:
        raise ValueError(
            f"project was saved by a newer version (schema {v}); please update ClipForge"
        )
    if v < 2:  # v1 -> v2: effects + captions added
        data = {**data, "effects": [], "captions": {}, "schema_version": 2}
    return data
