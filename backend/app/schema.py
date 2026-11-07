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

SCHEMA_VERSION = 6
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
    rotation: float = Field(default=0, ge=-3600, le=3600)  # degrees, clockwise
    opacity: float = Field(default=1, ge=0, le=1)


class Crop(Strict):
    """Hide the picture's edges (fractions of its width/height). The rest stays put."""
    left: float = Field(default=0, ge=0, le=0.9)
    right: float = Field(default=0, ge=0, le=0.9)
    top: float = Field(default=0, ge=0, le=0.9)
    bottom: float = Field(default=0, ge=0, le=0.9)

    @model_validator(mode="after")
    def _keep_something(self) -> "Crop":
        if self.left + self.right > 0.9 + EPS or self.top + self.bottom > 0.9 + EPS:
            raise ValueError("crop must leave at least 10% of the picture")
        return self

    @property
    def active(self) -> bool:
        return max(self.left, self.right, self.top, self.bottom) > 1e-4


LOOKS = ("none", "warm", "cool", "bw", "vintage", "vivid", "faded", "cinematic", "noir")


class ColorAdjust(Strict):
    brightness: float = Field(default=0, ge=-1, le=1)
    contrast: float = Field(default=1, ge=0, le=3)
    saturation: float = Field(default=1, ge=0, le=3)
    gamma: float = Field(default=1, ge=0.1, le=4)
    temperature: float = Field(default=0, ge=-1, le=1)  # -1 cool … +1 warm
    look: Literal["none", "warm", "cool", "bw", "vintage", "vivid", "faded", "cinematic", "noir"] = "none"

    @property
    def active(self) -> bool:
        return self != ColorAdjust()


KF_LIMITS = {"scale": (0.02, 10), "x": (-10000, 10000), "y": (-10000, 10000),
             "rotation": (-3600, 3600), "opacity": (0, 1), "volume": (0, 4)}
VIDEO_KF = ("scale", "x", "y", "rotation", "opacity")
MAX_KEYFRAMES = 64


class Keyframe(Strict):
    """A value at a moment of the SOURCE media (seconds), so trims, splits and speed
    changes keep animations attached to the same picture/sound. ``ease`` shapes the
    move to the next keyframe."""
    t: float = Field(ge=0, le=86400)
    v: float
    ease: Literal["linear", "ease", "hold"] = "linear"


class Transition(Strict):
    """Transition INTO a clip from the clip right before it on the same track.
    If nothing is directly before it, it renders as a fade up from black."""
    kind: Literal["crossfade", "dip_black", "dip_white", "wipe_left", "wipe_right", "wipe_up", "wipe_down",
                  "slide_left", "slide_right", "slide_up", "slide_down", "smooth_left", "smooth_right",
                  "circle_open", "circle_close", "radial", "zoom_in", "pixelize", "blur",
                  "cover_left", "reveal_right",
                  # Phase 9
                  "whip_left", "whip_right", "spin", "glitch", "rgb_split", "light_leak",
                  "zoom_blur", "flash_cut", "shake_cut"] = "crossfade"
    duration: float = Field(default=0.5, ge=0.1, le=3.0)


COLOR_HEX = r"^#[0-9a-fA-F]{6}$"


class Watermark(Strict):
    """Your logo in a corner of the whole video (from the brand kit; the file is copied into
    the project's media/brand folder)."""
    file: str = Field(pattern=r"^logo-[0-9a-f]{16}\.png$")
    corner: Literal["tl", "tr", "bl", "br"] = "br"
    size: float = Field(default=0.12, ge=0.03, le=0.4)
    opacity: float = Field(default=0.8, ge=0.1, le=1.0)


class Chroma(Strict):
    """Green screen: make one colour see-through (FFmpeg chromakey)."""
    color: str = Field(default="#00ff00", pattern=COLOR_HEX)
    similarity: float = Field(default=0.3, ge=0.01, le=0.8)   # how close a colour must be to vanish
    blend: float = Field(default=0.08, ge=0, le=0.5)          # soft edge


