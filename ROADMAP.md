# Roadmap & feature status

This file is the **persistent project checklist**. Update it whenever a feature lands, so progress survives across sessions.

Legend: ✅ done & tested · 🟡 partial (see note) · ⬜ not started

## Phase 1 — Foundation ✅

- ✅ Environment inspection, architecture, repo structure
- ✅ Versioned project schema (v1) with semantic validation and a migration hook
- ✅ Safe media import: streaming upload, size/quota limits, extension allow-list, FFprobe validation, SHA-256 de-dup, read-only originals
- ✅ FFmpeg/FFprobe integration (argument lists, protocol + demuxer whitelists, timeouts, measured progress, cancel)
- ✅ Thumbnails, waveforms, browser preview proxies (background jobs)
- ✅ Dark UI shell: Dashboard, AI Auto Editor, Manual Editor, Projects, Export, Settings
- ✅ Initial tests (backend unit + integration, frontend engine, browser E2E)

## Phase 2 — Manual editor foundation ✅ (the last four items were finished in Phase 12)

- ✅ Media library (import, drag-to-timeline, double-click append, remove unused, status chips)
- ✅ Multitrack timeline with real data model (video stacking, linked A/V clips)
- ✅ Program-monitor playback of the timeline, multi-track audio preview, frame step
- ✅ Move (incl. across tracks), trim both edges, split, delete, ripple delete, duplicate
- ✅ Snapping (clip edges, playhead, zero), zoom (anchored Ctrl+wheel, slider, fit), scroll
- ✅ Track mute / hide / lock, add / remove tracks
- ✅ Undo / redo (200 steps, labelled)
- ✅ Clip speed, volume, scale, position
- ✅ Autosave, crash-safe writes, cross-window conflict detection, reopen
- ✅ Export presets (1080p, 720p, 4K, 9:16, 1:1, custom), fps, letterbox/crop, quality, validation report
- ✅ Preview fidelity: every video layer, size/position/rotation/crop, volume above 100% (added in Phases 6 and 11; colour and transitions are look-alikes, the export is exact)
- ✅ Multi-clip drag (Phase 12)
- ✅ Relink missing media (Phase 12)
- ✅ Unlink / relink A/V clips (Phase 12)
- ✅ Timeline markers (Phase 12)

## Phase 3 — Automatic editing engine ✅ (signal-based) / 🟡 (transcript features)

