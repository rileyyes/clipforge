# Dependencies, licenses & costs

**Running cost: $0.** No paid services, no API keys, no network calls.

## Runtime

| Dependency | Version | License | Purpose |
|---|---|---|---|
| Python | ≥ 3.11 | PSF | backend |
| Starlette | ≥ 0.40 | BSD-3 | HTTP framework (FastAPI's foundation) |
| Pydantic | ≥ 2.7 | MIT | schema & validation |
| Uvicorn | ≥ 0.30 | BSD-3 | ASGI server |
| NumPy | ≥ 1.26 | BSD-3 | waveform peak computation |
| FFmpeg / FFprobe | ≥ 6.0 | LGPL-2.1+ / GPL-2+ (build-dependent) | decode, analyse, render. Called as an external program, not linked. Builds with libx264 are GPL. Fine for personal use; check before distributing binaries. |
| React / React DOM | 19 | MIT | UI |

## Development

| Dependency | License | Purpose |
|---|---|---|
| esbuild | MIT | bundling |
| TypeScript | Apache-2.0 | type checking |
| pytest | MIT | backend tests |
| Playwright (Python) | Apache-2.0 | browser E2E |

## Planned (Phase 3+), all free/local

| Candidate | License | Purpose | Notes |
|---|---|---|---|
| faster-whisper (CTranslate2) | MIT | transcription with word timestamps | CPU works. A GPU is ~5–10× faster. Model download ~150 MB–1.5 GB (default "small" ≈ 480 MB). ClipForge decodes audio with FFmpeg and passes samples, so faster-whisper's PyAV decoder isn't used; `av<19` is pinned anyway (PyAV 19 broke faster-whisper 1.2.x). |
| PySceneDetect | BSD-3 | shot detection | or a custom OpenCV frame-diff |
| Optional LLM provider | varies | context reasoning | Off by default. A local model (e.g. via Ollama) or a paid API **only with your approval**. |