class Clip(Strict):
    id: str
    media_id: str
    start: float = Field(ge=0)  # timeline position (s)
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    volume: float = Field(default=1.0, ge=0.0, le=4.0)
    transform: Transform = Field(default_factory=Transform)
    crop: Crop = Field(default_factory=Crop)
    color: ColorAdjust = Field(default_factory=ColorAdjust)
    chroma: Optional[Chroma] = None
    keyframes: dict[str, list[Keyframe]] = Field(default_factory=dict)
    link_id: Optional[str] = None
    label: Optional[str] = Field(default=None, max_length=200)
    transition_in: Optional[Transition] = None
    fade_in: float = Field(default=0, ge=0, le=10)   # video: from black, audio: volume
    fade_out: float = Field(default=0, ge=0, le=10)  # video: to black, audio: volume

    @field_validator("id", "media_id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)

    @field_validator("keyframes")
    @classmethod
    def _v_keyframes(cls, v: dict) -> dict:
        out = {}
        for prop, kfs in v.items():
            if prop not in KF_LIMITS:
                raise ValueError(f"'{prop}' can't be keyframed")
            if not kfs:
                continue
            if len(kfs) > MAX_KEYFRAMES:
                raise ValueError(f"at most {MAX_KEYFRAMES} keyframes per property")
            lo, hi = KF_LIMITS[prop]
            for a, b in zip(kfs, kfs[1:]):
                if b.t - a.t < 0.001:
                    raise ValueError("keyframes must be in time order, at least 1 ms apart")
            for k in kfs:
                if not lo <= k.v <= hi:
                    raise ValueError(f"{prop} keyframe value {k.v} is outside {lo}…{hi}")
            out[prop] = kfs
        return out

    @model_validator(mode="after")
    def _range(self) -> "Clip":
        if self.source_out - self.source_in < MIN_CLIP_DURATION * self.speed - EPS:
            raise ValueError("clip is shorter than the minimum duration")
        dur = (self.source_out - self.source_in) / self.speed
        if self.fade_in + self.fade_out > dur + EPS:
            raise ValueError("fade in + fade out can't be longer than the clip")
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
    role: Literal["dialogue", "music"] = "dialogue"  # audio tracks: music gets ducked under dialogue
    clips: list[Clip] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)




