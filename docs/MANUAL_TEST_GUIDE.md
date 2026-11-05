# Hands-on test guide: Phases 4–10

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

## Phase 8: Shorts, publishing, YouTube, faster re-exports, portable package

Use a project whose recording has been **analysed** (AI Auto Editor → Analyse), ideally with speech transcribed.

| # | Do this | You should see |
|---|---|---|
| 8.1 | **Shorts** (phone icon) → choose the project | *Best moments*: up to a few 15–60 s moments, each with a score and why |
| 8.2 | Pick one → **Make Short** (captions on) | A new project under *Your Shorts*, 9:16. Open it: the picture follows your face (or the movement) smoothly, captions in the middle |
| 8.3 | Export that Short | A vertical 1080×1920 MP4 that passes all checks |
| 8.4 | AI Auto Editor with a transcript → *Humor* or *Story* style | Moments with laughs, punchlines or stories rank higher, and the reasons say so |
| 8.5 | *(Optional, only if you run Ollama)* Start Ollama with a model, reload the AI Auto Editor | A **Rate moments with local AI (model)** button; afterwards moments it liked show "AI: …" in the list |
| 8.6 | **Publish** → choose the project | Chapters starting at 0:00, title ideas, a description with the chapters, tags. Problems (e.g. chapters < 10 s apart) are listed in plain words |
| 8.7 | Edit a chapter title, the title and tags, then reload the page | Your edits are kept |
| 8.8 | *(Optional)* Publish → follow the steps to connect YouTube (needs your own Google API client, see docs/YOUTUBE.md) | "Connected: *your channel*" |
| 8.9 | *(Optional)* Choose an export → **Upload to YouTube** (leave it **Private**) | It asks you to confirm, shows progress, then a link. The video is private on YouTube with your title, description, tags and thumbnail |
| 8.10 | Effects → *My sounds & images* → press **#** on a sound and give it the keyword "laugh" → *Suggestions from your library* → **Suggest** | Suggested spots for it near laughs or loud reactions; **Add all** puts them on the timeline |
| 8.11 | Thumbnails → add your own image or *From my library* → **Cut out subject** | The person/object is cut out from the background as a new layer |
| 8.12 | Export a project, then export it again without changes | The second export is much faster; the report says all blocks were reused |
| 8.13 | Add one flash in the middle, export again | Faster than the first export; the report says most blocks were reused; the flash is in the video |
| 8.14 | *(Portable package)* GitHub → Actions → latest green **CI** run → *Artifacts* → download **ClipForge-portable-win64**, unzip, double-click `ClipForge.bat` | ClipForge opens without using your installed Python/FFmpeg (Windows may warn first: *More info → Run anyway*). Your projects are there (same workspace) |

## Phase 9: face cam, smoother jump cuts, new transitions

You need a game/screen recording and a webcam video of the same session (OBS + the Windows Camera app at the same time works; see the chat notes). Both should have sound.

| # | Do this | You should see |
|---|---|---|
| 9.1 | Import both videos into one project; put the game on the timeline | Both in Media |
| 9.2 | Editor → **Cam** → pick the webcam video → **Add face cam** | A job "Line up face cam", then a message saying how far apart they were. Play it: your lips match your voice |
| 9.3 | If it's slightly off, press **−1 frame** / **+1 frame** | It moves by one frame each time |
| 9.4 | Try each corner, the **Size** slider, **Circle**, a border colour | The preview follows every change |
| 9.5 | **Crop to my face** | The cam zooms in on your head and shoulders |
| 9.6 | Cut the game clip in a few places (or run the AI Auto Editor) and play | The face cam always shows the matching moment |
| 9.7 | Put the playhead somewhere, **Hide from here**, move on 5 s, press again | The cam fades out there and back in after |
| 9.8 | **Full screen on my biggest reactions** (needs the recording analysed) | On loud reactions the cam fills the screen briefly |
| 9.9 | Tick **Remove my background** | A job prepares it (under half the length of the cam video on a 2-core PC; faster on yours); then "Ready for export" |
| 9.10 | Export | The cam is where you put it; with background removal, just you over the game |
| 9.11 | Toolbar → **Smooth jump cuts…** → *Zoom punch-in*, then export | Every other piece after a jump cut is slightly zoomed in, like a second camera |
| 9.12 | Try *Quick blend* and *Whip pan*; then *Plain cuts* | Short blends / whip pans at the jump cuts; *Plain cuts* removes them again |
| 9.13 | AI Auto Editor → Finishing touches → **Smoother jump cuts** → *Zoom punch-in* → Send to Manual Editor | The report says how many jump cuts were smoothed |
| 9.14 | Clip tab → Transition → try **Spin**, **Glitch**, **Light leak**, **Whip pan**, **Flash cut** and export | Each one shows in the export (the preview still shows a plain cut) |
| 9.15 | Shorts → a moment → Face cam: **Stacked** → Make Short → export | Face cam on the top 40%, the game below |

## Phase 10: edit by transcript, fillers & retakes, titles, blur, beat

Use a talking video with speech transcribed (Effects → Transcribe speech), ideally with a few "um"s and a sentence you restarted.

| # | Do this | You should see |
|---|---|---|
| 10.1 | Editor → **Script** | Your edit as text; the current word lights up as it plays; fillers marked yellow, retakes purple |
| 10.2 | Click a word | The playhead jumps there |
| 10.3 | Drag across a few words → **Cut** (or Delete) | They're gone from picture and sound; the timeline closes up; Ctrl+Z brings them back |
| 10.4 | **Remove N filler words**, then **Remove N retakes** | The "um"s and first tries are gone and it still sounds natural |
| 10.5 | AI Auto Editor → Finishing touches → tick **Remove filler words** and **Remove retakes** → Send to Manual Editor | The report says how many were removed |
| 10.6 | **Text** → **Lower third** → type your name and a second line | It slides in at the bottom-left of the preview |
| 10.7 | Try **Big title**, **Top banner**, **Subscribe**, **Chapter card**; change colours, position, size | Each one in the preview; export them and compare |
| 10.8 | **Blur** → **Draw a blur** → drag over something | A blurred box there for 3 s |
| 10.9 | Put the playhead on a face → **Blur faces here** | An oval blur on each face |
| 10.10 | Select a blur → **Follow it** (on something that moves) | After a moment "Following it now"; the blur moves with it in the preview |
| 10.11 | Try **Pixelate** and **Black box**; export | The export hides it the same way |
| 10.12 | Put a song on the music track (♪) → **Beat** → **Find the beat** | Its BPM, and green marks on the timeline |
| 10.13 | Make a few cuts → **Snap cuts to the beat** | The cuts move onto the green marks; play it: the cuts land on the beat |
| 10.14 | **End the music with the video** | The song ends with the video with a fade |

**Known preview limits (the export is always exact):** colour is approximate, transitions show as cuts, face cam background removal only appears in the export, and titles/blur are drawn by the browser in the preview (close, not identical).
