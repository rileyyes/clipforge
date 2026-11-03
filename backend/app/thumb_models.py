"""Thumbnail design schema (editable layers) and related models.

A design is a stack of layers in a 1280x720 coordinate space. AI artwork, video
frames and uploads are *image* layers referencing stored assets; typography and
graphics stay editable *text* / *shape* layers — nothing is flattened except the
generated artwork itself.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schema import now_iso
from .storage import ID_RE

THUMB_W, THUMB_H = 1280, 720
YOUTUBE_MAX_BYTES = 2 * 1024 * 1024
YOUTUBE_MIN_WIDTH = 640
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
FONTS = ("Impact", "Arial Black", "Arial", "Segoe UI", "Helvetica", "Georgia", "Verdana",
         "Trebuchet MS", "Courier New", "Comic Sans MS")
GENRES = ("cinematic", "gaming", "horror", "commentary", "reaction", "documentary",
          "educational", "funny", "minimalist", "professional", "vlog", "tutorial")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _color(v: Optional[str]) -> Optional[str]:
    if v is not None and not COLOR_RE.fullmatch(v):
        raise ValueError("colors must be #RRGGBB or #RRGGBBAA")
    return v


def _hexid(v: str) -> str:
    if not ID_RE.fullmatch(v):
        raise ValueError("ids must be 32 lowercase hex characters")
    return v


class LayerBase(Strict):
    id: str
    name: str = Field(default="", max_length=60)
    x: float = Field(ge=-5000, le=5000)
    y: float = Field(ge=-5000, le=5000)
    w: float = Field(gt=0, le=10000)
    h: float = Field(gt=0, le=10000)
    rotation: float = Field(default=0, ge=-360, le=360)
    opacity: float = Field(default=1, ge=0, le=1)
    locked: bool = False
    hidden: bool = False

    @field_validator("id")
    @classmethod
    def _v_id(cls, v: str) -> str:
        return _hexid(v)


class Crop(Strict):  # normalized source rectangle
    x: float = Field(default=0, ge=0, le=1)
    y: float = Field(default=0, ge=0, le=1)
    w: float = Field(default=1, gt=0, le=1)
    h: float = Field(default=1, gt=0, le=1)

    @model_validator(mode="after")
    def _inside(self) -> "Crop":
        if self.x + self.w > 1.0001 or self.y + self.h > 1.0001:
            raise ValueError("crop must stay inside the image")
        return self


class Filters(Strict):
    brightness: float = Field(default=100, ge=0, le=300)  # percent
    contrast: float = Field(default=100, ge=0, le=300)
    saturation: float = Field(default=100, ge=0, le=300)
    blur: float = Field(default=0, ge=0, le=40)  # px


class ImageLayer(LayerBase):
    type: Literal["image"] = "image"
    asset_id: str
    fit: Literal["cover", "contain"] = "cover"  # never stretched
    crop: Crop = Field(default_factory=Crop)
    filters: Filters = Field(default_factory=Filters)
    flip: bool = False

    @field_validator("asset_id")
    @classmethod
    def _v_asset(cls, v: str) -> str:
        return _hexid(v)


class Shadow(Strict):
    color: str = "#000000cc"
    blur: float = Field(default=12, ge=0, le=100)
    dx: float = Field(default=0, ge=-100, le=100)
    dy: float = Field(default=6, ge=-100, le=100)

    @field_validator("color")
    @classmethod
    def _v_col(cls, v: str) -> str:
        return _color(v)  # type: ignore[return-value]


class TextLayer(LayerBase):
    type: Literal["text"] = "text"
    text: str = Field(max_length=200)
    font_family: str = "Impact"
    font_weight: int = Field(default=800, ge=100, le=900)
    font_size: float = Field(default=110, ge=8, le=600)
    align: Literal["left", "center", "right"] = "left"
    letter_spacing: float = Field(default=0, ge=-20, le=100)
    line_height: float = Field(default=1.0, ge=0.6, le=3)
    uppercase: bool = True
    color: str = "#ffffff"
    stroke_color: str = "#000000"
    stroke_width: float = Field(default=10, ge=0, le=60)
    shadow: Optional[Shadow] = Field(default_factory=Shadow)

    @field_validator("font_family")
    @classmethod
    def _v_font(cls, v: str) -> str:
        if v not in FONTS:
            raise ValueError(f"font must be one of {', '.join(FONTS)}")
        return v

    @field_validator("color", "stroke_color")
    @classmethod
    def _v_col(cls, v: str) -> str:
        return _color(v)  # type: ignore[return-value]


class ShapeLayer(LayerBase):
    type: Literal["shape"] = "shape"
    shape: Literal["rect", "ellipse", "arrow", "highlight"] = "rect"
    fill: str = "#ff3b30ff"
    fill2: Optional[str] = None  # gradient end colour
    gradient: Literal["none", "linear", "radial"] = "none"
    gradient_angle: float = Field(default=0, ge=-360, le=360)
    stroke: Optional[str] = None
    stroke_width: float = Field(default=0, ge=0, le=60)
    radius: float = Field(default=0, ge=0, le=500)
    role: Literal["element", "scrim"] = "element"  # scrim = readability/separation overlay

    @field_validator("fill", "fill2", "stroke")
    @classmethod
    def _v_col(cls, v: Optional[str]) -> Optional[str]:
        return _color(v)


Layer = Annotated[Union[ImageLayer, TextLayer, ShapeLayer], Field(discriminator="type")]


class Concept(Strict):
    id: str = ""
    name: str = Field(max_length=80)
    hook: str = Field(max_length=300)
    composition: str = Field(max_length=400)
    subject: str = Field(max_length=200)
    background: str = Field(max_length=300)
    headline: str = Field(default="", max_length=60)
    palette: list[str] = Field(default_factory=list, max_length=6)
    style: str = Field(max_length=200)
    why: str = Field(max_length=600)
    workflow: Literal["ai_original", "ai_with_footage", "footage_composite"] = "footage_composite"
    workflow_reason: str = Field(default="", max_length=300)
    image_prompt: str = Field(default="", max_length=2000)
    negative_prompt: str = Field(default="", max_length=600)
    departs_from_footage: bool = False
    review_note: str = Field(default="", max_length=300)
    reference_frames: list[str] = Field(default_factory=list, max_length=4)
    layout: Literal["text_left", "text_right", "text_top", "text_bottom", "no_text"] = "text_left"
    direction: str = Field(default="", max_length=40)
    source: str = Field(default="built-in", max_length=60)

    @field_validator("palette")
    @classmethod
    def _v_pal(cls, v: list[str]) -> list[str]:
        for c in v:
            _color(c)
        return v

    @field_validator("reference_frames")
    @classmethod
    def _v_refs(cls, v: list[str]) -> list[str]:
        return [_hexid(x) for x in v]


class GenerationRecord(Strict):
    asset_id: str
    provider: str
    model: str = ""
    workflow: str
    prompt: str = Field(max_length=4000)
    negative_prompt: str = ""
    references: list[str] = Field(default_factory=list)
    external: bool = False
    consented: bool = False
    created_at: str = Field(default_factory=now_iso)


class Design(Strict):
    id: str
    name: str = Field(default="Thumbnail", min_length=1, max_length=80)
    width: int = THUMB_W
    height: int = THUMB_H
    background: str = "#101114"
    layers: list[Layer] = Field(default_factory=list, max_length=60)
    concept: Optional[Concept] = None
    generations: list[GenerationRecord] = Field(default_factory=list, max_length=200)
    edit_revision: int = 0
    timeline_fingerprint: str = ""
    # (media_id, source_in, source_out) ranges of the edit this design was made for
    timeline_coverage: list[tuple[str, float, float]] = Field(default_factory=list, max_length=5000)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("id")
    @classmethod
    def _v_id(cls, v: str) -> str:
        return _hexid(v)

    @field_validator("background")
    @classmethod
    def _v_bg(cls, v: str) -> str:
        return _color(v)  # type: ignore[return-value]

    @model_validator(mode="after")
    def _shape(self) -> "Design":
        if (self.width, self.height) != (THUMB_W, THUMB_H):
            raise ValueError("designs are 1280x720 (YouTube 16:9)")
        ids = [layer.id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate layer id")
        return self


class Version(Strict):
    id: str
    label: str = Field(max_length=80)
    created_at: str = Field(default_factory=now_iso)
    design: Design
    edit_revision: int = 0
    timeline_fingerprint: str = ""


class ThumbContext(Strict):
    """What the creator tells us about the video (always optional)."""
    title: str = Field(default="", max_length=150)
    description: str = Field(default="", max_length=2000)
    about: str = Field(default="", max_length=500)  # "what is this video about?"
    subject: str = Field(default="", max_length=200)  # main subject to feature
    genre: str = Field(default="", max_length=30)
    style_notes: str = Field(default="", max_length=500)

    @field_validator("genre")
    @classmethod
    def _v_genre(cls, v: str) -> str:
        if v and v not in GENRES:
            raise ValueError(f"genre must be one of {', '.join(GENRES)}")
        return v
