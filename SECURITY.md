# Security

RJClip is a **local, single-user** application. Security is designed in now so it stays sound as features (AI providers, cloud mode) are added.

## Threat model (local mode)

| Asset | Threat | Controls |
|---|---|---|
| User's media & projects | Another website in the same browser sends requests to `localhost` (CSRF, DNS rebinding) | Bound to `127.0.0.1` only. `TrustedHostMiddleware` rejects foreign `Host` headers. Every state-changing request must carry `X-RJClip: 1` (a cross-origin page can't add it without a CORS preflight, which is never granted). Foreign `Origin` → 403. |
| Files on the computer | Path traversal via ids, filenames or export names | Paths are built only from server-generated 32-hex ids. Every id is regex-validated. `safe_join` re-resolves and checks containment, including symlinks. Uploaded filenames are display-only. Export names are sanitized to `[A-Za-z0-9 _.-]`. |
| Files on the computer | **Malicious media** making FFmpeg read other files or the network (HLS/concat playlists, `file:`/`http:` references) | FFmpeg/FFprobe open untrusted inputs with `-protocol_whitelist file` and a **demuxer whitelist** (mov/mp4/matroska/webm/avi/mp3/wav/aac/flac/ogg). Playlist demuxers are excluded. Regression test: a concat playlist disguised as `.mp4` is rejected. |
| The machine | Command injection | FFmpeg is always called with argument lists (never a shell). No user string reaches a filter graph except validated numbers. |
| Availability | Huge uploads, decompression bombs, hung processes | Per-file upload limit, workspace quota and free-disk check. Every FFmpeg/FFprobe call has a timeout. Single job worker by default. Cancellation kills the process. |
| Integrity | Crash mid-save corrupting a project | Atomic write + fsync + `.bak` fallback. Schema validation on every load and save. |
| Integrity | Original footage modified | Originals stored read-only. All editing is non-destructive. Renders write to `exports/`. |
| Browser | XSS | React escapes all text. Strict CSP (`script-src 'self'`, no inline scripts, `frame-ancestors 'none'`), `nosniff`, `no-referrer`. |
| Privacy | Media content leaking into logs | Access logging off. Logs contain job ids and FFmpeg errors, never media content. No telemetry, no external network calls. |

## Assumptions

- The local OS account is trusted (anyone with it can read the workspace anyway).
- FFmpeg itself is kept up to date. Demuxer bugs are mitigated by the whitelist, not eliminated. Running workers as a separate low-privilege user or in a sandbox is planned (Phase 7).
- `RJCLIP_HOST` set to anything other than `127.0.0.1` exposes the app **without authentication**. The server prints a warning. Don't do this on untrusted networks.

## Future cloud mode (not implemented)

Requires, before any deployment: identity provider or Argon2id passwords, secure HttpOnly SameSite cookies, CSRF tokens, per-user project ownership checks on every route, object storage with per-user prefixes and signed URLs, isolated FFmpeg workers (container per job, no network, CPU/mem/time limits), SSRF protection for any URL-based import, rate limiting, secret management (no keys in repo or logs), dependency scanning, and a dedicated multi-tenant threat model (file isolation, worker escape, DoS via expensive renders).

## Reporting

This is a personal project. Open a GitHub issue marked **security** (don't include exploit details publicly) or contact the maintainer.
