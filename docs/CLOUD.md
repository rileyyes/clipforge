# Cloud deployment design (not built)

RJClip is designed and tested as a **single-user app on your own computer**, and that's how it should be run today. This document sets out what a hosted, multi-user version would need. **Don't expose the current server to the internet.** It has no accounts and trusts anyone who can reach it. That's safe on `127.0.0.1` and unsafe anywhere else.

## Why the local app is safe, and what changes in the cloud

| Local today | Why it's enough locally | Cloud requirement |
|---|---|---|
| Binds to `127.0.0.1`; Host and Origin allow-lists; `X-RJClip` CSRF header | Only your own browser can reach it | Real accounts (OIDC), sessions or tokens, per-request authorisation on every project/media/job id |
| One workspace folder | It's your disk | Per-tenant storage (S3/GCS) with per-object authorisation; no shared filesystem paths in the API |
| FFmpeg runs in-process with input format and protocol allow-lists | You only upload your own files | **Untrusted media is the main risk**: run FFmpeg/OpenCV/Pillow in sandboxed, network-less workers (gVisor/Firecracker or a locked-down container: no network, read-only root, seccomp, CPU/memory/time limits, and a fresh worker per job) |
| Thread-pool job queue, JSON job files | One user | A durable queue (e.g. Postgres + workers, or SQS); per-user quotas and concurrency limits; idempotent retries |
| JSON project files, atomic writes | Single writer | Postgres for projects and versions (the JSON document fits a `jsonb` column), with optimistic concurrency on `edit_revision` (already in the API) |
| Speech-to-text and the optional SD/OpenAI providers run locally | Free, private | GPU workers for Whisper; consent and data-handling notes before any third-party AI provider sees user content |

## Proposed architecture

```
Browser ──HTTPS──► CDN (static UI) 
        └─HTTPS──► API (stateless, autoscaled)  ── Postgres (projects, versions, jobs, users)
                        │ signed upload URLs        └─ object storage (media, renders, library), per-tenant prefixes
                        └─► queue ──► sandboxed media workers (FFmpeg, analysis, render; no network)
                                   └► GPU workers (Whisper)
```

- **Uploads** go straight to object storage with short-lived signed URLs, sized and typed at creation. A worker then probes the file (`ffprobe` with the same allow-lists) before it is marked usable.
- **Exports** are written by workers to storage and downloaded via signed URLs. Range streaming for previews also uses signed URLs or a small authorising proxy.
- **The render cache** becomes per-tenant (key prefix) so one user's segments are never served to another, even with equal hashes.

## Threat model

| Threat | Mitigation |
|---|---|
| Malicious media exploiting FFmpeg/OpenCV/libav parsers | Sandboxed, network-less, short-lived workers; format/protocol allow-lists (existing); keep FFmpeg patched; resource limits |
| SSRF/LFI through FFmpeg protocols or playlists (`concat`, `http`, `file` tricks) | `-protocol_whitelist file` (existing) plus no network in workers; concat lists are written by RJClip only (existing) |
| IDOR: guessing another user's project/media ids | Ids are random 128-bit (existing), but **authorise every lookup by tenant**; never rely on unguessable ids alone |
| XSS through file names, captions, labels | React escaping (existing), strict CSP (existing), `nosniff` (existing); images re-encoded (existing) |
| Zip bombs / huge uploads / decode bombs | Size caps (existing), duration/pixel caps before decode, per-job time and memory limits |
| Resource exhaustion (long renders, many jobs) | Per-user quotas, queue concurrency limits, job timeouts (existing `render_timeout_s`) |
| Secrets (OIDC, storage keys, AI provider keys) | Secret manager; never sent to the browser; workers get scoped credentials only |
| Third-party AI providers seeing user content | Off by default (existing); explicit per-project consent; documented retention |
| Account takeover | OIDC with MFA available; short sessions; re-auth for destructive actions |

## Effort estimate

Roughly 4–6 weeks for a careful first version: accounts and authorisation, storage abstraction, queue and workers, sandboxing, quotas, and a security review. Most of the editing, analysis and rendering code can be reused unchanged. It already works with explicit paths and validated documents, and the API is generated and documented (`/api/openapi.json`).
