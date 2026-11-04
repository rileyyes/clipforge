"""Timeline renderer.

Strategy (chosen for long sources and many clips):

1. **Plan** — quantise every clip/gap to absolute frame and sample boundaries
   (``round(t * fps)`` / ``round(t * 48000)``). Because boundaries come from
   absolute timeline positions, rounding never accumulates: A/V drift is
   bounded to < 1 frame anywhere in the video.
2. **Segments** — each clip is rendered on its own with an input seek
   (``-ss`` before ``-i``), so a 2-hour source is never decoded end-to-end and
   no filter graph has to buffer frames for distant clips. Every segment is
   padded/trimmed to its *exact* frame/sample count.
3. **Assemble** — the base video track and each audio track are joined with the
   concat demuxer; upper video tracks are overlaid; audio tracks are mixed.

Never stretches footage: ``fit`` letterboxes, ``fill`` crops.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Literal, Optional

from . import ffmpeg as ff
from .config import Settings
from .jobs import JobContext
from .schema import Clip, MediaAsset, OutputSettings, Project, Track
from . import effects as fx
from .effects import mutes_for_clip
from . import look
from .rcache import RenderCache
from .library import project_sound
from .storage import PathSecurityError

# transition kind -> FFmpeg xfade transition (dips are done with fades instead)
XFADE = {"crossfade": "fade", "wipe_left": "wipeleft", "wipe_right": "wiperight", "wipe_up": "wipeup",
         "wipe_down": "wipedown", "slide_left": "slideleft", "slide_right": "slideright",
         "slide_up": "slideup", "slide_down": "slidedown", "smooth_left": "smoothleft",
         "smooth_right": "smoothright", "circle_open": "circleopen", "circle_close": "circleclose",
         "radial": "radial", "zoom_in": "zoomin", "pixelize": "pixelize", "blur": "hblur",
         "cover_left": "coverleft", "reveal_right": "revealright"}
DIPS = {"dip_black": "black", "dip_white": "white"}
WARP_MARGIN = 4

AUDIO_RATE = 48000
QUALITY_CRF = {"draft": 28, "standard": 21, "high": 17}


@dataclass
class Seg:
    kind: Literal["clip", "gap", "transition"]
    count: int  # frames (video) or samples (audio)
    clip: Optional[Clip] = None
    start_frame: int = 0
    head: float = 0.0        # timeline seconds skipped at the clip start (taken by a transition)
    fade_in: float = 0.0     # seconds (video: from black, audio: volume)
    fade_out: float = 0.0
    prev: Optional[Clip] = None   # transition: outgoing clip
    trans: Optional[str] = None   # transition kind
    half: float = 0.0             # transition half-length in seconds
    fade_in_color: str = "black"
    fade_out_color: str = "black"


@dataclass
class RenderPlan:
    fps: Fraction
    width: int
    height: int
    total_frames: int
    total_samples: int
    base: list[Seg] = field(default_factory=list)
    overlays: list[Seg] = field(default_factory=list)
    audio_tracks: list[list[Seg]] = field(default_factory=list)
    audio_roles: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return float(self.total_frames / self.fps)


def fps_fraction(fps: float) -> Fraction:
    common = {23.976: Fraction(24000, 1001), 29.97: Fraction(30000, 1001),
              59.94: Fraction(60000, 1001)}
    for k, v in common.items():
        if abs(fps - k) < 0.01:
            return v
    return Fraction(fps).limit_denominator(1001)


def _track_segments(clips: list[Clip], to_units, total: int) -> list[Seg]:
    segs: list[Seg] = []
    cursor = 0
    for c in sorted(clips, key=lambda c: c.start):
        a, b = to_units(c.start), to_units(c.end)
        a = max(a, cursor)  # defensive: never overlap after rounding
        if b <= a:
            continue
        if a > cursor:
            segs.append(Seg("gap", a - cursor, start_frame=cursor))
        segs.append(Seg("clip", b - a, clip=c, start_frame=a))
        cursor = b
    if total > cursor:
        segs.append(Seg("gap", total - cursor, start_frame=cursor))
    return segs


def apply_transitions(segs: list[Seg], rate, lookup) -> list[Seg]:
    """Turn clip fades and transitions into segment edits.

    A transition into clip B from the clip A directly before it takes the last
    half of A's time and the first half of B's time and becomes its own segment
    (A's tail handle crossfaded with B's head handle). With nothing directly
    before B, the transition becomes a fade up from black/silence."""
    out: list[Seg] = []
    for sg in segs:
        if sg.kind == "clip":
            sg.fade_in, sg.fade_out = sg.clip.fade_in, sg.clip.fade_out
            tr = lookup(sg.clip)
            if tr is not None:
                prev = out[-1] if out and out[-1].kind == "clip" and \
                    out[-1].start_frame + out[-1].count == sg.start_frame else None
                h = int(round(tr.duration / 2 * rate))
                if tr.kind in DIPS and prev is not None:
                    # fade the outgoing clip down to black/white (silence), then the next one up
                    prev.fade_out = max(prev.fade_out, tr.duration / 2)
                    sg.fade_in = max(sg.fade_in, tr.duration / 2)
                    prev.fade_out_color = sg.fade_in_color = DIPS[tr.kind]
                elif prev is not None and 0 < h < prev.count and h < sg.count:
                    prev.count -= h
                    prev.fade_out = 0.0
                    out.append(Seg("transition", 2 * h, clip=sg.clip, start_frame=sg.start_frame - h,
                                   prev=prev.clip, trans=tr.kind, half=float(h / rate)))
                    sg.count -= h
                    sg.start_frame += h
                    sg.head = float(h / rate)
                    sg.fade_in = 0.0
                else:
                    sg.fade_in = max(sg.fade_in, tr.duration)
                    sg.fade_in_color = DIPS.get(tr.kind, "black")
            dur = float(sg.count / rate)
            if sg.fade_in + sg.fade_out > dur:  # keep fades inside what's left of the clip
                k = dur / (sg.fade_in + sg.fade_out)
                sg.fade_in, sg.fade_out = sg.fade_in * k, sg.fade_out * k
        out.append(sg)
    return out


def plan_render(project: Project, out: OutputSettings) -> RenderPlan:
    fps = fps_fraction(out.fps)
    duration = project.timeline.duration
    if duration <= 0:
        raise ValueError("The timeline is empty — add at least one clip before exporting.")
    to_f = lambda t: int(round(t * fps))  # noqa: E731
    to_s = lambda t: int(round(t * AUDIO_RATE))  # noqa: E731
    total_frames = to_f(duration)
    total_samples = int(round(total_frames / fps * AUDIO_RATE))
    plan = RenderPlan(fps=fps, width=out.width, height=out.height,
                      total_frames=total_frames, total_samples=total_samples)

    video_tracks = [t for t in project.timeline.tracks if t.kind == "video" and not t.hidden]
    links = {c.link_id: c.transition_in for t in video_tracks for c in t.clips
             if c.link_id and c.transition_in is not None}
    if video_tracks:
        plan.base = apply_transitions(_track_segments(video_tracks[0].clips, to_f, total_frames), fps,
                                      lambda c: c.transition_in)
        for t in video_tracks[1:]:
            plan.overlays += [s for s in _track_segments(t.clips, to_f, total_frames)
                              if s.kind == "clip"]
    else:
        plan.base = [Seg("gap", total_frames)]
    for t in project.timeline.tracks:
        if t.kind == "audio" and not t.muted and t.clips:
            plan.audio_tracks.append(apply_transitions(_track_segments(t.clips, to_s, total_samples),
                                                       AUDIO_RATE, lambda c: links.get(c.link_id)))
            plan.audio_roles.append(t.role)
    return plan


def atempo_chain(speed: float) -> list[str]:
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-6:
        parts.append(f"atempo={s:.6f}")
    return parts


def _fit_chain(out: OutputSettings, scale: float) -> str:
    W, H = out.width, out.height
    if out.fit_mode == "fill":
        chain = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H}")
    else:
        chain = f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    if abs(scale - 1.0) > 1e-6:
        chain += f",scale=trunc(iw*{scale:.4f}/2)*2:trunc(ih*{scale:.4f}/2)*2"
    return chain + ",setsar=1"


def video_segment_args(src: Path, seg: Seg, out: OutputSettings, fps: Fraction,
                       on_canvas: bool, dest: Path, alpha: bool = False) -> list[str]:
    """One clip segment.

    * base track (``on_canvas``): composed on a black W×H canvas.
    * upper tracks: the fitted picture only (placed during the final encode), or, when
      ``alpha``, a full transparent canvas with rotation/scale/opacity animation baked in.
    """
    c = seg.clip
    assert c is not None
    W, H = out.width, out.height
    seek = c.source_in + seg.head * c.speed
    span = c.source_out - seek
    warp = look.needs_warp(c)
    src_t = f"({seek:.6f}+t*{c.speed:.6f})"
    head = (f"[0:v]setpts=(PTS-STARTPTS)/{c.speed:.6f},fps={fps},"
            f"{_fit_chain(out, 1.0 if warp else look.static_value(c, 'scale'))}")
    colour = look.color_filters(c.color)
    if colour:
        head += "," + ",".join(colour)
    fades = ""
    if on_canvas and seg.fade_in > 0:
        fades += f",fade=t=in:st=0:d={seg.fade_in:.3f}:color={seg.fade_in_color}"
    if on_canvas and seg.fade_out > 0:
        fades += (f",fade=t=out:st={max(0.0, float(seg.count / fps) - seg.fade_out):.3f}"
                  f":d={seg.fade_out:.3f}:color={seg.fade_out_color}")
    trim = f"tpad=stop_mode=clone:stop_duration=10,trim=end_frame={seg.count},setpts=PTS-STARTPTS"
    tail = f"{trim}{fades},format=yuv420p[v]"
    if warp:
        m = WARP_MARGIN
        chain = ",".join([head, "format=yuva444p", *look.crop_filters(c, keep_size=True),
                          f"pad=w={W + 2 * m}:h={H + 2 * m}:x=(ow-iw)/2:y=(oh-ih)/2:color=black@0",
                          look.perspective_filter(c, W, H, m, f"{seek:.6f}", float(fps)),
                          f"crop={W}:{H}:{m}:{m}",
                          *look.opacity_filters(c, seek, float(seg.count / fps), float(fps))])
        if on_canvas:
            graph = (f"{chain}[fg];color=c=black:s={W}x{H}:r={fps}[bg];"
                     f"[bg][fg]overlay=x=0:y=0:shortest=1,{tail}")
        else:
            graph = f"{chain},{trim},format=yuva420p[v]"
    elif on_canvas:
        chain = ",".join([head, *look.crop_filters(c, keep_size=False)])
        x, y = look.prop_expr(c, "x", src_t), look.prop_expr(c, "y", src_t)
        ev = "frame" if look.animated(c, "x") or look.animated(c, "y") else "init"
        graph = (f"{chain}[fg];color=c=black:s={W}x{H}:r={fps}[bg];"
                 f"[bg][fg]overlay=x='(W-w)/2+({x})+{look.crop_shift(c, 'x')}':"
                 f"y='(H-h)/2+({y})+{look.crop_shift(c, 'y')}':eval={ev}:shortest=1,{tail}")
    else:
        graph = ",".join([head, *look.crop_filters(c, keep_size=False), tail])
    enc = (["-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuva420p"] if alpha and warp else
           ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-video_track_timescale", "90000"])
    return (ff.untrusted_input_args(src, seek=seek, duration=max(span, 0.05) + 0.5)
            + ["-filter_complex", graph, "-map", "[v]", "-an",
               "-frames:v", str(seg.count), "-r", str(fps), *enc, str(dest)])


def gap_video_args(seg: Seg, out: OutputSettings, fps: Fraction, dest: Path) -> list[str]:
    return ["-f", "lavfi", "-i", f"color=c=black:s={out.width}x{out.height}:r={fps}",
            "-frames:v", str(seg.count), "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
            "-video_track_timescale", "90000", str(dest)]


def audio_segment_args(src: Path, seg: Seg, dest: Path,
                       mutes: list[tuple[float, float]] = ()) -> list[str]:
    """``mutes``: censor windows (seconds from the clip's in-point) where the original
    speech is silenced — the bleep is mixed in separately, so nothing leaks through."""
    c = seg.clip
    assert c is not None
    offset = seg.head * c.speed
    seek = c.source_in + offset
    span = c.source_out - seek
    mutes = [(a - offset, b - offset) for a, b in mutes if b - offset > 0]
    mute = []
    if mutes:
        cond = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in mutes)
        mute = ["asetpts=PTS-STARTPTS", f"volume=0:enable='{cond}'"]
    fades = []
    if seg.fade_in > 0:
        fades.append(f"afade=t=in:st=0:d={seg.fade_in:.3f}")
    if seg.fade_out > 0:
        fades.append(f"afade=t=out:st={max(0.0, seg.count / AUDIO_RATE - seg.fade_out):.3f}:d={seg.fade_out:.3f}")
    chain = mute + atempo_chain(c.speed) + [
        f"aresample={AUDIO_RATE}",
        "aformat=sample_fmts=s16:channel_layouts=stereo",
        (f"volume=volume='{look.kf_expr(c.keyframes['volume'], f'({seek:.6f}+t*{c.speed:.6f})', c.volume)}'"
         ":eval=frame" if look.animated(c, "volume") else f"volume={look.static_value(c, 'volume'):.4f}"),
        "apad", f"atrim=end_sample={seg.count}", "asetpts=PTS-STARTPTS", *fades,
    ]
    return (ff.untrusted_input_args(src, seek=seek, duration=max(span, 0.05) + 0.5)
            + ["-map", "0:a:0", "-vn", "-af", ",".join(chain),
               "-c:a", "pcm_s16le", str(dest)])


def _handles(seg: Seg) -> tuple[Seg, Seg]:
    """Outgoing clip's tail (+ handle past its out-point) and incoming clip's head
    (+ handle before its in-point). Missing handles freeze-frame / pad silence."""
    a, b, h = seg.prev, seg.clip, seg.half
    pa = a.model_copy(update={"source_in": max(0.0, a.source_out - h * a.speed),
                              "source_out": a.source_out + h * a.speed, "fade_in": 0, "fade_out": 0})
    pb = b.model_copy(update={"source_in": max(0.0, b.source_in - h * b.speed),
                              "source_out": b.source_in + h * b.speed, "fade_in": 0, "fade_out": 0})
    return Seg("clip", seg.count, clip=pa), Seg("clip", seg.count, clip=pb)


def video_transition_args(part_a: Path, part_b: Path, seg: Seg, fps: Fraction, dest: Path) -> list[str]:
    kind = XFADE.get(seg.trans or "crossfade", "fade")
    d = float(seg.count / fps)
    return ["-i", str(part_a), "-i", str(part_b), "-filter_complex",
            f"[0:v][1:v]xfade=transition={kind}:duration={d:.4f}:offset=0,"
            f"tpad=stop_mode=clone:stop_duration=1,trim=end_frame={seg.count},setpts=PTS-STARTPTS,format=yuv420p[v]",
            "-map", "[v]", "-frames:v", str(seg.count), "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-video_track_timescale", "90000", str(dest)]


def audio_transition_args(part_a: Path, part_b: Path, seg: Seg, dest: Path) -> list[str]:
    curve = "exp" if seg.trans in DIPS else "tri"
    d = seg.count / AUDIO_RATE
    return ["-i", str(part_a), "-i", str(part_b), "-filter_complex",
            f"[0:a][1:a]acrossfade=d={d:.5f}:c1={curve}:c2={curve},apad,atrim=end_sample={seg.count}[a]",
            "-map", "[a]", "-c:a", "pcm_s16le", str(dest)]


def gap_audio_args(seg: Seg, dest: Path) -> list[str]:
    return ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo",
            "-af", f"atrim=end_sample={seg.count}", "-c:a", "pcm_s16le", str(dest)]


def encoder_args(encoder: str, quality: str) -> list[str]:
    crf = QUALITY_CRF.get(quality, 21)
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p4", "-rc", "vbr", "-cq", str(crf + 2)]
    if encoder == "h264_qsv":
        return ["-c:v", encoder, "-global_quality", str(crf + 2)]
    if encoder == "h264_videotoolbox":
        return ["-c:v", encoder, "-q:v", str(max(1, 100 - crf * 2))]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-profile:v", "high"]


_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _.\-]+")


def safe_output_name(name: str) -> str:
    stem = _SAFE_NAME.sub("", Path(name or "export").stem).strip(" .")[:80] or "export"
    return stem + ".mp4"


def _write_concat(listfile: Path, names: list[str]) -> None:
    listfile.write_text("ffconcat version 1.0\n" + "".join(f"file {n}\n" for n in names), encoding="utf-8")


def render_project(ctx: JobContext, settings: Settings, project: Project,
                   project_dir: Path, filename: str, quality: str,
                   encoder_pref: str = "auto") -> dict:
    out = project.output
    plan = plan_render(project, out)
    media = project.media_by_id()
    originals = project_dir / "media" / "original"

    def src_of(clip: Clip) -> Path:
        asset: MediaAsset = media[clip.media_id]
        p = originals / asset.stored_name
        if not p.exists():
            raise FileNotFoundError(f"source media missing: {asset.original_name}")
        return p

    work = project_dir / "work" / ctx.job.id
    work.mkdir(parents=True, exist_ok=True)
    exports = project_dir / "exports"
    exports.mkdir(exist_ok=True)
    final_name = safe_output_name(filename)
    dest = exports / final_name
    n = 1
    while dest.exists():
        dest = exports / f"{Path(final_name).stem}-{n}.mp4"
        n += 1

    try:
        # ---- stage 1: segments (progress measured by output time) -------
        jobs: list[tuple[list[str], float, str]] = []
        base_names = []
        for i, s in enumerate(plan.base):
            name = f"b{i:05d}.mp4"
            base_names.append(name)
            secs = float(s.count / plan.fps)
            if s.kind == "transition":
                pa, pb = _handles(s)
                na, nb = f"b{i:05d}_ta.mp4", f"b{i:05d}_tb.mp4"
                jobs.append((video_segment_args(src_of(s.prev), pa, out, plan.fps, True, work / na), secs, na))
                jobs.append((video_segment_args(src_of(s.clip), pb, out, plan.fps, True, work / nb), secs, nb))
                jobs.append((video_transition_args(work / na, work / nb, s, plan.fps, work / name), secs, name))
                continue
            args = (video_segment_args(src_of(s.clip), s, out, plan.fps, True, work / name)
                    if s.kind == "clip" else gap_video_args(s, out, plan.fps, work / name))
            jobs.append((args, secs, name))
        overlay_names = []
        for i, s in enumerate(plan.overlays):
            warp = look.needs_warp(s.clip)
            name = f"o{i:05d}.{'mkv' if warp else 'mp4'}"
            overlay_names.append(name)
            jobs.append((video_segment_args(src_of(s.clip), s, out, plan.fps, False, work / name, alpha=warp),
                         float(s.count / plan.fps), name))
        audio_lists = []
        for ti, segs in enumerate(plan.audio_tracks):
            names = []
            for i, s in enumerate(segs):
                name = f"a{ti:02d}_{i:05d}.wav"
                names.append(name)
                if s.kind == "transition":
                    pa, pb = _handles(s)
                    na, nb = f"a{ti:02d}_{i:05d}_ta.wav", f"a{ti:02d}_{i:05d}_tb.wav"
                    jobs.append((audio_segment_args(src_of(s.prev), pa, work / na, mutes_for_clip(project, pa.clip)), 0.01, na))
                    jobs.append((audio_segment_args(src_of(s.clip), pb, work / nb, mutes_for_clip(project, pb.clip)), 0.01, nb))
                    jobs.append((audio_transition_args(work / na, work / nb, s, work / name), 0.01, name))
                    continue
                args = (audio_segment_args(src_of(s.clip), s, work / name, mutes_for_clip(project, s.clip))
                        if s.kind == "clip" else gap_audio_args(s, work / name))
                # audio is ~10x cheaper than video; weight accordingly
                jobs.append((args, s.count / AUDIO_RATE * 0.1, name))
            audio_lists.append(names)
        audio_roles = list(plan.audio_roles)

        # sound-effect / bleep lanes (non-overlapping events per lane)
        events = []
        missing_sounds = 0
        for e in project.effects:
            if not e.enabled or e.kind not in ("censor", "sfx") or e.sound in (None, "mute"):
                continue
            wins = fx.map_to_timeline(project, e, "audio") or (fx.map_to_timeline(project, e, "video")
                                                                 if e.kind == "sfx" else [])
            for w in wins:
                a = int(round(w.start * AUDIO_RATE))
                n = int(round(w.end * AUDIO_RATE)) - a
                if e.kind == "sfx":  # sound effects play their natural length
                    n = int(e.duration * AUDIO_RATE)
                n = min(n, plan.total_samples - a)
                if n > 32:
                    path = None
                    if e.sound == "custom":
                        try:
                            path = project_sound(project_dir, e.sound_asset or "")
                        except PathSecurityError:
                            path = None
                        if path is None or not path.is_file():
                            missing_sounds += 1
                            continue
                    events.append((a, n, e.sound, e.volume, path))
        lanes: list[list[tuple]] = []
        for ev in sorted(events):
            lane = next((l for l in lanes if l[-1][0] + l[-1][1] <= ev[0]), None)
            if lane is None:
                lanes.append([ev])
            else:
                lane.append(ev)
        for li, lane in enumerate(lanes[:8]):
            names, cursor = [], 0
            for k, (a, n, sound, vol, path) in enumerate(lane):
                if a > cursor:
                    nm = f"fx{li}_{k:05d}g.wav"
                    jobs.append((gap_audio_args(Seg("gap", a - cursor), work / nm), 0.01, nm))
                    names.append(nm)
                nm = f"fx{li}_{k:05d}.wav"
                jobs.append((fx.sound_args(sound, n, vol, AUDIO_RATE, work / nm, path), 0.01, nm))
                names.append(nm)
                cursor = a + n
            if plan.total_samples > cursor:
                nm = f"fx{li}_end.wav"
                jobs.append((gap_audio_args(Seg("gap", plan.total_samples - cursor), work / nm), 0.01, nm))
                names.append(nm)
            audio_lists.append(names)
            audio_roles.append("fx")

        cache = RenderCache(settings.cache_dir, settings.render_cache_bytes, settings.ffmpeg_bin)
        total_work = sum(j[1] for j in jobs) or 1.0
        seg_weight, mix_weight, final_weight = 0.5, 0.1, 0.4
        done = 0.0
        stages = 3
        ctx.stage(1, stages, f"Rendering {len(jobs)} segments")
        for args, secs, name in jobs:
            ctx.check_cancel()
            base_done = done
            key = cache.key(args, work, name)
            if cache.fetch(key, work / name):
                done += secs
                cache.reused_seconds += secs
                ctx.progress(seg_weight * done / total_work)
                continue
            ff.run_ffmpeg(settings.ffmpeg_bin, args, expected_duration=max(secs, 0.001),
                          cancel_event=ctx.cancel_event, timeout=settings.render_timeout_s,
                          on_progress=lambda f, b=base_done, s=secs: ctx.progress(
                              seg_weight * (b + f * s) / total_work))
            cache.store(key, work / name)
            done += secs
        cache.evict()

        # ---- stage 2: mix audio (cleanup, ducking, loudness) -----------------
        ctx.stage(2, stages, "Mixing audio")
        mix_wav, loud = mix_audio(settings, project, plan, work, audio_lists, audio_roles, ctx,
                                  lambda f: ctx.progress(seg_weight + mix_weight * f))

        # ---- stage 3: assemble + encode -------------------------------------
        ctx.stage(3, stages, "Encoding final video")
        encoder = ff.pick_h264_encoder(settings.ffmpeg_bin, encoder_pref)
        partial = dest.with_name(dest.stem + ".partial.mp4")
        final_progress = lambda f: ctx.progress(seg_weight + mix_weight + final_weight * f)  # noqa: E731
        blocks_info = None
        if encoder == "libx264" and settings.block_render:
            blocks_info = _render_blocks(settings, project, project_dir, plan, out, work, base_names,
                                         overlay_names, mix_wav, encoder, quality, cache, ctx, partial,
                                         final_progress)
        else:
            _write_concat(work / "base.ffconcat", base_names)
            inputs, g, last, idx = _final_graph(plan, work, overlay_names,
                                                ["-f", "concat", "-i", str(work / "base.ffconcat")], None)
            audio_idx = idx
            inputs += ["-i", str(mix_wav)]
            last, more_inputs, ass_cwd = _video_effects(project, project_dir, plan, out, work, g, last,
                                                        audio_idx + 1)
            g.append(f"[{audio_idx}:a]apad,atrim=end_sample={plan.total_samples},asetpts=PTS-STARTPTS[aout]")
            args = inputs + more_inputs + [
                "-filter_complex", ";".join(g), "-map", f"[{last}]", "-map", "[aout]",
                *encoder_args(encoder, quality), "-pix_fmt", "yuv420p", "-r", str(plan.fps),
                "-frames:v", str(plan.total_frames),
                "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE), "-ac", "2",
                "-movflags", "+faststart", str(partial),
            ]
            ff.run_ffmpeg(settings.ffmpeg_bin, args, expected_duration=plan.duration,
                          cancel_event=ctx.cancel_event, timeout=settings.render_timeout_s,
                          on_progress=final_progress, cwd=ass_cwd)
        partial.replace(dest)

        ctx.stage(3, stages, "Validating export")
        report = validate_export(settings, dest, out, plan.duration,
                                 target_lufs=project.audio.target_lufs if loud.get("normalized") else None)
        report.update(encoder=encoder, quality=quality, project_revision=project.revision, loudness=loud,
                      cache={"enabled": cache.enabled, "reused": cache.hits, "rendered": cache.misses},
                      **({"blocks": blocks_info} if blocks_info else {}),
                      **({"missing_sounds": missing_sounds} if missing_sounds else {}))
        (exports / (dest.stem + ".report.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return {"file": dest.name, "validation": report}
    except BaseException:
        for p in exports.glob("*.partial.mp4"):
            p.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


BLOCK_S = 20.0  # final-quality video is encoded in blocks this long (each one cached)


def _final_graph(plan: "RenderPlan", work: Path, overlay_names: list[str], base_input: list[str],
                 win: Optional[tuple[int, int]], n_base: int = 1,
                 base_trims: Optional[list[Optional[float]]] = None) -> tuple[list[str], list[str], str, int]:
    """Base video + overlay tracks. With ``win`` = (first, end) frames only overlays that
    are visible in that window are used, each seeked to it; timestamps stay absolute
    (timeline seconds) so every time-based filter behaves exactly as in a full render."""
    fps = plan.fps
    A = win[0] if win else 0
    inputs = list(base_input)
    if not win:
        g = ["[0:v]setpts=PTS-STARTPTS[v0]"]
    else:
        # inputs are coarse-seeked with timestamps kept (-copyts); trim drops to the exact frame
        g = [f"[{j}:v]{f'trim=start={t:.6f},' if t is not None else ''}setpts=PTS-STARTPTS[bs{j}]"
             for j, t in enumerate(base_trims or [None] * n_base)]
        if n_base > 1:
            g.append("".join(f"[bs{j}]" for j in range(n_base)) + f"concat=n={n_base}:v=1:a=0[bj]")
            src = "bj"
        else:
            src = "bs0"
        g.append(f"[{src}]setpts=PTS-STARTPTS+{A}/({fps})/TB[v0]")
    last, idx = "v0", n_base
    for i, s in enumerate(plan.overlays):
        off = 0
        if win:
            if s.start_frame + s.count <= win[0] or s.start_frame >= win[1]:
                continue
            off = max(0, win[0] - s.start_frame)
        trim = ""
        if off:
            t = float((off - Fraction(1, 2)) / fps)
            inputs += ["-noaccurate_seek", "-ss", f"{t:.6f}"]
            trim = f"trim=start={t:.6f},"
        inputs += ["-i", str(work / overlay_names[i])]
        c = s.clip
        g.append(f"[{idx}:v]{trim}setpts=PTS-STARTPTS+{s.start_frame + off}/({fps})/TB[o{idx}]")
        if look.needs_warp(c):  # full transparent canvas, already positioned
            g.append(f"[{last}][o{idx}]overlay=x=0:y=0:eof_action=pass[v{idx}]")
        else:
            t0 = float(s.start_frame / fps)
            src_t = f"({c.source_in:.6f}+(t-{t0:.6f})*{c.speed:.6f})"
            x, y = look.prop_expr(c, "x", src_t), look.prop_expr(c, "y", src_t)
            ev = "frame" if look.animated(c, "x") or look.animated(c, "y") else "init"
            g.append(f"[{last}][o{idx}]overlay=x='(W-w)/2+({x})+{look.crop_shift(c, 'x')}':"
                     f"y='(H-h)/2+({y})+{look.crop_shift(c, 'y')}':eval={ev}:eof_action=pass[v{idx}]")
        last = f"v{idx}"
        idx += 1
    return inputs, g, last, idx


def block_windows(total_frames: int, fps: Fraction, block_s: Optional[float] = None) -> list[tuple[int, int]]:
    n = max(1, int(round((block_s or BLOCK_S) * fps)))
    wins = [(a, min(a + n, total_frames)) for a in range(0, total_frames, n)]
    if len(wins) > 1 and wins[-1][1] - wins[-1][0] < n // 4:  # fold a tiny tail into the previous block
        wins[-2] = (wins[-2][0], wins[-1][1])
        wins.pop()
    return wins


def _render_blocks(settings: Settings, project: Project, project_dir: Path, plan: "RenderPlan",
                   out: OutputSettings, work: Path, base_names: list[str], overlay_names: list[str],
                   mix_wav: Path, encoder: str, quality: str, cache: RenderCache, ctx: JobContext,
                   partial: Path, progress) -> dict:
    """Encode the final video in independent blocks, then join them without re-encoding.

    Each block gets exactly the filters that are visible in it, so its cache key only
    changes when something inside it changes: after a small edit a re-export re-encodes
    just the affected blocks and copies the rest."""
    fps = plan.fps
    starts, f = [], 0
    for s in plan.base:
        starts.append(f)
        f += s.count
    wins = block_windows(plan.total_frames, fps)
    names, reused = [], 0
    total = plan.total_frames or 1
    for k, (A, B) in enumerate(wins):
        ctx.check_cancel()
        members = [i for i, s in enumerate(plan.base) if starts[i] < B and starts[i] + s.count > A]
        # each segment is its own input (the concat demuxer can't seek accurately); the
        # first is seeked to the keyframe before the block and trimmed to its first frame
        off = A - starts[members[0]]
        base_in: list[str] = ["-copyts"]
        trims: list[Optional[float]] = [None] * len(members)
        for j, i in enumerate(members):
            if j == 0 and off:
                t = float((off - Fraction(1, 2)) / fps)
                base_in += ["-noaccurate_seek", "-ss", f"{t:.6f}"]
                trims[0] = t
            base_in += ["-i", str(work / base_names[i])]
        inputs, g, last, idx = _final_graph(plan, work, overlay_names, base_in, (A, B), len(members), trims)
        last, more, ass_cwd = _video_effects(project, project_dir, plan, out, work, g, last, idx,
                                             win=(A, B), tag=f"{k:04d}")
        g.append(f"[{last}]setpts=PTS-STARTPTS[vout]")
        name = f"final{k:04d}.mp4"
        args = inputs + more + [
            "-filter_complex", ";".join(g), "-map", "[vout]", "-an",
            *encoder_args(encoder, quality), "-pix_fmt", "yuv420p", "-r", str(fps),
            "-frames:v", str(B - A), "-video_track_timescale", "90000", str(work / name)]
        ass = work / f"cap{k:04d}.ass"
        key = cache.key(args, work, name, extra=ass.read_text(encoding="utf-8") if ass.exists() else "")
        names.append(name)
        if cache.fetch(key, work / name):
            reused += 1
            progress(B / total * 0.95)
            continue
        ff.run_ffmpeg(settings.ffmpeg_bin, args, expected_duration=max(float((B - A) / fps), 0.001),
                      cancel_event=ctx.cancel_event, timeout=settings.render_timeout_s,
                      on_progress=lambda x, a=A, b=B: progress((a + x * (b - a)) / total * 0.95), cwd=ass_cwd)
        cache.store(key, work / name)
    cache.evict()
    ctx.check_cancel()
    aac = work / "final_audio.m4a"
    ff.run_ffmpeg(settings.ffmpeg_bin, [
        "-i", str(mix_wav), "-af", f"apad,atrim=end_sample={plan.total_samples},asetpts=PTS-STARTPTS",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE), "-ac", "2", str(aac)],
        expected_duration=plan.duration, cancel_event=ctx.cancel_event, timeout=settings.render_timeout_s)
    _write_concat(work / "final.ffconcat", names)
    ff.run_ffmpeg(settings.ffmpeg_bin, [
        "-f", "concat", "-i", str(work / "final.ffconcat"), "-i", str(aac),
        "-map", "0:v", "-map", "1:a", "-c", "copy", "-movflags", "+faststart", str(partial)],
        expected_duration=plan.duration, cancel_event=ctx.cancel_event, timeout=settings.render_timeout_s)
    progress(1.0)
    return {"count": len(wins), "reused": reused, "seconds": BLOCK_S}


def _video_effects(project: Project, project_dir: Path, plan: "RenderPlan", out: OutputSettings,
                   work: Path, g: list[str], last: str, n_inputs: int,
                   win: Optional[tuple[int, int]] = None, tag: str = "") -> tuple[str, list[str], Optional[Path]]:
    """Append zoom/shake (zoompan), flashes, pop-up overlays and burned captions.

    With ``win`` (a block's first/end frame) only effects visible in that block are
    added; timestamps are absolute timeline seconds either way."""
    W, H, F = out.width, out.height, plan.fps
    D = plan.duration
    lo, hi = (float(win[0] / F), float(win[1] / F)) if win else (0.0, D)
    wins = {k: [] for k in ("zoom", "shake", "flash", "text", "image")}
    for e in project.effects:
        if e.enabled and e.kind in wins:
            for w in fx.map_to_timeline(project, e, "video"):
                if w.start < D and (not win or (min(w.end, D) > lo and w.start < hi)):
                    wins[e.kind].append((w.start, min(w.end, D), e))
    more: list[str] = []
    # zoom + shake in one zoompan pass ('it' = timeline seconds)
    if wins["zoom"] or wins["shake"]:
        zt = [f"{e.scale - 1:.3f}*between(it,{a:.3f},{b:.3f})*min(1,(it-{a:.3f})/0.06)" for a, b, e in wins["zoom"]]
        zt += [f"0.06*between(it,{a:.3f},{b:.3f})" for a, b, _ in wins["shake"]]
        cx = "+".join(f"{e.x - 0.5:.3f}*between(it,{a:.3f},{b:.3f})" for a, b, e in wins["zoom"]) or "0"
        cy = "+".join(f"{e.y - 0.5:.3f}*between(it,{a:.3f},{b:.3f})" for a, b, e in wins["zoom"]) or "0"
        sx = "+".join(f"{0.025 * e.intensity:.4f}*iw*sin(it*61)*between(it,{a:.3f},{b:.3f})" for a, b, e in wins["shake"]) or "0"
        sy = "+".join(f"{0.025 * e.intensity:.4f}*ih*cos(it*47)*between(it,{a:.3f},{b:.3f})" for a, b, e in wins["shake"]) or "0"
        z = "1+" + "+".join(zt)
        x = f"clip((iw-iw/zoom)*(0.5+({cx}))+({sx}),0,iw-iw/zoom)"
        y = f"clip((ih-ih/zoom)*(0.5+({cy}))+({sy}),0,ih-ih/zoom)"
        # zoompan numbers its output from 0, so a block puts its own start time back
        restamp = f",setpts=PTS-STARTPTS+{win[0]}/({F})/TB" if win else ""
        g.append(f"[{last}]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={F},setsar=1{restamp}[zp]")
        last = "zp"
    for i, (a, b, e) in enumerate(wins["flash"]):
        g.append(f"[{last}]drawbox=x=0:y=0:w=iw:h=ih:color=white@0.8:t=fill:"
                 f"enable='between(t,{a:.3f},{min(b, a + 0.18):.3f})'[fl{i}]")
        last = f"fl{i}"
    k = n_inputs
    pops = sorted(wins["text"] + wins["image"], key=lambda x: x[0])
    for i, (a, b, e) in enumerate(pops):
        png = work / f"pop{tag}_{i:04d}.png"
        try:
            if e.kind == "text":
                pw, ph = fx.text_png(e.text or "", max(12, int(H * e.size)), e.color, png)
            else:
                src = project_dir / "fx" / f"{e.asset}.png"
                if not src.exists():
                    continue
                pw, ph = fx.image_png(src, max(16, int(W * e.size * 2.5)), png)
        except Exception:  # noqa: BLE001 - a broken pop-up must not kill the export
            continue
        dur = max(0.1, b - a)
        px = int(min(max(0, W * e.x - pw / 2), max(0, W - pw)))
        py = int(min(max(0, H * e.y - ph / 2), max(0, H - ph)))
        more += ["-loop", "1", "-framerate", str(F), "-t", f"{dur:.3f}", "-i", str(png)]
        g.append(f"[{k}:v]format=rgba,fade=t=in:st=0:d=0.08:alpha=1,"
                 f"fade=t=out:st={max(0.0, dur - 0.12):.3f}:d=0.12:alpha=1,"
                 f"setpts=PTS-STARTPTS+{a:.4f}/TB[p{i}]")
        g.append(f"[{last}][p{i}]overlay=x={px}:y={py}:eof_action=pass[po{i}]")
        last = f"po{i}"
        k += 1
    cwd = None
    if project.captions.enabled:
        chunks = _caption_chunks_cached(project, project_dir, work)
        if win:
            chunks = [c for c in chunks if c["end"] > lo - 0.5 and c["start"] < hi + 0.5]
        if chunks:
            family = _caption_font_cached(work)
            ass = f"cap{tag}.ass" if win else "captions.ass"
            (work / ass).write_text(fx.captions_ass(project, chunks, family, H, W), encoding="utf-8")
            g.append(f"[{last}]ass={ass}:fontsdir=.[cap]")
            last, cwd = "cap", work
    return last, more, cwd


def _caption_chunks_cached(project: Project, project_dir: Path, work: Path) -> list[dict]:
    p = work / "caption_chunks.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    chunks = fx.caption_chunks(project, project_dir)
    p.write_text(json.dumps(chunks), encoding="utf-8")
    return chunks


def _caption_font_cached(work: Path) -> str:
    p = work / "caption_font.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    family = fx.prepare_caption_font(work) or "Arial"
    p.write_text(family, encoding="utf-8")
    return family


NR = {"light": 0.3, "medium": 1.0, "strong": 3.0}  # anlmdn strength (non-local means denoiser)
# used only if anlmdn makes FFmpeg fail; adaptive noise tracking so steady hiss is learned
# (afftdn alone barely touches broadband hiss; with a gentle gate in pauses it matches
# anlmdn's result on the test hiss, voice level unchanged)
NR_FALLBACK = {"light": "afftdn=nr=12:nf=-45:tn=1,agate=threshold=0.015:ratio=3:attack=5:release=150:range=0.5",
               "medium": "afftdn=nr=24:nf=-40:tn=1,agate=threshold=0.015:ratio=4:attack=5:release=130:range=0.2",
               "strong": "afftdn=nr=40:nf=-40:tn=1,agate=threshold=0.02:ratio=6:attack=5:release=120:range=0.06"}
DUCK = {"light": 3, "medium": 6, "strong": 12}  # sidechain compression ratio


def _loudnorm_measure(settings: Settings, wav: Path, target: float) -> Optional[dict]:
    proc = subprocess.run([settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-i", str(wav), "-af",
                           f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True, timeout=3600)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr)
    if proc.returncode != 0 or not m:
        return None
    data = json.loads(m[-1])
    try:
        if float(data["input_i"]) < -70:  # (near) silence: nothing to normalise
            return None
    except ValueError:
        return None
    return data


def mix_audio(settings: Settings, project: Project, plan: RenderPlan, work: Path, audio_lists: list[list[str]],
              roles: list[str], ctx, on_progress) -> tuple[Path, dict]:
    """Mix all audio into one WAV: dialogue (noise reduction / voice enhance), music
    (ducked under dialogue), effects; then two-pass loudness normalisation."""
    a = project.audio
    inputs: list[str] = []
    for ti, names in enumerate(audio_lists):
        lf = work / f"audio{ti:02d}.ffconcat"
        _write_concat(lf, names)
        inputs += ["-f", "concat", "-i", str(lf)]
    groups = {"dialogue": [], "music": [], "fx": []}
    for i, r in enumerate(roles):
        groups[r if r in groups else "dialogue"].append(f"[{i}:a]")
    g: list[str] = []
    info: dict = {"normalized": False, "noise_reduction": a.noise_reduction, "enhance_voice": a.enhance_voice,
                  "ducking": "off"}

    def mix(labels: list[str], out: str) -> None:
        if len(labels) == 1:
            g.append(f"{labels[0]}anull[{out}]")
        else:
            g.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[{out}]")

    finals: list[str] = []
    if groups["dialogue"]:
        mix(groups["dialogue"], "dia")
        chain = []
        if a.noise_reduction != "off":
            chain.append(f"anlmdn=s={NR[a.noise_reduction]}")
        if a.enhance_voice:
            chain += ["highpass=f=80", "equalizer=f=3000:t=q:w=1.2:g=3",
                      "acompressor=threshold=0.125:ratio=3:attack=10:release=150:makeup=1.5"]
        if chain:
            g.append(f"[dia]{','.join(chain)}[diap]")
        dia = "diap" if chain else "dia"
        if groups["music"] and a.ducking != "off":
            g.append(f"[{dia}]asplit=2[diam][diasc]")
            mix(groups["music"], "mus")
            g.append(f"[mus][diasc]sidechaincompress=threshold=0.02:ratio={DUCK[a.ducking]}:attack=40:"
                     f"release=500:makeup=1[musd]")
            finals += ["[diam]", "[musd]"]
            info["ducking"] = a.ducking
        else:
            finals.append(f"[{dia}]")
            if groups["music"]:
                mix(groups["music"], "mus")
                finals.append("[mus]")
    elif groups["music"]:
        mix(groups["music"], "mus")
        finals.append("[mus]")
    if groups["fx"]:
        mix(groups["fx"], "fxm")
        finals.append("[fxm]")
    if not finals:
        inputs += ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
        finals = ["[0:a]"]
    g.append(f"{''.join(finals)}amix=inputs={len(finals)}:duration=longest:normalize=0,"
             f"apad,atrim=end_sample={plan.total_samples},asetpts=PTS-STARTPTS[mix]")
    raw = work / "mix_raw.wav"
    graph = ";".join(g)

    def run_mix(fg: str) -> None:
        ff.run_ffmpeg(settings.ffmpeg_bin, inputs + ["-filter_complex", fg, "-map", "[mix]",
                                                      "-c:a", "pcm_f32le", "-ar", str(AUDIO_RATE), str(raw)],
                      expected_duration=plan.duration, cancel_event=ctx.cancel_event,
                      timeout=settings.render_timeout_s, on_progress=lambda f: on_progress(f * 0.5))
    try:
        run_mix(graph)
    except ff.Cancelled:
        raise
    except ff.FFmpegError:
        # anlmdn has crashed some Windows FFmpeg builds (heap corruption, exit 0xC0000374)
        # at higher strengths. Retry once with FFmpeg's FFT denoiser instead of failing.
        nr = f"anlmdn=s={NR.get(a.noise_reduction)}"
        if a.noise_reduction == "off" or nr not in graph:
            raise
        ctx.check_cancel()
        run_mix(graph.replace(nr, NR_FALLBACK[a.noise_reduction]))
        info["noise_reduction_fallback"] = "afftdn"
    if not a.normalize:
        return raw, info
    ctx.check_cancel()
    m = _loudnorm_measure(settings, raw, a.target_lufs)
    if m is None:
        info["note"] = "audio is silent; loudness left unchanged"
        return raw, info
    final = work / "mix_norm.wav"
    ln = (f"loudnorm=I={a.target_lufs}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
          f"linear=true:print_format=summary")
    ff.run_ffmpeg(settings.ffmpeg_bin, ["-i", str(raw), "-af",
                                        f"{ln},aresample={AUDIO_RATE},apad,atrim=end_sample={plan.total_samples}",
                                        "-c:a", "pcm_s16le", "-ar", str(AUDIO_RATE), str(final)],
                  expected_duration=plan.duration, cancel_event=ctx.cancel_event,
                  timeout=settings.render_timeout_s, on_progress=lambda f: on_progress(0.5 + f * 0.5))
    info.update(normalized=True, target_lufs=a.target_lufs, measured_lufs=float(m["input_i"]))
    # loudnorm's linear mode can't raise quiet-but-peaky audio (e.g. soft speech with sharp
    # transients, or deep volume-keyframe dips) without breaking the peak ceiling; it then
    # undershoots by several dB. Close the gap with gain into a peak limiter, re-measuring.
    got = measure_lufs(settings, final)
    gain, fixed = 0.0, final
    for i in range(3):
        if got is None or abs(got - a.target_lufs) <= 0.5:
            break
        ctx.check_cancel()
        gain = round(gain + (a.target_lufs - got), 2)
        fixed = work / f"mix_norm_fix{i}.wav"
        ff.run_ffmpeg(settings.ffmpeg_bin, ["-i", str(final), "-af",
                                            f"volume={gain}dB,alimiter=limit={10 ** (-1.5 / 20):.4f}:level=false:"
                                            f"attack=2:release=60,aresample={AUDIO_RATE},apad,"
                                            f"atrim=end_sample={plan.total_samples}",
                                            "-c:a", "pcm_s16le", "-ar", str(AUDIO_RATE), str(fixed)],
                      expected_duration=plan.duration, cancel_event=ctx.cancel_event,
                      timeout=settings.render_timeout_s)
        got = measure_lufs(settings, fixed)
    if fixed is not final:
        info.update(limiter_gain_db=gain)
    return fixed, info


def measure_lufs(settings: Settings, path: Path) -> Optional[float]:
    proc = subprocess.run([settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-nostats", "-i", str(path),
                           "-filter_complex", "ebur128", "-f", "null", "-"], capture_output=True, text=True,
                          timeout=3600)
    m = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", proc.stderr)
    if not m or m[-1] == "-inf":
        return None
    return float(m[-1])


def validate_export(settings: Settings, path: Path, out: OutputSettings,
                    expected_duration: float, full_decode: bool = True,
                    target_lufs: Optional[float] = None) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("file exists", path.exists() and path.stat().st_size > 0,
        f"{path.stat().st_size if path.exists() else 0} bytes")
    proc = subprocess.run(
        [settings.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format",
         "-show_streams", str(path)], capture_output=True, text=True, timeout=120)
    info = json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    add("video stream is H.264", bool(v and v.get("codec_name") == "h264"),
        v.get("codec_name", "missing") if v else "missing")
    add("audio stream is AAC", bool(a and a.get("codec_name") == "aac"),
        a.get("codec_name", "missing") if a else "missing")
    add("resolution", bool(v and v.get("width") == out.width and v.get("height") == out.height),
        f"{v.get('width')}x{v.get('height')} (expected {out.width}x{out.height})" if v else "n/a")
    fmt_dur = float(info.get("format", {}).get("duration", 0) or 0)
    tol = 2.0 / out.fps + 0.05
    add("duration", abs(fmt_dur - expected_duration) <= tol,
        f"{fmt_dur:.3f}s (expected {expected_duration:.3f}s, tolerance {tol:.3f}s)")
    if v and a:
        vd, ad = float(v.get("duration", 0) or 0), float(a.get("duration", 0) or 0)
        add("audio/video sync", abs(vd - ad) <= max(tol, 0.05),
            f"video {vd:.3f}s, audio {ad:.3f}s")
        nb = v.get("nb_frames")
        if nb:
            exp = int(round(expected_duration * out.fps))
            add("frame count", abs(int(nb) - exp) <= 1, f"{nb} frames (expected {exp})")
    if full_decode:
        d = subprocess.run(
            [settings.ffmpeg_bin, "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=max(120, int(expected_duration * 2)))
        errs = d.stderr.strip().splitlines()
        add("decodes without errors", d.returncode == 0 and not errs,
            "clean" if not errs else "; ".join(errs[:3]))
    if target_lufs is not None:
        lufs = measure_lufs(settings, path)
        add("loudness", lufs is not None and abs(lufs - target_lufs) <= 1.5,
            f"{lufs:.1f} LUFS (target {target_lufs:.0f})" if lufs is not None else "no audio")
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "file_size": path.stat().st_size if path.exists() else 0,
            "duration": fmt_dur}
