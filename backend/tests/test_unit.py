"""Unit tests: schema validation, path safety, render planning, filename safety."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.render import atempo_chain, fps_fraction, plan_render, safe_output_name
from app.schema import MediaAsset, OutputSettings, Project, Timeline, Track, default_timeline
from app.storage import (PathSecurityError, atomic_write_json, display_name, media_extension,
                         new_id, read_json, safe_join, validate_id)


def asset(duration=10.0, video=True, audio=True) -> MediaAsset:
    return MediaAsset(id=new_id(), original_name="a.mp4", stored_name="x.mp4",
                      kind="video" if video else "audio", duration=duration, size_bytes=1,
                      has_video=video, has_audio=audio)


def project_with(clips_v=(), clips_a=(), media=None) -> Project:
    m = media or asset()
    tl = default_timeline(new_id).model_dump()
    tl["tracks"][0]["clips"] = [dict(id=new_id(), media_id=m.id, **c) for c in clips_v]
    tl["tracks"][2]["clips"] = [dict(id=new_id(), media_id=m.id, **c) for c in clips_a]
    return Project.model_validate({"id": new_id(), "name": "t", "media": [m.model_dump()],
                                   "timeline": tl})


# ---------------------------------------------------------------- path safety
@pytest.mark.parametrize("bad", ["..", "../x", "a/b", "", ".", "a\\b", "x\x00"])
def test_safe_join_rejects(tmp_path, bad):
    with pytest.raises(PathSecurityError):
        safe_join(tmp_path, bad)


def test_safe_join_rejects_symlink_escape(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "link").symlink_to(tmp_path)
    with pytest.raises(PathSecurityError):
        safe_join(tmp_path / "root", "link")


@pytest.mark.parametrize("bad", ["abc", "../" + "a" * 30, "A" * 32, "g" * 32])
def test_validate_id(bad):
    with pytest.raises(PathSecurityError):
        validate_id(bad)
    assert validate_id("a" * 32) == "a" * 32


def test_media_extension_allow_list():
    assert media_extension("My Video.MOV") == ".mov"
    for bad in ("x.exe", "x.m3u8", "x.txt", "noext", "x.mp4.sh"):
        with pytest.raises(PathSecurityError):
            media_extension(bad)


def test_display_name_strips_paths_and_control_chars():
    assert display_name("../../etc/passwd") == "passwd"
    assert display_name("C:\\Users\\x\\clip.mp4") == "clip.mp4"
    assert "\n" not in display_name("a\nb.mp4")


def test_atomic_write_and_backup_recovery(tmp_path):
    f = tmp_path / "p.json"
    atomic_write_json(f, {"v": 1})
    atomic_write_json(f, {"v": 2})
    assert read_json(f) == {"v": 2}
    f.write_text("{corrupt")  # simulate crash-corrupted main file
    assert read_json(f) == {"v": 1}  # falls back to .bak


def test_safe_output_name():
    assert safe_output_name("../../evil name!.exe") == "evil name.mp4"
    assert safe_output_name("") == "export.mp4"
    assert safe_output_name("...") == "export.mp4"


# ---------------------------------------------------------------- schema
def test_overlapping_clips_rejected():
    with pytest.raises(ValidationError, match="overlap"):
        project_with([dict(start=0, source_in=0, source_out=5), dict(start=4, source_in=0, source_out=2)])


def test_source_out_beyond_media_rejected():
    with pytest.raises(ValidationError, match="exceeds media"):
        project_with([dict(start=0, source_in=0, source_out=11)])


def test_audio_only_media_on_video_track_rejected():
    with pytest.raises(ValidationError, match="audio-only"):
        project_with([dict(start=0, source_in=0, source_out=1)], media=asset(video=False))


def test_rotation_range_enforced():
    project_with([dict(start=0, source_in=0, source_out=1, transform={"rotation": 90})])
    with pytest.raises(ValidationError, match="rotation"):
        project_with([dict(start=0, source_in=0, source_out=1, transform={"rotation": 99999})])


def test_odd_output_dimensions_rejected():
    with pytest.raises(ValidationError, match="even"):
        OutputSettings(width=1921, height=1080)


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        Track.model_validate({"id": new_id(), "kind": "video", "name": "V", "evil": 1})


def test_newer_schema_refused():
    from app.schema import migrate
    with pytest.raises(ValueError, match="newer"):
        migrate({"schema_version": 999})


def test_clip_duration_with_speed():
    p = project_with([dict(start=2, source_in=0, source_out=4, speed=2)])
    assert p.timeline.duration == pytest.approx(4.0)


# ---------------------------------------------------------------- render planning
def test_plan_quantises_without_drift():
    # 300 clips of 1/3 s each: naive per-clip rounding would drift; absolute rounding can't.
    clips = [dict(start=i / 3, source_in=0, source_out=1 / 3) for i in range(300)]
    p = project_with(clips, clips)
    plan = plan_render(p, OutputSettings(fps=30))
    assert sum(s.count for s in plan.base) == plan.total_frames == 3000
    assert sum(s.count for s in plan.audio_tracks[0]) == plan.total_samples == 100 * 48000
    # every clip boundary lands within half a frame of its true position
    for s in plan.base:
        if s.kind == "clip":
            assert abs(s.start_frame / 30 - s.clip.start) <= 0.5 / 30 + 1e-9


def test_plan_inserts_gaps_and_tail():
    p = project_with([dict(start=1, source_in=0, source_out=1)], [dict(start=0, source_in=0, source_out=3)])
    plan = plan_render(p, OutputSettings(fps=25))
    assert [s.kind for s in plan.base] == ["gap", "clip", "gap"]
    assert [s.count for s in plan.base] == [25, 25, 25]


def test_plan_hidden_and_muted_tracks():
    p = project_with([dict(start=0, source_in=0, source_out=2)], [dict(start=0, source_in=0, source_out=2)])
    p.timeline.tracks[0].hidden = True
    p.timeline.tracks[2].muted = True
    plan = plan_render(p, OutputSettings())
    assert all(s.kind == "gap" for s in plan.base)
    assert plan.audio_tracks == []


def test_empty_timeline_cannot_render():
    with pytest.raises(ValueError, match="empty"):
        plan_render(project_with(), OutputSettings())


def test_ntsc_rates_and_atempo():
    assert fps_fraction(29.97) == Fraction(30000, 1001)
    assert atempo_chain(1.0) == []
    assert atempo_chain(4.0) == ["atempo=2.0", "atempo=2.000000"]
    assert atempo_chain(0.25) == ["atempo=0.5", "atempo=0.500000"]


def test_text_files_are_always_utf8():
    """Windows CI: files written as UTF-8 were read back with the Windows default code page,
    so a version named with curly quotes/emoji silently disappeared. Every read_text/
    write_text in the app must name its encoding (JSON is read from bytes)."""
    import re
    from pathlib import Path
    bad = []
    for f in (Path(__file__).parents[1] / "app").glob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.(read_text|write_text)\(", line) and "encoding=" not in line \
                    and not line.rstrip().endswith(","):
                bad.append(f"{f.name}:{n}: {line.strip()}")
    assert not bad, "\n".join(bad)


def test_project_file_never_disappears_under_concurrent_reads(tmp_path):
    """Windows CI: an upload failed because saving project.json raced a background job
    reading it. The file must always be readable while it's being rewritten."""
    import threading
    from app.storage import atomic_write_json, read_json
    f = tmp_path / "project.json"
    atomic_write_json(f, {"n": 0})
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                assert "n" in read_json(f)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                return

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for i in range(400):
        atomic_write_json(f, {"n": i, "pad": "x" * 2000})
    stop.set()
    for t in threads:
        t.join()
    assert not errors, errors[:3]
    assert read_json(f)["n"] == 399 and read_json(f.with_suffix(".json.bak"))["n"] == 398
