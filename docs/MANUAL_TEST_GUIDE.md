# Hands-on test guide: Phases 4–7

A checklist for trying the new features on your own videos. Each step says what you should see. If something doesn't match, note the step number and what happened. Screenshots help, and so do the **Details** text of any failed job.

**Before you start.** The easiest way is to double-click **`Update ClipForge.bat`** in the clipforge folder. It gets the latest version, installs what's needed (including speech-to-text) and starts ClipForge. Or do it by hand:

```powershell
cd C:\Users\Riley\clipforge
git pull
cd frontend; npm run build
cd ..\backend; .venv\Scripts\activate; pip install -r requirements.txt
python -m app.main
```

Open http://127.0.0.1:8765. For bleeps and captions, also install the free transcriber once: `pip install -r requirements-ai.txt`.

Use a 2–10 minute video with talking, a few loud reactions and at least one swear word.

---

## Phase 4: effects, captions, audio

| # | Do this | You should see |
|---|---|---|
| 4.1 | Editor → **Effects** tab → **Transcribe speech** | Progress bar, then "1 of 1 clip source(s) transcribed ✓" |
| 4.2 | Pick the sound *quack* → **Find & bleep swears** | Each swear listed with its context; low-confidence ones are marked "review". Orange marks appear on the timeline |
| 4.3 | Play over a bleep | The quack plays and the original word can't be heard |
| 4.4 | Comedy edits → *Balanced* → **Auto-place** | Zooms, shakes, pop-up text and sound effects on your loudest reactions, never stacked on each other |
| 4.5 | Tick **Burn animated captions into the export**, try each style | Captions in the preview; censored words show as `s***` |
| 4.6 | Audio: turn on noise removal + voice enhance; set A2 to the music role (♪) and put music there | Music gets quieter whenever you talk (after export) |
| 4.7 | **Export** | The report shows ✓ for every check, including loudness ≈ −14 LUFS. In the file, the bleeps, captions and effects are all there |

## Phase 5: one-click AI edit + version history

| # | Do this | You should see |
|---|---|---|
| 5.1 | AI Auto Editor → analyse → in **Finishing touches** tick bleeps, comedy (*Balanced*), captions and audio polish → **Send to Manual Editor** | Short messages listing what was added. If you have no transcript yet, it says bleeps/captions were *skipped* and why |
| 5.2 | Editor → **History** tab | A "Before AI edit" version, if the timeline had clips before |
| 5.3 | **Save this version**, name it "First cut". Then delete a clip | Saved; the clip is gone |
| 5.4 | **Compare** on "First cut" | Red bars show the footage you cut, "−X s cut", and clip counts for A and B |
| 5.5 | **Restore** "First cut" | The deleted clip is back; a "Before restoring…" version appears |
| 5.6 | Restore "Before restoring…" | You're back to the version without the clip |

## Phase 6: advanced editor

| # | Do this | You should see |
|---|---|---|
| 6.1 | Select a video clip → **Clip** tab → Rotation 90° | The preview turns at once |
| 6.2 | Crop **Left** 20% | The left edge disappears; the rest stays where it was |
| 6.3 | Colour → Look **Black & white**, then try Cinematic; move Temperature | The preview changes. It's an approximation, and the export is exact |
| 6.4 | Slow zoom: playhead at the clip's start → ◆ next to Scale. Move the playhead 3 s later → drag Scale to 130% | Two ◆ marks on the clip; scrubbing between them zooms smoothly in the preview |
| 6.5 | On the ◆ at the start, set "To next keyframe" to **Ease in/out** | The zoom starts and ends gently |
| 6.6 | Trim the start of that clip by 1 s | The zoom still happens on the same footage |
| 6.7 | Picture-in-picture: drag a clip to **V2**, set Scale 35% and position X 600 / Y −300, then keyframe X so it slides in | A small window over V1 that moves, both in the preview and in the export |
| 6.8 | Select an audio clip → ◆ Volume at one point, then a lower value 1 s later | The volume dips there; ◆ marks show on the audio clip |
| 6.9 | Transition into a clip: try *Wipe left*, *Circle open*, *Zoom in*, *Dip to white* | After export, each plays between the two clips (the preview shows a cut) |
| 6.10 | Press **Play** and watch the **L/R meters** at the right of the preview | Green bars move; yellow near −12 dB, red near clipping. The small red light means it clipped (click it to reset) |
| 6.11 | Click **Light preview** | Plays a 540p copy (smoother on slow PCs). The first time, it makes the copies in the background |
| 6.12 | Zoom the timeline far in on an audio clip | The waveform stays detailed. For files imported before this update, click ⟳ on the file in Media to rebuild it |
| 6.13 | Export, then change one clip and export again | The second export is much faster: only the changed part re-renders. Settings shows the render cache size |

## Phase 7: your own sounds & images, launcher

| # | Do this | You should see |
|---|---|---|
| 7.1 | Close ClipForge, then double-click **`Start ClipForge.bat`** in the clipforge folder | A window that sets things up (first time only), then the browser opens ClipForge |
| 7.2 | Editor → **Effects** → *My sounds & images* → **Record sound**. Allow the microphone, say something funny, then **Stop** | A player with your take. Silence at the start and end is trimmed after saving |
| 7.3 | Name it → **Save** | It appears under *Sounds* with its length and a "mic" tag |
| 7.4 | Press **Bleep** on your sound, then **Find & bleep swears** | Swears are bleeped with *your* sound. The bleep sound list shows it as ★ name |
| 7.5 | Move the playhead → **Add** on your sound | A sound effect at the playhead that plays its full length |
| 7.6 | **Import image** → pick a PNG/JPG → **Add** | It pops up on screen at the playhead |
| 7.7 | Open **another project** → Effects | The same sounds and images are there |
| 7.8 | AI Auto Editor → Finishing touches → bleep sound list | Your sounds are listed with ★ |
| 7.9 | Delete a sound from the library that a project uses, then export that project | The export still has the sound (each project keeps its own copy) |
| 7.10 | Open http://127.0.0.1:8765/api/docs | A list of every API route |

**Known preview limits (the export is always exact):** colour is approximate and transitions show as cuts in the preview.