- ✅ Streaming analysis: loudness (20/s), on-screen motion, hard scene cuts. ~3.4 s per minute of 720p on 2 cores, < 50 MB RAM
- ✅ Silence & pacing presets (off / conservative / balanced / aggressive) with a retained pause; natural short pauses never cut
- ✅ Moments ("beats") split only at pauses; size adapts to the target length
- ✅ Explainable weighted scoring: balanced, excitement, reactions, information, visual action (+ humor/story approximations with warning)
- ✅ Duration planner: custom duration, % of original, original length; opening hook; setup-before-payoff context; feasibility warnings
- ✅ Keep / drop overrides per moment; deterministic plans; validated EDL; stale-review protection
- ✅ Review UI: summary, warnings, source strip, per-moment preview, play rough cut
- ✅ Send to Manual Editor / Apply & export (previous timeline backed up to `history/`)
- 🟡 Transcription (faster-whisper adapter written behind a provider interface, **not yet run in tests**: it couldn't be installed in the build environment). Word-boundary snapping is implemented and tested with synthetic word data.
- ⬜ Laughter classifier, repetition detection, transcript keyword/topic scoring
- ⬜ Optional LLM reasoning provider (local or API, opt-in)
- ⬜ Short-form (9:16) auto-reframe

## Phase 4 — YouTube entertainment features ✅

- ✅ Transcription job (faster-whisper, free/local, optional install) — 🟡 not yet run on a real machine
- ✅ Swear censoring at the audio level: strong/mild lists + custom & allow words, padding, review flags, 6 synthesised sounds, masked captions
- ✅ Comedy edits: zoom punch-ins, shake, flash, pop-up text, 10 synthesised SFX, user images; auto-placement on reactions (minimal/balanced/chaotic)
- ✅ Effects pinned to source time (follow trims/moves, vanish when cut); timeline markers; monitor preview; undo/redo; autosave
- ✅ Animated burned-in captions (bold pop / word highlight / clean) + SRT export
- ✅ Two-pass loudness normalisation (−14 LUFS default, verified in the export report), noise removal, voice enhancement
- ✅ Music tracks ducked under dialogue (sidechain), volume fades
- ✅ Transitions: crossfade (with handles; linked audio crossfades) and dip to black; fades from/to black
- ⬜ Transition/fade preview in the live monitor (export is exact)
- ⬜ Built-in music library, animated GIF pop-ups (first frame only today), dragging effects on the timeline

## Phase 4b — Thumbnail Maker 🟡 basic version (back burner)

- ✅ Timeline-aware frames from the final edit (cached), honest analysis summary with unknowns
- ✅ Built-in creative director: 3 distinct concepts, grounded headline ideas, workflow recommendation, asks for context when needed
- ✅ Layered studio (text, shapes, image adjustments, layers, undo/redo, small previews), rule-based refinements, versions, staleness warning
- ✅ Validated 1280×720 JPEG/PNG export (YouTube rules), saved to project
- 🟡 Free local Stable Diffusion + optional OpenAI Images + Ollama/OpenAI text model: integrated, contract-tested against fake servers, **not run against real services**
- ⬜ Design scoring/review, text-model refinement in UI, image upload UI, crop handles, version compare, subject cut-outs

## Phase 5 — AI + manual integration ✅

- ✅ Open AI rough cut in the timeline, edit, re-render (tested in browser E2E)
- ✅ One-click "AI edit + finishing touches": bleeps, comedy edits, captions and audio polish run with the edit. Each step reports whether it was applied or skipped, and why (for example, no transcript). Re-running replaces earlier automatic effects rather than stacking them.
- ✅ Version history (Editor → History):
  - save named versions
  - automatic checkpoints every 10 minutes while editing, and before every AI edit and restore
  - rename and delete versions
  - restore a version (the current edit is saved first, so a restore can be undone)
  - compare any two versions: footage cut or added per source, clip, effect and transition counts, and changed settings
- ✅ Older "history/timeline-*.json" AI backups are imported as versions automatically

## Phase 6 — Advanced editor ✅

- ✅ Keyframes for scale, position, rotation, opacity and volume
  - easing: linear, ease in/out, or hold
  - anchored to the footage, so trims, splits and speed changes keep them in place
  - ◆ marks on the timeline; the preview animates too
- ✅ Rotation, opacity and crop, all previewed live in the monitor, which now shows every video layer
- ✅ 21 transitions: crossfade, dip to black/white, wipes, slides, smooth, cover/reveal, circle, radial, zoom, pixelize, blur
- ✅ Colour correction:
  - brightness, contrast, saturation, gamma, temperature
  - 8 looks: warm, cool, black & white, vintage, vivid, faded, cinematic, noir
- ✅ Light preview toggle: plays 540p proxy copies and makes any that are missing
- ✅ Render cache: re-exports reuse every unchanged segment. It's keyed on the exact FFmpeg arguments and source files, so it's never stale. 4 GB limit, oldest files evicted first
- ✅ Detailed waveforms when zoomed in (100 peaks/s, interpolated past that); "Rebuild previews" upgrades older media
- ✅ Stereo peak audio meters with peak hold and a clip light; preview volume above 100% now works (Web Audio)

## Phase 7 — Production readiness 🟡

- ✅ **My sounds & images**: record sounds with the mic or import audio/video/images into a library shared by all projects. Use them as the bleep sound (Effects panel and the Auto Editor), as sound effects, or as image pop-ups. They're copied into each project that uses them
- ✅ GitHub Actions CI on every push:
  - backend tests on **Ubuntu and Windows**
  - frontend tests, typecheck and build
  - engine → backend cross-check
  - all 8 browser E2E flows
  - a from-scratch Windows launcher run
  - `pip-audit` and `npm audit`
- ✅ Windows bugs found by that CI and fixed:
  - UTF-8 file reading
  - a crash in FFmpeg's denoiser, now with a fallback
- ✅ OpenAPI 3.1 at `/api/openapi.json` and a readable page at `/api/docs`, generated from the routes so they can't drift (the goal of the planned FastAPI move)
- ✅ Performance benchmark on a 2-hour source (`scripts/benchmark.py`; results in [docs/BENCHMARKS.md](docs/BENCHMARKS.md))
- ✅ One-click Windows launcher (`Start RJClip.bat` / `Update RJClip.bat`); packaging options evaluated in [docs/PACKAGING.md](docs/PACKAGING.md)
- ✅ Cloud deployment design and threat model ([docs/CLOUD.md](docs/CLOUD.md)); design only, not built
- ⬜ FastAPI migration. **Blocked here:** FastAPI can't be installed in this development environment, and a framework swap that can't be run can't be tested. The generated OpenAPI spec already covers its main benefit
- ⬜ Vite dev server + React types + component tests. **Blocked the same way** (no `vite`, `@types/react` or Testing Library packages available). Typechecking covers the engine; the UI is covered by the 8 browser E2E flows
- ✅ Windows portable package and faster re-exports: done in Phase 8 (8.7)

## Phase 8 — Creator tools 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **8.1 Shorts maker** (Shorts page): suggests the best 15–60 s moments, then makes a 9:16 project per Short. The crop follows you (face detection, or movement when no face is found) with a smooth, steady camera; optional captions and title. Each Short is a normal project you can edit
- ✅ **8.2 Reads what's said**: with a transcript the AI scores laughs, punchlines, questions, exclamations and story beats. Optional **local AI** (Ollama, or any OpenAI-compatible server on your PC) rates moments 0–10 on top; found automatically, off when not running, nothing is sent online
- ✅ **8.3 Publish page**: chapters (from topic changes, checked against YouTube's rules: first at 0:00, ≥ 3, ≥ 10 s apart), title ideas, a description with chapters, and tags (≤ 15, under YouTube's 500-character limit). The local AI can polish them if you run one
- ✅ **8.4 Upload to YouTube**: connect your own Google account with your own free API client (step-by-step in [docs/YOUTUBE.md](docs/YOUTUBE.md)); resumable upload with title, description, tags, category, thumbnail. **Private by default** and it asks before every upload. Your login stays on your PC (owner-only file, never sent to the browser). Tested against a fake Google server, **not yet against the real YouTube**
- ✅ **8.5 Suggestions from your library**: tag your sounds/images ("laugh", "fail", "wow"…) and RJClip suggests where to drop them, from what's said and the loud reactions
- ✅ **8.6 Thumbnail Maker**: cut out the subject (no AI download needed), use your own images or library images, real face detection (bundled model), title prefilled from Publish, optional local AI for headline ideas
- ✅ **8.7 Faster re-exports**: the final video is encoded in 20-second blocks, each cached. After a small change only the blocks that changed are encoded again; the rest are copied. Checked frame by frame against a one-pass render (identical apart from encoder noise, no dropped/doubled frames at block edges)
- ✅ **8.7 Windows portable package**: a zip with Python, FFmpeg, the UI and speech-to-text inside. Nothing to install: unzip, double-click `RJClip.bat`. Built on every push by CI, then unzipped on a clean runner with **nothing on PATH** and used to import, export and re-export a video. Unsigned, so Windows SmartScreen will warn the first time ("More info → Run anyway"). See [docs/PACKAGING.md](docs/PACKAGING.md)
- ⬜ Code-signed installer (needs a signing certificate)

## Phase 9 — Face cam & transitions 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Face cam** (Editor → **Cam**): import your webcam video and it sits over the main recording, **following every cut** (yours and the AI's), so it never drifts out of sync
  - **Line up by sound**: if the cam was recorded separately, RJClip matches the two microphones (accurate to a few ms in tests) and says how sure it is; nudge by a frame or type an offset
  - corner presets (top/bottom, left/right), size, gap to the edge
  - square corners, rounded or **circle**; border colour/width; soft shadow
  - **Crop to my face** (head and shoulders, found with the bundled face detector)
  - **Hide** stretches (it fades out and back in) or make it **fill the screen** for a moment, by hand or on your **biggest reactions**
  - preview in the monitor matches the export (same layout maths, tested against each other)
- ✅ **Optional AI background removal** for the face cam (off by default): shows just you over the video, no green screen. Runs on your computer with a small bundled model (PP-HumanSeg, Apache-2.0, 6 MB); prepared once per recording in the background. Good, not perfect: edges around hair can be rough. Export only (the preview shows the full picture)
- ✅ **Stacked Shorts**: face cam on top, video below (or keep it in its corner, or leave it out)
- ✅ **Smoother jump cuts**: zoom punch-in (alternating close/wide, like a second camera), quick blend, or whip pan. In the Editor toolbar and in the AI's finishing touches. Only undoes changes it made itself
- ✅ **9 new transitions**: whip pan left/right, spin, glitch, RGB split, light leak, zoom blur, flash cut, shake cut (30 in total)
- ✅ Previewing transitions in the monitor: done in Phase 11

## Phase 10 — Modern editing essentials 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Edit by transcript** (Editor → **Script**): your edit as text. Click a word to jump there; drag or Shift+click to select words and **Cut** (or press Delete). Picture and sound are cut together and the gap closes; the music keeps playing (and is trimmed with a fade if it now runs past the end). Titles and blurs move along. Undo works
- ✅ **Filler words & retakes**: "um", "uh", "hmm"… and sentences you started, stopped and said again (the same 3–5 words within 15 s; the later take is kept). Marked in the Script tab, removed in one click there, or as AI finishing touches. RJClip asks the speech-to-text to write fillers down, but how many it catches depends on the speech
- ✅ **Titles** (Editor → **Text**): lower third, big title, top banner, subscribe button, chapter card; text, second line, colours, position, size; animated in and out. Rendered sharply by the same subtitle engine as captions; previewed in the monitor
- ✅ **Privacy blur** (Editor → **Blur**): blur, pixelate or black box; box or oval; **draw it on the preview**, or **Blur faces here** in one click; **Follow it** tracks what moves (and finds it again after a cut). Works best on things with clear detail; check the preview
- ✅ **Music beat sync** (Editor → **Beat**): finds the tempo and beats of the song on your music track (within about a frame in tests), shows them on the timeline, **snaps nearby cuts onto the beat** (roll edits: nothing else shifts, linked sound follows), and ends the music with the video. No built-in music library (licences); YouTube Studio's Audio Library has free music you can import

## Phase 11 — Polish 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Titles and blurs on the timeline**: their own lane above V1. Click one to open it (Text or Blur tab), drag to move it, drag an edge to change its length
- ✅ **Ripple delete moves titles and blurs** along with the picture (before, only Script-tab cuts did)
- ✅ **Transitions preview in the monitor**: all 30, as look-alikes of the export (both pictures, with the export's timing)
- ✅ **Side panel**: one row of icon tabs (Clip, FX, Text, Script, Blur, Beat, Cam, History) instead of two rows of buttons
- ✅ **Keyboard**: press **?** for all shortcuts; **J / K / L** = back 2 s / pause / play
- ✅ **Safe-area guides** on the preview: title-safe and action-safe boxes, or, for vertical Shorts, where YouTube puts its own buttons and text (approximate)
- ✅ **Fits laptop screens**: the Editor and the AI Auto Editor no longer run off a 1280×720 screen (the Export button and the side tabs were cut off; the Auto Editor's columns overlapped)

## Phase 12 — Editing basics that were skipped 🟡 (built and tested automatically; waiting for your hands-on test)

Picked by looking for what earlier phases left unfinished (the four ⬜ items in Phase 2) and what a creator would trip over.

- ✅ **Move several clips at once**: Ctrl/Shift-click to select, drag any of them; they keep their spacing and their sound. **Ctrl+A** selects every clip. (A group stays on its tracks; drag a single clip to change track)
- ✅ **Unlink / link picture and sound** (Ctrl+L or the chain button): unlink to nudge or delete the sound on its own; link clips that line up (same start and length) so they move together again
- ✅ **Timeline markers**: **M** adds one at the playhead; name it, colour it, drag it, delete it; **Shift+← / →** jumps between them. They move with ripple delete and Script-tab cuts
- ✅ **Chapters from markers** on the Publish page: your marker names become the YouTube chapters (an "Intro" at 0:00 is added if needed; works without a transcript; the local AI keeps your names)
- ✅ **Relink missing media**: if a recording disappears from the project folder, the Media panel says so and **Find file** brings it back from any copy (any name). The file must have what the edit uses and be long enough; a different file resets that recording's transcript/analysis and says so
- ✅ The timeline toolbar fits a 1280-wide screen (less-used buttons become icons with tooltips)
- ✅ Fixes found on the way: job progress can no longer step backwards (seen on Windows); the Editor fits 1280×720 even with wider system fonts

## Phase 13 — Effect times you can edit 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Type a new time** for any effect (pop-up text, zoom, shake, flash, sound, image, bleep), including ones the AI placed: Editor → **FX** → Effects list → the **At** box. Type `20.8`, `0:20.8` or `1:02.5`, press Enter. The preview jumps there; **Esc** cancels
- ✅ **Nudge** −0.1 s / +0.1 s, or **To playhead**
- ✅ The effect is re-pinned to whatever footage is at the new time (so it still follows that moment when you move clips). Sounds and bleeps prefer the audio track. A time with no footage is refused with a message; an effect whose moment was cut out can be brought back by typing a time
- ✅ Effect cards fit the side panel on a 1280-wide screen (the delete button and colour box were cut off)

## Phase 18 — Creator styles: fonts, Kill Count, Vanoss-style tools, looks 🟡 (built and tested automatically; waiting for your hands-on test)

**Fonts & text styles**
- ✅ 22 free fonts built in (Bold, Clean, Fun, Horror, Retro & gaming, Handwritten), each shipped with its licence (SIL Open Font License or Apache 2.0, in `backend/app/fonts/licenses/`). Add your own `.ttf`/`.otf` in **Settings → Fonts** (web fonts and font collections are turned down with a message)
- ✅ Every title, caption style and counter can use any of them; the preview loads the real font, so it looks like the export
- ✅ Outline (size + colour), drop shadow and glow on any title; 10 ready-made styles (Bold outline, Horror, Blood drip, Comic, Cartoon, Arcade, Neon, Glitch, Marker, Clean); **Save as my style** keeps your own
- ✅ **Emoji stickers**: 32 one-colour emoji (Noto Emoji) you can tint, place, turn and animate like pop-up words. (Full-colour images: use *My library* images, as before)

**Kill Count tools** (Text tab)
- ✅ **Kill at the playhead**: type who and how, press Kill → the counter goes up (with a sound) and a death card (KILL #n, name, how) slams in. One Ctrl+Z takes the whole kill back
- ✅ **Counters** (up to 4, e.g. KILLS and DEATHS): label, starting number, place, colours, font, size, when they show. Each +1 is pinned to the footage like other effects, so cutting and moving keeps it on its moment, and a count you cut out stops counting
- ✅ **End tally**: a full-screen recap listing every death card before it and the total; adding one ends the counter there
- ✅ **Narration tracks**: the track button now cycles dialogue → music → narration. Everything else (the movie/game sound and music) gets quieter while your narration talks, using the Ducking strength
- ✅ **Number cards** for Top-10 style videos (#7 + text)

**Vanoss-style tools**
- ✅ **Funny-moment finder** (AI tab): finds where people get much louder than their normal talking — laughing, yelling, screaming — across all mic tracks (more people at once = higher score), starting each moment a few seconds early for the set-up. **Mark them** (markers) or **Keep only these** (cuts everything else). It can't tell a laugh from a shout: it's a loudness finder, you pick the funny ones
- ✅ **Name tags** (Text tab): name each mic's audio track; a voice-chat style list shows everyone and lights up whoever is talking (or only shows the talker). Based on loudness, so game sound on a mic counts as talking
- ✅ **Combos** (Effects tab): one click adds several effects — Meme zoom (zoom + shake + boom), Bass boosted, Airhorn hype, Record scratch, Bonk
- ✅ **Bass boost** effect: crunchy, boosted low end for a stretch (the final loudness pass keeps the video's level safe)
- ✅ **Sound board** (Effects tab): one click drops any built-in sound or one of yours at the playhead, even while playing. (Your own sounds and images were already supported in *My library*)

**Looks** (Clip tab): Horror, VHS tape (scanlines, colour bleed, noise), Old film (grain + vignette), Vignette, Cinema bars. (Whip, zoom and glitch transitions already existed from Phase 9.)

**Fixes found on the way**
- The preview picture was cropped top and bottom when the preview area was shorter than the video's shape (e.g. a 1280×720 window): it now always fits whole
- Settings sections in the side panel no longer stick out sideways when a row of buttons is wide

## Phase 17 — Polish 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Titles, blurs and markers follow the clip you move**: drag a clip (or several, or type a new start in the Clip tab) and the titles and markers on it move with it, so they stay on the same moment. They belong to the clip on the lowest video track at that point (your main picture), so moving a face cam or B-roll on V2 doesn't drag them; a blur goes with the picture it covers (the top one). One Ctrl+Z puts everything back. Trimming doesn't move them
- ✅ **First-run tour**: the first time you open the editor, 7 short steps point at the media, preview, timeline, tools and Export. Skip it any time (Esc); **Settings → Show the tour again** brings it back. It's remembered per browser
- ✅ **Windows installer** (`RJClip-Setup-win64.exe`, unsigned): installs the same tested portable package for your user only (no admin prompt) into `%LOCALAPPDATA%\Programs\RJClip`, with a Start-menu shortcut (desktop shortcut optional) and an uninstaller in *Settings → Apps*. Your projects stay in `%USERPROFILE%\RJClipWorkspace` and are never touched by installing, updating or uninstalling. CI builds it with Inno Setup, installs it silently on a clean Windows machine, exports a video with it, uninstalls it and checks everything is gone except your projects. Unsigned, so Windows SmartScreen warns the first time (*More info → Run anyway*)

## Phase 16 — Smarter AI help 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Hook checker** (Editor → **AI** tab → **Check my hook**): scores the first 10 seconds of your edit out of 100 from things it can measure — how soon you start talking, a long intro, how loud and how busy the start is compared with the rest, and whether your first sentence sounds like a hook (needs the transcript). Each weak point comes with a tip, and some with a one-click fix: **Cut slow start** (removes the silence before your first word) and **Add teaser** (copies your best moment to the very start). It is a rule of thumb, not a prediction of views
- ✅ **B-roll from your own clips**: finds words you say (nouns from the transcript) that also appear in your *other* recordings' transcripts or file names, and suggests that footage on V2 over the moment you say it. Each word and each piece of footage is suggested once. **Preview it**, **Add B-roll** or **Add all**. Only uses clips already in the project — nothing is downloaded
- ✅ **Voiceover** (offline): type a line, pick one of 6 voices and a speed → **Add voiceover** puts it on an audio track at the playhead. Uses the free Piper voice engine, downloaded once (about 95 MB, from GitHub and HuggingFace, checked by SHA-256) when you click **Download the voice**; after that it runs with no internet. Credit for the voice: "Voice: Piper, LibriTTS-R (CC BY 4.0)" — put it in your description if you publish voiceovers
- ✅ **Smarter music**: **Smooth loops** (on by default) loops a song in whole bars on its beat with a crossfade at each join instead of a fade-out/fade-in; **Match songs to the video** splits the video into calmer and busier stretches and suggests a calm or hype song from your sounds for each (each song is labelled calm/medium/hype with its tempo) → **Use these songs**
- ✅ Fixes found on the way: a very early refused upload (no FFmpeg, file too big) could reset the connection instead of showing the message; the beat cache from older versions is refreshed to include the song's energy

## Phase 15 — Pro look 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Brand kit** (Settings → Brand kit, saved once for every project): logo watermark (corner, size, see-through), intro and outro videos, title colours, caption style. **Editor → Text → Apply my brand kit** adds the logo to the whole video, puts the intro first (everything moves later) and the outro last, recolours titles and sets the caption style (undoable, except the logo, which has its own **Remove logo** button). The project keeps its own copy of the logo
- ✅ **Pop-up words, arrows, circles and boxes** (Text tab): place them anywhere (drag them on the preview, or the Across/Down sliders), turn them, and pick an animation: pop, bounce, slide up, typewriter (words only) or none. Drawn by the same title engine as before, so the export matches the preview closely
- ✅ **Green screen** (Clip tab): makes a colour see-through (FFmpeg chromakey in the export; a close look-alike in the preview), with strength and soft-edge sliders
- ✅ **Layouts** (Clip tab): side by side, top/bottom, picture-in-picture in any corner and size, reset — for the top two video clips at the playhead
- ✅ **Freeze frame** (hold the picture 0.5–10 s; the sound pauses, music keeps playing) and **reverse** (picture and sound, clips up to 60 s). Both are made as new media files, so they preview and edit like any clip
- ✅ **Speed ramps**: smooth slow-motion or speed-up from the playhead and back, made of short pieces whose speed eases in and out (the sound follows the speed)
- ✅ Fixes found on the way: a title added at the playhead could be invisible on that exact frame; a freeze right at a clip's edge, a speed ramp on a fast clip, and picture linked to sound on a music track are handled (found by the random-edit test)

## Rename — ClipForge → RJClip ✅ (Nov 2026)

- App, docs, launchers (`Start RJClip.bat`, `Update RJClip.bat`), portable zip, CI and the GitHub repo (`rileyyes/rjclip`; the old address redirects)
- Kept working: `CLIPFORGE_*` settings (copied to `RJCLIP_*`), an existing `~/ClipForgeWorkspace`, the old `X-ClipForge` header, the old `.bat` files (left unchanged so an update running from them doesn't break)
- The launcher points git at the new repo and renames the `clipforge` folder to `RJClip` once its window is closed

## Phase 14 — Background music & captions 🟡 (built and tested automatically; waiting for your hands-on test)

- ✅ **Background music for a stretch of time**: Editor → **Music** tab (was "Beat") → pick a song or **Import** one → **From / To** (type times or use the playhead; "Whole video") → volume, fade in/out, "start song at" (skip an intro), **loop if shorter** → **Add music**. It goes on a music track (a free one, else a new "Music" track), so it's lowered while you talk ("Lower the music while you talk"). Each song is listed with its own volume and a remove button. Loop joins get a short fade out and back in (0.3 s); Phase 16 adds smooth crossfaded loops
- ✅ **Captions in the preview**: when captions are on (FX → 4 · Captions), the preview shows them while you edit, built exactly like the export's lines (checked against the same test cases). The look is a close CSS copy of the burned-in style
- ✅ **Fix a misheard word**: Script tab → double-click a word (or select it → **Fix word**) → type → Enter. Captions, the .srt, swear finding and chapters use the fix; the timing stays. Re-transcribing a recording replaces its fixes
- ✅ Fixes found on the way: the Script tab's Cut/Fix bar no longer appears above the text when you click a word (a double-click could hit **Cut**); linking picture and sound now needs them to line up exactly and be the same moment of a recording

## Known limitations / bugs

- Without a transcript, "humor" and "story" styles are approximations (the UI says so).
- Very long timelines render one FFmpeg process per clip. Correct and memory-safe, but a 140-clip, 29-minute timeline took ~7 min on 2 cores.
- Block rendering (fast re-exports) is used with the software H.264 encoder. With a GPU encoder the final video is still encoded in one pass (fast already, but not cached).

- Preview colour and transitions are CSS look-alikes, face cam background removal only shows in the export, and titles/blur preview with browser styling (close, not pixel-identical). Export is exact.
- Titles, blurs and markers sit at timeline times: Script-tab cuts and ripple delete move them; moving clips by hand doesn't.
- Linking needs the clips to line up exactly (same start and length); linked clips always stay in sync, so offset sound is kept unlinked.
- Face cam background removal runs per frame on the CPU: preparing it took 0.43× the cam's length on a 2-core VM (a 1-hour webcam recording ≈ 26 minutes), once per recording.
- Long exports are CPU-bound: a 30-minute 1080p edit took 42 min on a 2-core VM with software H.264 (see docs/BENCHMARKS.md). GPU encoders are used automatically when they work.
- Keyframed rotation/scale/opacity render through a transparent warp pass, which is slower than plain clips (about 2–3× for those clips only).
- Upload copies the file into the workspace (2× disk use for huge recordings). "Import by reference" is planned with a safe folder allow-list.
- Single-user, single-machine. Two tabs editing the same project get a conflict prompt instead of a merge.
