# Hands-on test guide: Phases 4–15

A checklist for trying the new features on your own videos. Each step says what you should see. If something doesn't match, note the step number and what happened. Screenshots help, and so do the **Details** text of any failed job.

**Before you start.** The easiest way is to double-click **`Update RJClip.bat`** in the rjclip folder. It gets the latest version, installs what's needed (including speech-to-text) and starts RJClip. Or do it by hand:

```powershell
cd C:\Users\Riley\rjclip
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
| 7.1 | Close RJClip, then double-click **`Start RJClip.bat`** in the rjclip folder | A window that sets things up (first time only), then the browser opens RJClip |
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
| 8.14 | *(Portable package)* GitHub → Actions → latest green **CI** run → *Artifacts* → download **RJClip-portable-win64**, unzip, double-click `RJClip.bat` | RJClip opens without using your installed Python/FFmpeg (Windows may warn first: *More info → Run anyway*). Your projects are there (same workspace) |

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

## Phase 11: polish

| # | Do this | You should see |
|---|---|---|
| 11.1 | Add a title and a blur | A **Text·Blur** lane above V1 with a purple and a blue bar |
| 11.2 | Click a bar; drag it; drag its right edge | The right tab opens with it selected; it moves; it gets longer |
| 11.3 | Ripple delete (Shift+Delete) a clip before a title | The title moves left with the video; Ctrl+Z puts it back |
| 11.4 | Add a transition (Clip tab) and play over the cut | The preview shows the transition (not a plain cut) |
| 11.5 | Press **?** | A list of keyboard shortcuts |
| 11.6 | Press **L**, then **K**, then **J** | Plays, pauses, jumps back 2 s |
| 11.7 | **Guides** under the preview (try a 9:16 Short too) | Safe-area boxes; on a Short, where YouTube's buttons and text go |
| 11.8 | Make the window smaller (or try a 1280×720 laptop) | Everything still fits: Export button, all side tabs, no overlapping |

**Known preview limits (the export is always exact):** colour and transitions are look-alikes, face cam background removal only appears in the export, and titles/blur are drawn by the browser in the preview (close, not identical).

## Phase 12: editing basics that were skipped

| # | Do this | You should see |
|---|---|---|
| 12.1 | Click a clip, then **Ctrl-click** (or Shift-click) another; drag one of them | Both move together, keeping the gap between them, with their sound. Ctrl+Z puts them back |
| 12.2 | Press **Ctrl+A** | Every clip is selected (not ones on locked tracks) |
| 12.3 | Select a video clip and press **Ctrl+L** (or the chain button) | "Unlinked": now drag just the sound a little. The picture stays put |
| 12.4 | Drag the sound back into line (edges snap), select both, **Ctrl+L** | "Linked": they move together again. If they don't line up, it tells you to line them up first |
| 12.5 | Press **M** at a few places | A flag on the ruler and a bar above the timeline: type a name, pick a colour. **Done** closes it |
| 12.6 | Press **Shift+←** / **Shift+→**; drag a flag; select one and press **Delete** | Jumps between markers; the marker moves; it's gone |
| 12.7 | Ripple delete a clip before a marker | The marker moves left with the video |
| 12.8 | **Publish** → Chapters: *From my timeline markers* → **Write it for me** | Chapters named like your markers, the first at 0:00 (an "Intro" is added if needed). Works even without a transcript. YouTube's rules are still checked (3+ chapters, 10 s apart) |
| 12.9 | Close RJClip, rename or move a recording out of `workspace\projects\<project>\media\original`, reopen | "file missing" in the Media panel and a note at the top |
| 12.10 | Click **Find file** and pick the recording (any name) | "Relinked", the clips play again. A different or too-short file is refused with the reason |

**Notes:** moving several clips keeps each on its own track (drag one clip on its own to move it to another track). If you relink to a *different* file (for example a re-export), its old transcript and analysis are reset, so check the cuts still line up.

## Phase 13: change an effect's time

| # | Do this | You should see |
|---|---|---|
| 13.1 | AI Auto Editor with comedy edits (or add a **Pop-up text** yourself) → Editor → **FX** tab → scroll to **Effects** | Each effect has an **At** box with its time |
| 13.2 | Click the box, type a new time (`20.8`, `0:20.8` or `1:02.5`), press **Enter** | The box shows the new time, the preview jumps there and the effect plays there |
| 13.3 | **−0.1s** / **+0.1s** | It moves by a tenth of a second each click |
| 13.4 | Move the playhead somewhere, click **To playhead** | It starts at the playhead |
| 13.5 | Type `abc`, or a time past the end of the video | Goes back to the old time; past the end you get "no footage" |
| 13.6 | Type a time, then press **Esc** instead of Enter | Nothing changes |
| 13.7 | Ctrl+Z, then export | Undo moves it back; the export shows it at the time you set |

**Note:** moving a bleep moves both the beep and the part of the sound that's silenced, so it's the way to line a bleep up with its word if it's slightly early or late (use ±0.1s). The masked word in the captions follows the bleep too.

## Phase 14: background music and captions

| # | Do this | You should see |
|---|---|---|
| 14.1 | Editor → **Music** tab → **Import** a song you have the rights to (mp3, m4a, wav…) | It's picked in the Song list |
| 14.2 | Type **From** and **To** (e.g. `0:10` and `1:30`), or use the **Playhead** buttons / **Whole video** → **Add music** | A message like "looped 3×" if the song is shorter; the song appears on the A2/Music track and in "Music in this video" |
| 14.3 | Play it | The music fades in, loops with a short dip, fades out at the end, and goes quieter while you talk (try "Lower the music while you talk": A lot) |
| 14.4 | Drag the item's volume slider; click the trash icon; Ctrl+Z | Louder/quieter in the export; removed; back |
| 14.5 | FX tab → **1 · Transcript**, then **4 · Captions** → turn them on | Captions now show **in the preview** while you play, in the style/size/position you pick |
| 14.6 | Script tab → **double-click** a wrong word → type the right one → Enter | "Fixed: …", the preview caption changes, the word is highlighted |
| 14.7 | Export, and FX → **Download .srt** | The burned-in captions and the .srt both have the fixed word |

**Notes:** the caption preview is a close look-alike; the export is exact. Fixing a word changes only its text (not when it's said). If you transcribe that recording again, its fixes are replaced.

## Phase 18: fonts, counter tools, reaction & group tools, looks

| # | Do this | You should see |
|---|---|---|
| 18.1 | Settings → **Fonts** | The built-in fonts, each written in itself. **Add a font file** → pick a `.ttf`/`.otf` (e.g. from Google Fonts) → it's listed under yours |
| 18.2 | Editor → **Text** → **Pop-up words** → click the **Horror** style | Creepy red text with a glow in the preview. Try other styles, the **Font** list (your font is under *Yours*), **Outline**, **Shadow**, **Glow** |
| 18.3 | **Save as my style** | A ★ button with your style; use it on another title. × deletes it |
| 18.4 | **Emoji sticker** → pick 💀, drag it on the preview, change its colour | A tinted emoji sticker; it pops in |
| 18.5 | Text → **Counter**: pause on a moment, type a name and a detail → **Count it at …** (do it twice) | A COUNT counter top right goes 0 → 1 → 2 exactly at those moments, each with a red flash and a boom; a callout card #1 / #2 |
| 18.6 | **Ctrl+Z** once | The whole last count (+1 and card) goes away. **Ctrl+Y** brings it back |
| 18.7 | Cut out the part with the first count (Script tab or split + ripple delete) | The counter only counts what's left |
| 18.8 | Near the end → **Tally screen here** | Full screen: FINAL COUNT, the total, and the names in order; the counter stops there |
| 18.9 | Put a clip on V1 and your narration on its own audio track → click that track's mic button until it shows **N** (narration) → export | The clip's sound gets quieter while you talk |
| 18.10 | Two mics on two audio tracks → Text → **Name tags**: name each, tick **Show name tags** → play | Each name lights up while that person is loud |
| 18.11 | A long session → **AI** tab → **Find funny moments** | A list of loud reactions with scores; click a time to jump there. **Mark them** adds markers; **Keep only these** cuts the rest (Ctrl+Z undoes) |
| 18.12 | **Effects** tab → **Combos** → **Meme zoom**, **Bass boosted**; click a few **Sound board** buttons while playing | Several effects at once; sounds dropped where the playhead was |
| 18.13 | Effects → Captions → **Caption font** | Captions in that font (preview and export) |
| 18.14 | Clip tab → **Look** → VHS tape / Old film / Horror / Vignette / Cinema bars | The look in the preview; same in the export |
| 18.15 | Make the window small (e.g. 1280×720) | The preview shows the whole picture (nothing cut off top or bottom) |
| 18.16 | Export | Fonts, counter, cards, tally, name tags, stickers, bass boost and looks all in the video |

## Phase 17: polish

| # | Do this | You should see |
|---|---|---|
| 17.1 | Settings → **Show the tour again** → open a project in the editor | The tour: 7 steps, each pointing at a part of the screen. **Back**/**Next** work, keys like S or Delete do nothing behind it |
| 17.2 | Finish it (**Start editing**), reload the page | It doesn't come back. Start it again from Settings and press **Esc**: it closes |
| 17.3 | Put a title and a marker on the second clip of your timeline (and a blur, if you like) → drag that clip later | The title, marker and blur move with it; the ones on other clips stay put. **Ctrl+Z** puts it all back |
| 17.4 | Drag a face cam or B-roll clip on V2 | Titles and markers stay where they are |
| 17.5 | GitHub → Actions → latest green *CI* run → Artifacts → **RJClip-Setup-win64** → unzip → run `RJClip-Setup-win64.exe` | SmartScreen: *More info → Run anyway*. No admin prompt. Finish → RJClip opens in your browser; Start menu has **RJClip** |
| 17.6 | Windows Settings → Apps → RJClip → Uninstall | RJClip is removed; your projects in `RJClipWorkspace` are still there |

## Phase 16: smarter AI help

Needs a recording with a transcript (Script tab → Transcribe) for the best results.

| # | Do this | You should see |
|---|---|---|
| 16.1 | Editor → **AI** tab → **Check my hook** | A score out of 100, a verdict, and tips about your first 10 seconds |
| 16.2 | If offered, click **Cut slow start**, then **Check my hook** again | The silence before your first word is gone and the score goes up. Ctrl+Z undoes it |
| 16.3 | If offered, click **Add teaser** | A few seconds of your best moment play at the very start, then the video as before |
| 16.4 | Import a second recording that mentions something you also say (or is named after it, e.g. `castle tour.mp4`) → **Find B-roll** | Suggestions like “castle” → castle tour.mp4; **Preview it** jumps there; **Add B-roll** puts the clip on V2 over that moment |
| 16.5 | Voiceover → **Download the voice** (once, about 95 MB) | Progress, then the voice box appears. Turn off your internet after this to check it works offline |
| 16.6 | Type a sentence, pick a voice and speed → **Add voiceover** | A new audio clip at the playhead that says your sentence |
| 16.7 | Music tab → add a short song to the whole video with **Smooth loops** ticked | The song repeats with no gap or dip at each join |
| 16.8 | Import a calm song and an energetic one → **Match songs to the video** → **Use these songs** | Calmer stretches get the calm song, busier ones the energetic one |
| 16.9 | Export | Teaser, B-roll, voiceover and music all in the video |

## Phase 15: pro look

| # | Do this | You should see |
|---|---|---|
| 15.1 | **Settings → Brand kit**: upload a logo (PNG), an intro video, pick a corner, size, colours, caption style | Saved as you go; the logo shows in the box |
| 15.2 | Editor → **Text** tab → **Apply my brand kit** | Logo on the preview, the intro is first on the timeline, titles/captions recoloured. Ctrl+Z undoes the intro/colours; **Remove logo** takes the logo off |
| 15.3 | Text tab → **Pop-up words**, **Arrow**, **Circle**, **Box** | Each appears at the playhead; with it selected, drag it on the preview; Turn slider rotates it; try each Animation |
| 15.4 | Put a green-screen video on **V2** above your gameplay → select it → Clip tab → **Green screen: On** | The green disappears (preview close, export exact); Strength / Soft edge adjust the edge |
| 15.5 | Two clips at the playhead (V1 + V2) → **Side by side / Top / bottom / Picture-in-picture / Reset** | They rearrange; corner and size for picture-in-picture |
| 15.6 | Playhead on a clip → **Freeze frame** for 2 s | The picture holds, the sound pauses, then everything carries on |
| 15.7 | Select a clip, playhead on it → **Slow-mo** (or **Speed-up**) | A smooth slow-down and back up from the playhead; the video gets longer (or shorter) |
| 15.8 | Select a clip under 60 s → **Reverse this clip** | It plays backwards, sound too |
| 15.9 | Export | Logo, intro, shapes, green screen, layouts, freeze, ramp and reverse all in the video |