class Title(Strict):
    """A text graphic on the timeline (timeline seconds; drawn above video and captions)."""
    id: str
    start: float = Field(ge=0, le=86400)
    duration: float = Field(default=4.0, ge=0.5, le=600)
    template: Literal["lower_third", "big_title", "top_banner", "subscribe", "chapter",
                      "pop_text", "arrow", "circle", "box"] = "lower_third"
    text: str = Field(default="Your name", max_length=80)
    subtext: str = Field(default="", max_length=100)
    color: str = Field(default="#ffffff", pattern=COLOR_HEX)
    accent: str = Field(default="#ff5a3c", pattern=COLOR_HEX)
    align: Literal["left", "center", "right"] = "left"
    size: float = Field(default=1.0, ge=0.5, le=2.0)
    # Phase 15 (pop_text and the shapes; ignored by the older templates)
    x: float = Field(default=0.5, ge=0, le=1)          # centre, fraction of the width
    y: float = Field(default=0.5, ge=0, le=1)          # centre, fraction of the height
    rotation: float = Field(default=0, ge=-180, le=180)
    anim: Literal["none", "pop", "typewriter", "slide_up", "bounce"] = "pop"

    @field_validator("id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)


class BlurKey(Strict):
    """Where the blurred area is at timeline time t (fractions of the frame; x, y = top-left)."""
    t: float = Field(ge=0, le=86400)
    x: float = Field(ge=-0.5, le=1)
    y: float = Field(ge=-0.5, le=1)
    w: float = Field(ge=0.01, le=1)
    h: float = Field(ge=0.01, le=1)


class Blur(Strict):
    """Hide part of the picture (a face, a licence plate, a chat window) for a stretch of
    the timeline. One key = a fixed area; several = it moves (e.g. after tracking)."""
    id: str
    start: float = Field(ge=0, le=86400)
    duration: float = Field(default=3.0, ge=0.1, le=3600)
    mode: Literal["blur", "pixelate", "black"] = "blur"
    shape: Literal["rect", "ellipse"] = "rect"
    strength: float = Field(default=0.7, ge=0.1, le=1)
    keys: list[BlurKey] = Field(min_length=1, max_length=2000)

    @field_validator("id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)

    @field_validator("keys")
    @classmethod
    def _v_keys(cls, v: list) -> list:
        for a, b in zip(v, v[1:]):
            if b.t - a.t < 0.001:
                raise ValueError("blur keys must be in time order")
        return v


class Marker(Strict):
    """A named point on the timeline (timeline seconds). Can be used as YouTube chapters."""
    id: str
    t: float = Field(ge=0, le=86400)
    label: str = Field(default="", max_length=100)
    color: str = Field(default="#ffb703", pattern=COLOR_HEX)

    @field_validator("id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)


class Timeline(Strict):
    # Video tracks: index order = stacking order (first = bottom / V1).
    tracks: list[Track] = Field(default_factory=list, max_length=32)
    titles: list[Title] = Field(default_factory=list, max_length=500)
    blurs: list[Blur] = Field(default_factory=list, max_length=200)
    markers: list[Marker] = Field(default_factory=list, max_length=500)

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
                            "ding", "pop", "airhorn", "custom"]] = None
    sound_asset: Optional[str] = None  # sound == "custom": a sound copied from My library
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

    @field_validator("asset", "sound_asset")
    @classmethod
    def _v_asset(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _check_id(v)

    @model_validator(mode="after")
    def _kind_fields(self) -> "Effect":
        if self.kind in ("censor", "sfx") and self.sound is None:
            raise ValueError(f"{self.kind} effects need a sound")
        if self.sound == "custom" and not self.sound_asset:
            raise ValueError("a custom sound needs a sound from your library")
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


class AudioSettings(Strict):
    normalize: bool = True               # two-pass loudness normalisation
    target_lufs: float = Field(default=-14, ge=-30, le=-8)  # YouTube plays back at about -14 LUFS
    noise_reduction: Literal["off", "light", "medium", "strong"] = "off"
    enhance_voice: bool = False          # rumble cut, presence lift, gentle compression
    ducking: Literal["off", "light", "medium", "strong"] = "medium"  # music under dialogue


class CamRange(Strict):
    """A stretch of the MAIN recording (source seconds), so it stays put through cuts."""
    start: float = Field(ge=0, le=86400)
    end: float = Field(gt=0, le=86400)

    @model_validator(mode="after")
    def _order(self) -> "CamRange":
        if self.end - self.start < 0.05:
            raise ValueError("a face cam range must be at least 0.05 s long")
        return self


class CamBox(Strict):
    """Where the face cam sits, as fractions of the output frame (left, top, width, height)."""
    x: float = Field(default=0.69, ge=-0.5, le=1)
    y: float = Field(default=0.6, ge=-0.5, le=1)
    w: float = Field(default=0.28, ge=0.03, le=1)
    h: float = Field(default=0.3, ge=0.03, le=1)


CAM_CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")


class FaceCam(Strict):
    """A webcam recording that follows the main recording.

    It isn't a timeline clip: wherever the main recording is on a video track, the
    matching moment of the face cam is laid on top (cam time = main time + ``offset``).
    So every cut — yours or the AI's — applies to the face cam too."""
    enabled: bool = True
    media_id: str
    main_media_id: str
    offset: float = Field(default=0, ge=-86400, le=86400)
    corner: Literal["top_left", "top_right", "bottom_left", "bottom_right", "custom"] = "bottom_right"
    size: float = Field(default=0.28, ge=0.08, le=0.9)    # width, fraction of the frame width
    margin: float = Field(default=0.03, ge=0, le=0.2)    # gap to the frame edge, fraction of width
    box: CamBox = Field(default_factory=CamBox)          # used as-is when corner == "custom"
    crop: Crop = Field(default_factory=Crop)             # trim the cam picture (e.g. down to the face)
    shape: Literal["rect", "rounded", "circle"] = "rounded"
    border: float = Field(default=0.004, ge=0, le=0.03)  # fraction of the frame width
    border_color: str = Field(default="#ffffff", pattern=COLOR_HEX)
    shadow: bool = True
    remove_bg: bool = False
    hidden: list[CamRange] = Field(default_factory=list, max_length=500)
    full: list[CamRange] = Field(default_factory=list, max_length=500)  # cam fills the screen here

    @field_validator("media_id", "main_media_id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_id(v)


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
    audio: AudioSettings = Field(default_factory=AudioSettings)
    facecam: Optional[FaceCam] = None
    watermark: Optional["Watermark"] = None

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
    fc = project.facecam
    if fc is not None:
        cam, main = media.get(fc.media_id), media.get(fc.main_media_id)
        if cam is None or main is None:
            raise ValueError("the face cam references unknown media")
        if not cam.has_video:
            raise ValueError("the face cam needs a video file")
        if fc.media_id == fc.main_media_id:
            raise ValueError("the face cam must be a different recording from the main one")
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
            if clip.keyframes:
                allowed = VIDEO_KF if track.kind == "video" else ("volume",)
                bad = set(clip.keyframes) - set(allowed)
                if bad:
                    raise ValueError(f"{', '.join(sorted(bad))} can't be keyframed on {track.kind} clips")
            if clip.transition_in is not None:
                if track.kind != "video":
                    raise ValueError("transitions go on video clips (linked audio follows)")
                if clip.transition_in.duration > clip.duration * 0.9 + EPS:
                    raise ValueError("transition is longer than the clip")
                prev = next((c for c in ordered if abs(c.end - clip.start) < 0.02 and c is not clip), None)
                if prev is not None and clip.transition_in.duration > prev.duration * 0.9 + EPS:
                    raise ValueError("transition is longer than the previous clip")
            prev_end = clip.end


def default_timeline(new_id) -> Timeline:
    return Timeline(
        tracks=[
            Track(id=new_id(), kind="video", name="V1"),
            Track(id=new_id(), kind="video", name="V2"),
            Track(id=new_id(), kind="audio", name="A1"),
            Track(id=new_id(), kind="audio", name="A2", role="music"),
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
            f"project was saved by a newer version (schema {v}); please update RJClip"
        )
    if v < 2:  # v1 -> v2: effects + captions added
        data = {**data, "effects": [], "captions": {}, "schema_version": 2}
        v = 2
    if v < 3:  # v2 -> v3: audio settings, track roles, transitions/fades (all defaulted)
        # existing projects keep their sound exactly: no automatic normalisation or ducking
        data = {**data, "audio": {"normalize": False, "ducking": "off"}, "schema_version": 3}
    if data.get("schema_version", 3) < 4:  # v3 -> v4: crop, colour, rotation, opacity, keyframes (defaulted)
        data = {**data, "schema_version": 4}
    if data.get("schema_version", 4) < 5:  # v4 -> v5: face cam (none) and new transitions
        data = {**data, "schema_version": 5}
    if data.get("schema_version", 5) < 6:  # v5 -> v6: timeline markers (none)
        data = {**data, "schema_version": 6}
    return data


def rescale_positions(data: dict, old: dict, new: dict) -> dict:
    """Clip positions are pixels of the project's output size. When that size changes
    (e.g. exporting a 1080p design at 720p), scale every x/y offset (static and keyframed)
    so pictures stay in the same place relative to the frame."""
    kx = new["width"] / old["width"] if old.get("width") else 1.0
    ky = new["height"] / old["height"] if old.get("height") else 1.0
    if abs(kx - 1) < 1e-9 and abs(ky - 1) < 1e-9:
        return data
    for t in data.get("timeline", {}).get("tracks", []):
        for c in t.get("clips", []):
            tr = c.get("transform") or {}
            if "x" in tr:
                tr["x"] = round(tr["x"] * kx, 2)
            if "y" in tr:
                tr["y"] = round(tr["y"] * ky, 2)
            for prop, k in (("x", kx), ("y", ky)):
                for kf in (c.get("keyframes") or {}).get(prop, []) or []:
                    kf["v"] = round(kf["v"] * k, 2)
    return data
