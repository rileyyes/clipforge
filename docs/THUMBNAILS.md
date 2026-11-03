# Thumbnail Maker (basic version)

Make a 1280×720 YouTube thumbnail from your **final edit**. It's deliberately simple for now (see ROADMAP "Phase 4b"). It is **free and local by default**.

## Workflow

1. **Thumbnails → choose a project** (it needs something on the timeline).
2. **Analyse edit**: pulls a handful of representative frames from the *edited* video, with trims, clip order, hidden tracks, overlays and scale/position applied. It uses Auto Editor analysis peaks and scene changes when available. Frames are cached, and nothing is rendered in full.
3. **Tell it about the video**: a one-line description (required if there's no transcript), plus optional title, genre and main subject. It won't guess a topic it hasn't analysed.
4. **Get 3 concepts**: three different creative directions, each with a hook, composition, headline idea, palette, the reason it fits, and a recommended workflow:
   - **Your footage**: built from real frames (always available, most accurate).
   - **AI artwork** / **AI art + your footage**: need an image provider (below). Always labelled as dramatization, never passed off as footage.
5. **Studio**: layers (hide, lock, reorder, duplicate, delete), drag to move, text (font, size, colour, outline, alignment), shapes and highlights, image brightness/contrast/saturation/blur, size and rotation, undo/redo, live previews at feed (320 px) and sidebar (168 px) sizes, and plain-language refinements ("more dramatic", "remove the text", "make the subject bigger", "cleaner"…). Locked layers are never touched.
6. **Save version** (immutable snapshots, restorable). The draft autosaves separately.
7. **Export** JPEG or PNG at exactly 1280×720. Validated against YouTube's rules (16:9, ≥ 640 px wide, ≤ 2 MB, real JPG/PNG). JPEG quality steps down automatically to stay under 2 MB. Saved to the project and downloadable.

If you change the edit later, saved thumbnails show a warning that they may no longer represent the video.

## Free AI artwork (optional): Stable Diffusion on your PC

Needs an NVIDIA GPU (≈ 6–8 GB VRAM recommended; 4 GB works with SD 1.5 models).

1. Install **Stable Diffusion WebUI Forge** (or AUTOMATIC1111) and a model/checkpoint.
2. Start it with the API enabled: add `--api` to its launch arguments.
3. Start ClipForge with `CLIPFORGE_SDWEBUI_URL=http://127.0.0.1:7860`.

Nothing leaves your computer. `CLIPFORGE_SDWEBUI_STEPS` (default 28) trades speed for quality.

## Free smarter concepts (optional): Ollama

`ollama pull llama3.1`, then `CLIPFORGE_LLM_BASE_URL=http://127.0.0.1:11434/v1` (`CLIPFORGE_LLM_MODEL` to change the model). The built-in director works without it. *(The API supports it; the UI toggle comes in a later version.)*

## Paid option (off unless you turn it on)

`CLIPFORGE_IMAGE_PROVIDER=openai` + `OPENAI_API_KEY=…` uses OpenAI Images (`gpt-image-1`), billed per image. An `OPENAI_API_KEY` alone does **not** enable it. External providers require a consent tick before any prompt or frame is sent.

## Testing status

- Built-in director, frame extraction, studio, versions, export and validation: tested (unit, API and browser E2E).
- Stable Diffusion WebUI, OpenAI Images and the Ollama/OpenAI text model: tested only against a **fake local server** that mimics their documented APIs (requests, responses, errors, cancel). **Not yet run against the real services.**

## Not built yet

Automated design scoring/review, conversational refinement through a text model, image upload in the studio UI (the API exists), crop handles, version side-by-side compare, background removal / subject cut-outs, vision-model scene understanding.
