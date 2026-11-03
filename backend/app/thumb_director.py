"""Thumbnail creative director: concepts, headlines, initial designs, refinements.

Two engines share one output contract (``Concept``):
* **Built-in director** (always available, deterministic): genre profiles ×
  creative "directions" (cinematic, curiosity, character, bold, minimal, humor,
  contrast) filled with what is actually known — your description, transcript
  keywords from the final edit, measured signals and frame colours. It never
  claims to know what it hasn't analysed; with too little context it asks.
* **Text model** (optional, ``thumb_providers.text_model``): asked for JSON
  concepts under the same honesty rules; output is validated and falls back to
  the built-in director on any failure.

Trust rules baked in: headlines only use your words / transcript words or
clearly-labelled generic framing; AI artwork is labelled a dramatization and
flagged for review; prompts forbid text and identifiable real people.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Optional

from .storage import new_id
from .thumb_models import FONTS, Concept, Design, ThumbContext

NEGATIVE = ("text, letters, words, captions, watermark, logo, signature, UI elements, blurry, "
            "low quality, cluttered composition, deformed hands, extra limbs, identifiable real person")

# ---------------------------------------------------------------- genre profiles
P = {  # palettes: dark, accent, highlight
    "horror": [["#0b0f14", "#7a0f12", "#d7e3e8"], ["#0a0a0a", "#3c6e47", "#e6f0d0"], ["#120c1c", "#5b2a86", "#f2e9ff"]],
    "gaming": [["#0d1b2a", "#00e5ff", "#ffea00"], ["#120458", "#ff2a6d", "#05d9e8"], ["#101010", "#76ff03", "#ffffff"]],
    "funny": [["#ffd60a", "#ff006e", "#1b1b1b"], ["#3a86ff", "#ffbe0b", "#ffffff"], ["#06d6a0", "#ef476f", "#1b1b1b"]],
    "cinematic": [["#0b132b", "#f4a261", "#e9edf2"], ["#1a1a1a", "#2a9d8f", "#f1faee"], ["#14110f", "#c9a227", "#f5f1e6"]],
    "documentary": [["#1d1d1b", "#d4a373", "#f5f1e6"], ["#0f1c2e", "#e9c46a", "#fdfcdc"]],
    "educational": [["#0b3954", "#ffd166", "#ffffff"], ["#ffffff", "#118ab2", "#073b4c"]],
    "commentary": [["#111111", "#ff3b30", "#ffffff"], ["#0f172a", "#facc15", "#ffffff"]],
    "reaction": [["#111111", "#ffde00", "#ffffff"], ["#1a0933", "#ff2e63", "#ffffff"]],
    "minimalist": [["#f5f5f0", "#111111", "#e63946"], ["#0d0d0d", "#f5f5f0", "#ffb703"]],
    "professional": [["#0b1f3a", "#4cc9f0", "#ffffff"], ["#f8fafc", "#0f172a", "#2563eb"]],
    "vlog": [["#fefae0", "#e76f51", "#264653"], ["#1d3557", "#f1faee", "#e63946"]],
    "tutorial": [["#0b3954", "#ffd166", "#ffffff"], ["#111827", "#22c55e", "#ffffff"]],
}
FONT_BY_GENRE = {"horror": "Impact", "gaming": "Impact", "funny": "Arial Black", "cinematic": "Georgia",
                 "documentary": "Georgia", "educational": "Arial Black", "commentary": "Impact",
                 "reaction": "Impact", "minimalist": "Helvetica", "professional": "Segoe UI",
                 "vlog": "Trebuchet MS", "tutorial": "Arial Black"}
LIGHTING = {"horror": "low-key moonlight, deep shadows, faint rim light, haze",
            "gaming": "neon rim lighting, high contrast, glowing accents",
            "funny": "bright even lighting, punchy saturated colours",
            "cinematic": "golden-hour key light, volumetric haze, anamorphic feel",
            "documentary": "natural light, grounded realistic tones, subtle film grain",
            "educational": "clean bright studio light, crisp shapes",
            "commentary": "studio key light, strong subject separation",
            "reaction": "bright key light, high contrast, vivid background",
            "minimalist": "soft diffuse light, generous negative space",
            "professional": "clean studio lighting, cool neutral tones",
            "vlog": "warm natural daylight", "tutorial": "clean bright light, high clarity"}

# creative directions. workflow: ai_original (A), ai_with_footage (B), footage_composite (C)
DIRECTIONS: dict[str, dict[str, Any]] = {
    "cinematic": dict(name="Cinematic moment", workflow="ai_original", departs=True, layout="text_left",
                      hook="A single dramatic, movie-poster moment built around {subject}",
                      composition="Wide shot, subject on the right third, strong depth, headline space on the left",
                      background="An atmospheric {setting} with depth and light falloff",
                      style="cinematic film still, dramatic lighting, rich contrast"),
    "curiosity": dict(name="The unanswered question", workflow="ai_original", departs=True, layout="text_right",
                      hook="Show just enough of {subject} to make the viewer ask what happens next",
                      composition="Subject partly hidden or seen from behind on the left, mystery in the light, space on the right",
                      background="A {setting} that hints at something just out of frame",
                      style="moody, mysterious, selective lighting, intrigue over spectacle"),
    "character": dict(name="Real reaction", workflow="footage_composite", departs=False, layout="text_right",
                      hook="The strongest real moment from your edit, framed so the emotion reads instantly",
                      composition="Your best frame large on the left two-thirds, clean separation, short headline on the right",
                      background="Your own footage, graded and separated with a soft scrim",
                      style="authentic, high clarity, punchy grade"),
    "bold": dict(name="Bold contrast", workflow="ai_with_footage", departs=True, layout="text_left",
                 hook="A loud, high-contrast poster that states the video's core idea in one glance",
                 composition="One oversized focal element, flat contrasting background, big short headline",
                 background="Simple graphic {setting} in two contrasting colours",
                 style="bold graphic poster, simplified shapes, strong colour blocking"),
    "minimal": dict(name="Minimal & iconic", workflow="ai_original", departs=True, layout="text_bottom",
                    hook="One iconic object that stands for {subject}, nothing else",
                    composition="Single centred object, lots of negative space, tiny or no headline",
                    background="Plain {setting} with a subtle gradient",
                    style="minimalist, iconic, studio product-shot clarity"),
    "humor": dict(name="Comic exaggeration", workflow="ai_with_footage", departs=True, layout="text_top",
                  hook="Exaggerate the funniest idea in the video into one absurd, readable image",
                  composition="Exaggerated subject large in frame, expressive pose, playful perspective",
                  background="A bright {setting} that sets up the joke",
                  style="playful, expressive, bright saturated colours, slightly cartoonish"),
    "contrast": dict(name="Before / after split", workflow="footage_composite", departs=False, layout="no_text",
                     hook="Two real frames from different points of your edit, side by side",
                     composition="Split frame: earlier moment left, later moment right, a clear divider",
                     background="Your own footage",
                     style="clean split layout, matched grade on both halves"),
}
GENRE_DIRECTIONS = {
    "horror": ["cinematic", "curiosity", "character", "minimal", "bold"],
    "gaming": ["bold", "character", "cinematic", "humor", "contrast"],
    "funny": ["humor", "character", "bold", "minimal"],
    "cinematic": ["cinematic", "curiosity", "minimal", "character"],
    "documentary": ["cinematic", "character", "curiosity", "minimal"],
    "educational": ["minimal", "bold", "character", "contrast"],
    "tutorial": ["contrast", "minimal", "character", "bold"],
    "commentary": ["character", "bold", "curiosity", "minimal"],
    "reaction": ["character", "humor", "bold", "curiosity"],
    "minimalist": ["minimal", "cinematic", "character"],
    "professional": ["minimal", "character", "bold", "cinematic"],
    "vlog": ["character", "cinematic", "humor", "minimal"],
}
SETTING = {"horror": "abandoned, fog-filled place", "gaming": "stylised game-world arena",
           "funny": "everyday scene", "cinematic": "vast landscape", "documentary": "real-world location",
           "educational": "clean studio backdrop", "tutorial": "clean desk / workspace",
           "commentary": "studio backdrop", "reaction": "vivid studio backdrop",
           "minimalist": "seamless backdrop", "professional": "modern office backdrop",
           "vlog": "sunlit outdoor location"}
GENERIC_HEADLINES = {
    "horror": ["DON'T LOOK BACK", "NOT ALONE?", "LIGHTS OUT"],
    "gaming": ["NO WAY", "ONE SHOT", "FINAL ROUND"],
    "funny": ["WAIT FOR IT", "WHY?!", "I CAN'T"],
    "cinematic": ["THE JOURNEY", "BEYOND"],
    "documentary": ["THE REAL STORY", "INSIDE"],
    "educational": ["EXPLAINED", "HOW IT WORKS"],
    "tutorial": ["STEP BY STEP", "HOW TO"],
    "commentary": ["LET'S TALK", "MY TAKE"],
    "reaction": ["MY REACTION", "WAIT WHAT?"],
    "minimalist": [""], "professional": ["THE GUIDE"], "vlog": ["A DAY IN", "COME WITH ME"],
}
FILLER = set("i my me we our you your the a an and or of to in on at for with this that how why what when "
             "is are was were be it its vs video episode part ep full new official".split())


def genre_of(ctx: ThumbContext, analysis: dict) -> str:
    if ctx.genre:
        return ctx.genre
    sig = analysis.get("signals") or {}
    if sig.get("energy") == "high" and (sig.get("faces_ratio") or 0) >= 0.5:
        return "reaction"
    if sig.get("motion") == "high":
        return "gaming"
    if (sig.get("faces_ratio") or 0) >= 0.5:
        return "commentary"
    return "cinematic"


def needs_context(ctx: ThumbContext, analysis: dict) -> Optional[dict]:
    has_words = (analysis.get("transcript") or {}).get("available")
    has_vision = bool(analysis.get("vision"))
    if ctx.about.strip() or ctx.title.strip() or has_words or has_vision:
        return None
    return {"reason": "I can see the edit's pacing, colours and frames, but I can't tell what the video is "
                      "about (no transcript or description). Tell me briefly so the concepts are accurate.",
            "fields": ["about", "genre", "title", "subject"]}


# ---------------------------------------------------------------- headlines
def headlines(ctx: ThumbContext, analysis: dict, genre: str, n: int = 6) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    def add(text: str, basis: str):
        t = re.sub(r"\s+", " ", text).strip().upper()
        if not t or t in seen or len(t) > 26 or len(t.split()) > 4:
            return
        if ctx.title and t == ctx.title.strip().upper():
            return  # never just repeat the video title
        seen.add(t)
        out.append({"text": t, "basis": basis})

    def key_words(s: str) -> list[str]:
        return [w for w in re.findall(r"[A-Za-z0-9']+", s) if w.lower() not in FILLER]

    for src, basis in ((ctx.title, "from your title"), (ctx.about, "from your description")):
        kw = key_words(src)
        if 1 <= len(kw) <= 3:
            add(" ".join(kw), basis)
        elif len(kw) > 3:
            nums = [w for w in kw if any(ch.isdigit() for ch in w)]
            add(" ".join((nums[:1] + [w for w in kw if w not in nums])[:3]), basis)
            add(" ".join(kw[:2]), basis)
        if kw:
            add(f"{kw[-1]}?", basis)
    if ctx.subject:
        add(ctx.subject, "your main subject")
    for w in (analysis.get("transcript") or {}).get("keywords", [])[:3]:
        add(w, "said in the video")
    for g in GENERIC_HEADLINES.get(genre, []):
        if g:
            add(g, "generic framing — make sure it fits")
    return out[:n]


# ---------------------------------------------------------------- concepts
def _subject(ctx: ThumbContext, analysis: dict) -> str:
    if ctx.subject.strip():
        return ctx.subject.strip()
    if ctx.about.strip():
        return re.split(r"[.;,\n]", ctx.about.strip())[0][:120]
    if ctx.title.strip():
        return ctx.title.strip()[:120]
    kw = (analysis.get("transcript") or {}).get("keywords", [])
    return ", ".join(kw[:3]) if kw else "the video's main subject"


def build_concepts(ctx: ThumbContext, analysis: dict, *, has_image_provider: bool, seed: int = 0) -> list[Concept]:
    genre = genre_of(ctx, analysis)
    subject = _subject(ctx, analysis)
    setting = SETTING.get(genre, "fitting environment")
    dirs = GENRE_DIRECTIONS.get(genre, ["cinematic", "character", "minimal"])
    moments = [m for m in analysis.get("moments", []) if m.get("frame_asset")]
    has_frames = bool(moments)
    order = dirs[seed % len(dirs):] + dirs[: seed % len(dirs)]
    chosen: list[str] = []
    for d in order:
        if not has_frames and DIRECTIONS[d]["workflow"] == "footage_composite":
            continue
        chosen.append(d)
        if len(chosen) == 3:
            break
    # accuracy: if frames exist, make sure one concept is built from real footage
    if has_frames and not any(DIRECTIONS[d]["workflow"] == "footage_composite" for d in chosen):
        chosen[-1] = "character" if "character" not in chosen else "contrast"
    for extra in ("cinematic", "minimal", "bold", "curiosity"):
        if len(chosen) >= 3:
            break
        if extra not in chosen:
            chosen.append(extra)
    sig = analysis.get("signals") or {}
    hl = headlines(ctx, analysis, genre)
    palettes = P.get(genre, P["cinematic"])
    concepts = []
    for i, d in enumerate(chosen):
        spec = DIRECTIONS[d]
        workflow = spec["workflow"]
        reason = {"ai_original": "Original artwork reads best for this idea; it is a dramatization, not footage.",
                  "ai_with_footage": "Combines original artwork with a real frame so the thumbnail stays anchored in the video.",
                  "footage_composite": "Uses real frames from your edit — the most accurate option."}[workflow]
        if workflow != "footage_composite" and not has_image_provider:
            reason += " (Needs an image provider; until one is configured you can build it from footage instead.)"
        if workflow == "ai_with_footage" and not has_frames:
            workflow, reason = "ai_original", "No frames available from the edit, so this is fully original artwork."
        pal = list(palettes[(i + seed) % len(palettes)])
        if workflow == "footage_composite" and moments and moments[0].get("dominant_colors"):
            pal = (moments[0]["dominant_colors"][:1] + pal)[:3]
        layout = spec["layout"] if hl or spec["layout"] == "no_text" else "no_text"
        headline = "" if layout == "no_text" else hl[(i + seed) % len(hl)]["text"] if hl else ""
        why = [f"Fits a {genre} video"]
        if ctx.about:
            why.append(f"about “{ctx.about.strip()[:90]}”")
        if sig.get("energy"):
            why.append(f"with {sig['energy']}-energy audio")
        if sig.get("cuts_per_minute"):
            why.append(f"and {sig['cuts_per_minute']} cuts/min in the final edit")
        text_side = {"text_left": "left", "text_right": "right", "text_top": "top", "text_bottom": "bottom"}.get(layout)
        hook = spec["hook"].format(subject=subject)
        prompt = (f"{spec['style']}. {hook}. Composition: {spec['composition']}. "
                  f"Background: {spec['background'].format(setting=setting)}. Lighting: {LIGHTING.get(genre, '')}. "
                  f"Colour palette {', '.join(pal)}. Wide 16:9 YouTube thumbnail, one dominant focal point, "
                  f"keep key content inside the central 16:9 area"
                  + (f", clear empty space on the {text_side} for a headline" if text_side else "")
                  + ". Any characters must be fictional and non-identifiable. No text, no letters, no logos."
                  + (f" Style notes: {ctx.style_notes}." if ctx.style_notes else ""))
        refs = [m["frame_asset"] for m in moments[: (2 if d == "contrast" else 1)]] if workflow != "ai_original" else []
        if d == "contrast" and len(moments) >= 2:
            refs = [sorted(moments[:4], key=lambda m: m["time"])[0]["frame_asset"],
                    sorted(moments[:4], key=lambda m: m["time"])[-1]["frame_asset"]]
        departs = spec["departs"] and workflow != "footage_composite"
        concepts.append(Concept(
            id=new_id(), name=spec["name"], hook=hook, composition=spec["composition"], subject=subject,
            background=spec["background"].format(setting=setting) if workflow != "footage_composite" else spec["background"],
            headline=headline, palette=pal, style=f"{spec['style']} — {LIGHTING.get(genre, '')}",
            why=" ".join(why) + ". " + {"cinematic": "Cinematic framing sells the mood at a glance.",
                                          "curiosity": "Withholding the payoff creates curiosity without promising anything false.",
                                          "character": "Real faces/moments from the edit build trust and read well small.",
                                          "bold": "One big idea and colour contrast stay legible at phone size.",
                                          "minimal": "A single icon is memorable and uncluttered.",
                                          "humor": "Exaggeration signals the comedy instantly.",
                                          "contrast": "Two real moments show the change without claiming more than the video shows."}[d],
            workflow=workflow, workflow_reason=reason, image_prompt=prompt if workflow != "footage_composite" else "",
            negative_prompt=NEGATIVE if workflow != "footage_composite" else "",
            departs_from_footage=departs,
            review_note=("Original artwork is a dramatization, not footage — check it reflects what actually "
                         "happens in the video." if departs else ""),
            reference_frames=refs, layout=layout, direction=d, source="built-in director"))
    return concepts


def combine(a: Concept, b: Concept) -> Concept:
    c = a.model_copy(deep=True)
    c.id = new_id()
    c.name = f"{a.name} × {b.name}"[:80]
    c.background, c.palette, c.style = b.background, b.palette, b.style
    c.composition = f"{a.composition}; styled like: {b.composition}"[:400]
    if c.workflow != "footage_composite":
        c.image_prompt = (f"{b.style}. {a.hook}. Composition: {a.composition}. Background: {b.background}. "
                          f"Colour palette {', '.join(b.palette)}. Wide 16:9 YouTube thumbnail, one dominant focal point. "
                          "Any characters must be fictional and non-identifiable. No text, no letters, no logos.")[:2000]
    c.departs_from_footage = a.departs_from_footage or (b.departs_from_footage and c.workflow != "footage_composite")
    c.direction = f"{a.direction}+{b.direction}"[:40]
    c.why = f"Combines “{a.name}” (idea, subject) with “{b.name}” (look and palette)."
    return c


LLM_SYSTEM = """You are a YouTube thumbnail creative director. Return JSON: {"concepts":[...3 items...], "headlines":[...]}.
Each concept has: name, hook, composition, subject, background, headline (<=4 words, may be ""), palette (3 hex colours),
style, why, workflow ("ai_original" | "ai_with_footage" | "footage_composite"), image_prompt (no text in the image,
fictional non-identifiable people only), layout ("text_left"|"text_right"|"text_top"|"text_bottom"|"no_text"),
departs_from_footage (true if the art shows things not literally in the video).
The 3 concepts must take genuinely different creative directions.
Honesty rules: use only facts given to you; never invent events, outcomes, quotes, numbers or achievements;
headlines must not promise anything the video does not contain; if unsure, prefer curiosity over claims."""


def llm_concepts(tm, ctx: ThumbContext, analysis: dict, has_frames: bool, cancel=None) -> tuple[list[Concept], list[dict]]:
    facts = {
        "creator_context": ctx.model_dump(),
        "final_edit": {k: analysis.get(k) for k in ("final_duration", "clip_count", "signals", "format_guess")},
        "transcript_excerpt": (analysis.get("transcript") or {}).get("excerpt", "")[:1500],
        "transcript_keywords": (analysis.get("transcript") or {}).get("keywords", []),
        "vision_description": analysis.get("vision"),
        "frames_available": has_frames,
        "unknowns": analysis.get("unknowns"),
    }
    import json as _json
    data = tm.chat_json(LLM_SYSTEM, "Facts about the edited video:\n" + _json.dumps(facts, ensure_ascii=False),
                        cancel=cancel)
    out = []
    for raw in (data.get("concepts") or [])[:3]:
        raw = {k: v for k, v in raw.items() if k in Concept.model_fields}
        raw.setdefault("hook", raw.get("name", ""))
        for k in ("composition", "subject", "background", "style", "why"):
            raw.setdefault(k, "")
        raw["id"] = new_id()
        raw["source"] = f"text model ({tm.model})"
        raw["negative_prompt"] = NEGATIVE
        if raw.get("workflow") != "footage_composite" and raw.get("departs_from_footage", True):
            raw["departs_from_footage"] = True
            raw["review_note"] = "Original artwork is a dramatization — check it reflects the video."
        if not has_frames and raw.get("workflow") != "ai_original":
            raw["workflow"] = "ai_original"
        out.append(Concept.model_validate(raw))
    if len(out) < 3:
        raise ValueError("text model returned fewer than 3 concepts")
    hls = [{"text": str(h)[:26].upper(), "basis": "suggested by the text model — check it's accurate"}
           for h in (data.get("headlines") or [])[:6] if str(h).strip()]
    return out, hls


# ---------------------------------------------------------------- initial design
def _text_box(text: str, size: float) -> tuple[list[str], float, float]:
    words = text.split()
    lines = [text] if len(text) <= 13 or len(words) == 1 else [" ".join(words[: (len(words) + 1) // 2]),
                                                              " ".join(words[(len(words) + 1) // 2:])]
    w = max(len(line) for line in lines) * size * 0.58
    return lines, w, len(lines) * size * 1.0


def build_design(concept: Concept, *, background_asset: Optional[str], frame_assets: list[str],
                 genre: str, name: str = "Thumbnail") -> Design:
    W, H = 1280, 720
    layers: list[dict] = []
    pal = concept.palette or ["#101114", "#ff3b30", "#ffffff"]
    accent = pal[1] if len(pal) > 1 else "#ff3b30"
    light = pal[2] if len(pal) > 2 else "#ffffff"

    def img(asset, x, y, w, h, nm, **kw):
        layers.append({"type": "image", "id": new_id(), "name": nm, "asset_id": asset, "x": x, "y": y,
                       "w": w, "h": h, "fit": "cover", **kw})

    if concept.direction.startswith("contrast") and len(frame_assets) >= 2:
        img(frame_assets[0], 0, 0, W / 2, H, "Earlier moment (footage)")
        img(frame_assets[1], W / 2, 0, W / 2, H, "Later moment (footage)")
        layers.append({"type": "shape", "id": new_id(), "name": "Divider", "shape": "rect", "x": W / 2 - 6,
                       "y": 0, "w": 12, "h": H, "fill": light + "ff" if len(light) == 7 else light})
    elif background_asset:
        img(background_asset, 0, 0, W, H, "AI artwork" if concept.workflow != "footage_composite" else "Background (footage)",
            filters={"brightness": 100, "contrast": 108, "saturation": 108, "blur": 0})
        if concept.workflow == "ai_with_footage" and frame_assets:
            side_right = concept.layout in ("text_left",)
            fx = W * 0.42 if side_right else 0
            img(frame_assets[0], fx, 0, W * 0.58, H, "Real frame (footage)")
            layers.append({"type": "shape", "id": new_id(), "name": "Blend", "shape": "rect", "role": "scrim",
                           "x": fx - 40 if side_right else W * 0.58 - 200, "y": 0, "w": 240, "h": H,
                           "fill": "#00000000", "fill2": "#000000cc", "gradient": "linear",
                           "gradient_angle": 180 if side_right else 0})
    # readability scrim on the text side
    lay = concept.layout
    if lay != "no_text" and concept.headline:
        scrims = {"text_left": (0, 0, W * 0.6, H, 0), "text_right": (W * 0.4, 0, W * 0.6, H, 180),
                  "text_top": (0, 0, W, H * 0.5, 90), "text_bottom": (0, H * 0.5, W, H * 0.5, 270)}
        x, y, w, h, ang = scrims[lay]
        layers.append({"type": "shape", "id": new_id(), "name": "Text backdrop", "shape": "rect", "role": "scrim",
                       "x": x, "y": y, "w": w, "h": h, "fill": "#000000b3", "fill2": "#00000000",
                       "gradient": "linear", "gradient_angle": ang})
        size = 150 if len(concept.headline) <= 8 else 124 if len(concept.headline) <= 14 else 104
        lines, tw, th = _text_box(concept.headline, size)
        tw = min(tw, W * 0.56 if lay in ("text_left", "text_right") else W * 0.9)
        pos = {"text_left": (60, (H - th) / 2), "text_right": (W - 60 - tw, (H - th) / 2),
               "text_top": ((W - tw) / 2, 50), "text_bottom": ((W - tw) / 2, H - th - 50)}[lay]
        font = FONT_BY_GENRE.get(genre, "Impact")
        layers.append({"type": "text", "id": new_id(), "name": "Headline", "text": "\n".join(lines),
                       "x": pos[0], "y": pos[1], "w": tw, "h": th, "font_family": font if font in FONTS else "Impact",
                       "font_weight": 900, "font_size": size, "uppercase": True,
                       "align": "right" if lay == "text_right" else "center" if lay in ("text_top", "text_bottom") else "left",
                       "color": light if concept.workflow == "footage_composite" else "#ffffff",
                       "stroke_color": "#000000", "stroke_width": 12,
                       "shadow": {"color": "#000000cc", "blur": 18, "dx": 0, "dy": 6}})
        if concept.direction in ("bold", "educational"):
            t = layers[-1]
            layers.insert(len(layers) - 1, {"type": "shape", "id": new_id(), "name": "Accent bar", "shape": "rect",
                                            "x": t["x"] - 10, "y": t["y"] + th + 6, "w": min(tw, 380), "h": 16,
                                            "fill": accent if len(accent) == 9 else accent + "ff", "radius": 8})
    return Design.model_validate({"id": new_id(), "name": name, "background": pal[0] if len(pal[0]) in (7, 9) else "#101114",
                                  "layers": layers, "concept": concept.model_dump()})


# ---------------------------------------------------------------- refinement
RULES: list[tuple[str, dict]] = [
    (r"\b(remove|no|without|delete)\b.*\b(text|headline|title|words)\b", {"remove_text": True}),
    (r"\b(bigger|larger|zoom in|closer)\b", {"scale_subject": 1.15}),
    (r"\b(smaller|zoom out|further)\b", {"scale_subject": 0.88}),
    (r"\bdramatic\b", {"filters": {"contrast": 18, "saturation": 6, "brightness": -6}, "vignette": True,
                       "prompt": "more dramatic, high-contrast cinematic lighting, deep shadows"}),
    (r"\b(mysterious|mystery|eerie|creepy)\b", {"filters": {"brightness": -12, "saturation": -15}, "vignette": True,
                                               "prompt": "mysterious, low-key lighting, fog, partially hidden subject"}),
    (r"\b(funnier|funny|playful|goofy)\b", {"filters": {"saturation": 18, "brightness": 6},
                                           "prompt": "playful, comedic, exaggerated, bright saturated colours"}),
    (r"\bcinematic\b", {"filters": {"contrast": 10, "saturation": -5},
                        "prompt": "cinematic film still, anamorphic lighting, shallow depth of field"}),
    (r"\b(colou?rful|vibrant|saturated)\b", {"filters": {"saturation": 25}, "prompt": "vibrant, colourful palette"}),
    (r"\b(brighter|lighter)\b", {"filters": {"brightness": 12}}),
    (r"\b(darker|moodier)\b", {"filters": {"brightness": -12}}),
    (r"\b(cleaner|simpler|less clutter|declutter|minimal)\b", {"declutter": True,
                                                              "prompt": "clean simple composition, single focal point, uncluttered"}),
    (r"generic ai|less ai|more real|realistic|natural", {"prompt": "photographic, natural textures, subtle film grain, "
                                                         "imperfect real-world lighting, not glossy or airbrushed",
                                                         "negative": "plastic skin, airbrushed, oversaturated, glossy CGI"}),
    (r"\b(change|new|different)\b.*\bbackground\b", {"regenerate": True, "prompt": "new, different background"}),
    (r"\b(lighting|light)\b", {"regenerate": True, "prompt": "keep the same subject and composition, change the lighting"}),
]


def refine(design: Design, instruction: str, can_regenerate: bool, can_reference: bool) -> dict:
    d = copy.deepcopy(design.model_dump(mode="json"))
    text = instruction.lower()
    applied, notes = [], []
    prompt_bits, negative_bits = [], []
    regenerate = False
    matched = False
    for pat, act in RULES:
        if not re.search(pat, text):
            continue
        matched = True
        if act.get("remove_text"):
            before = len(d["layers"])
            d["layers"] = [l for l in d["layers"] if not (l["type"] == "text" and not l.get("locked"))]
            d["layers"] = [l for l in d["layers"] if not (l["type"] == "shape" and l.get("name") == "Text backdrop"
                                                           and not l.get("locked"))]
            applied.append(f"removed {before - len(d['layers'])} text layer(s)")
        if "scale_subject" in act:
            imgs = [l for l in d["layers"] if l["type"] == "image" and not l.get("locked") and not l.get("hidden")]
            target = imgs[-1] if imgs else None
            if target:
                f = act["scale_subject"]
                cx, cy = target["x"] + target["w"] / 2, target["y"] + target["h"] / 2
                target["w"] *= f
                target["h"] *= f
                target["x"], target["y"] = cx - target["w"] / 2, cy - target["h"] / 2
                applied.append(f"scaled “{target.get('name') or 'image'}” by {f:.0%}")
            else:
                notes.append("No unlocked image layer to resize.")
        if "filters" in act:
            for l in d["layers"]:
                if l["type"] == "image" and not l.get("locked"):
                    fl = l.setdefault("filters", {"brightness": 100, "contrast": 100, "saturation": 100, "blur": 0})
                    for k, v in act["filters"].items():
                        fl[k] = max(0, min(300, fl.get(k, 100) + v))
            applied.append("adjusted image " + ", ".join(f"{k} {'+' if v > 0 else ''}{v}" for k, v in act["filters"].items()))
        if act.get("vignette") and not any(l.get("name") == "Vignette" for l in d["layers"]):
            idx = max([i for i, l in enumerate(d["layers"]) if l["type"] == "image"], default=-1) + 1
            d["layers"].insert(idx, {"type": "shape", "id": new_id(), "name": "Vignette", "shape": "rect", "role": "scrim",
                                     "x": 0, "y": 0, "w": 1280, "h": 720, "fill": "#00000000", "fill2": "#000000aa",
                                     "gradient": "radial"})
            applied.append("added a vignette")
        if act.get("declutter"):
            before = len(d["layers"])
            d["layers"] = [l for l in d["layers"] if not (l["type"] == "shape" and l.get("role") != "scrim"
                                                           and not l.get("locked") and l.get("shape") in ("arrow", "highlight", "ellipse"))]
            if before != len(d["layers"]):
                applied.append(f"removed {before - len(d['layers'])} decorative element(s)")
        if act.get("prompt"):
            prompt_bits.append(act["prompt"])
        if act.get("negative"):
            negative_bits.append(act["negative"])
        if act.get("regenerate"):
            regenerate = True
    has_ai_art = any(l["type"] == "image" and l.get("name") == "AI artwork" for l in d["layers"])
    regen = None
    if prompt_bits and (regenerate or has_ai_art):
        if not can_regenerate:
            notes.append("Changing the artwork itself needs an image provider. I applied what I could to the "
                         "editable layers; configure a provider to regenerate the art.")
        else:
            base = (design.concept.image_prompt if design.concept else "") or ""
            regen = {"prompt": (base + " Revision: " + "; ".join(prompt_bits) + ".").strip()[:2000],
                     "negative": ", ".join(filter(None, [design.concept.negative_prompt if design.concept else "",
                                                         *negative_bits]))[:600],
                     "reference_current": can_reference}
            notes.append("The artwork will be regenerated as a new background; your text and design layers are "
                         "kept. " + ("The current artwork is sent as a reference so the subject stays similar."
                                     if can_reference else
                                     "This provider can't edit selectively, so the new art may differ more."))
    if not matched:
        notes.append("I didn't recognise that instruction. Try: more dramatic, mysterious, funnier, cinematic, "
                     "more colourful, cleaner, make the subject bigger, remove the text, change the background, "
                     "change the lighting, less like generic AI art.")
    if any(l.get("locked") for l in design.model_dump()["layers"]):
        notes.append("Locked layers were left exactly as they were.")
    return {"design": Design.model_validate(d).model_dump(mode="json"), "applied": applied, "notes": notes,
            "regenerate": regen}
