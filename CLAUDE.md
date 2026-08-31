# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Vietnamese text-to-speech reader. A single FastAPI service serves the static frontend, one TTS
API, and one English→Vietnamese translation API. No database, no build step — all user state
lives in browser `localStorage`.

Prose documentation is in Vietnamese under `README.md` and `docs/`. This file is the English
summary for agents; the `docs/` pages carry the depth.

## Commands

```bash
# Deploy (build, wait for healthy, smoke-test, then delete the old image)
./deploy.sh
./deploy.sh --no-cache

# Local dev
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
sudo apt install sox libsox-fmt-mp3        # required for gTTS speed-up
.venv/bin/uvicorn app.main:app --reload --port 8010

# Tests
.venv/bin/python -m pytest                                    # all, offline
.venv/bin/python -m pytest tests/test_text.py                 # one file
.venv/bin/python -m pytest tests/test_text.py::test_name      # one test
.venv/bin/python -m pytest -k markdown                        # filter by name
.venv/bin/python -m pytest -m integration                     # real network, FREE (TTS)
.venv/bin/python -m pytest -m paid                            # real network, COSTS MONEY (Gemini)

# Syntax checks (no linter or formatter is configured)
node --check static/app.js
bash -n deploy.sh

# Diagnostics
curl -s localhost:8000/api/status | python3 -m json.tool
docker compose logs --tail 50
```

`pytest.ini` deselects both network markers by default, so a plain `pytest` run costs nothing.

`integration` is free — gTTS and edge-tts. **Run it before every deploy**: both use unofficial
endpoints, and mocked tests can never catch a provider changing its protocol or blocking the
server.

`paid` calls Gemini and costs real money against a **per-day request** quota, so it is a separate
marker rather than part of `integration`. Run it only when verifying the provider itself — a new
key, a model rename, a prompt change. The whole file is deliberately **two calls**: one
translation asserting every property at once, one failure asserting the error path. Keep it that
way; splitting the assertions into readable single-purpose tests doubles what each run spends.

## Architecture

Request flow for `POST /api/tts`: rate limit by IP → length check → `strip_markdown` + `normalize`
→ `Synthesizer.get_audio`, which checks the disk cache, collapses concurrent duplicates via
single-flight, then calls a provider.

Provider chain, guarded by `ProviderGuard` (`app/breaker.py`):

1. **gTTS** (Google) — default. Sped up `+20%` through `sox tempo`, pitch preserved.
2. **edge-tts** (Microsoft, HoaiMy voice) — used when gTTS fails or the breaker is open.

The breaker exists to stop calling Google *before* Google blocks us: a per-minute token budget
skips gTTS entirely when exhausted, HTTP 429/403 opens the circuit immediately (and suppresses
retries), and recovery probes with a single request after a doubling cooldown.

Each provider's audio is cached under its own key, so fallback audio never shadows the preferred
voice, and a long outage does not re-hit the network on every replay.

`POST /api/translate` is deliberately **outside** this flow. The "Dịch" button rewrites the
textarea in place, like the line-wrap button, so `text.py`, the audio cache and the queue are
untouched and a translation outage cannot reach the primary voice.

`Translator` (`app/translate.py`) sends the whole document to **Gemini** in one call. There is no
fallback provider on purpose: a `503` the user can see beats silently returning a much worse
translation they mistake for a good one. A statistical translator was tried and removed — see
[docs/translation.md](docs/translation.md) for the measurements.

See [docs/architecture.md](docs/architecture.md) and [docs/translation.md](docs/translation.md).

## Non-obvious constraints

These are not derivable from reading the code. Each came from a real incident and is guarded by a
test or a config comment — do not "clean them up".

**Deployment** (details in [docs/operations.md](docs/operations.md)):

- Static asset URLs must carry `?v=<content hash>`. Cloudflare caches static files for 4 hours
  **and overwrites the origin's `Cache-Control`**, so headers cannot force a refresh. Without
  versioning, every deploy serves new HTML with stale JS.
- Every file under `static/` must be world-readable. The container runs as `1001:33` and Docker
  `COPY` preserves source modes; a mode-640 file makes StaticFiles send `200` + `Content-Length`
  and then close with no body, which Cloudflare turns into a 520. This does not reproduce on the
  dev server, which runs as the file owner.
- Never add `security_opt: no-new-privileges:true`. The host runs AppArmor; `no_new_privs` blocks
  the profile transition at `exec`, so every binary in the container — `python` included — fails
  with `operation not permitted`.
- `user: "1001:33"` must match the host owner of `mp3/`. On this host `ubuntu` is uid 1001,
  gid 33, not the usual 1000:1000.
- The public hostname sits behind **Cloudflare Access** (single-user policy). `curl` against
  `langnghe.hipingu.health` returns a Cloudflare sign-in page, not the app — that is expected,
  not an outage. Docker's healthcheck and `deploy.sh` both hit `localhost:8000` and are
  unaffected. Access is what makes it safe to hold a paid API key server-side.

**Code:**

- The retry wrapper in `tts.py` catches broad `Exception` on purpose. `EdgeTTSException` and
  `aiohttp.ClientError` both derive directly from `Exception`, so narrowing to `OSError` would
  make retries never fire for the most common failure and leak a 500 instead of a 503.
- Rate limiting reads `CF-Connecting-IP`. `cloudflared` runs with host networking and connects to
  `127.0.0.1`, so `request.client.host` is `127.0.0.1` for every user.
- `sox` is invoked with `-C 64`. Without it, both sox and ffmpeg re-encode at 32kbps and the
  speed-up silently halves gTTS audio quality.
- No lookbehind regex in `static/app.js`. Safari below 16.4 throws `SyntaxError` at parse time,
  killing the whole script.
- Changing how audio is produced requires bumping `GTTS_VARIANT` / `EDGE_VARIANT` in `tts.py`;
  they are part of the cache key.
- Translations are cached whole (`.txt` beside the `.mp3` files, same `CACHE_MAX_MB` budget),
  keyed on `GEMINI_VARIANT` plus the model name; failed translations are never cached. Editing
  the prompt in a way that changes output requires bumping `GEMINI_VARIANT` — changing the model
  does not, it is already in the key.
- `GEMINI_API_KEY` is the project's only real secret. It must never reach logs, error messages
  (the Gemini URL embeds the key, so the HTTP error body is dropped on purpose) or `/api/status`.
  Locked by `test_status_never_leaks_the_api_key`. It must be an API key from AI Studio starting
  with `AIza`; an `AQ.…` token is a short-lived credential that expires within hours and leaves a
  puzzling `401`.
- The whole document goes to Gemini in **one** call. Splitting it repeats the 174-token system
  prompt per call (36% dearer for a document read end to end) and multiplies request count
  against a **per-day request** quota — per-line translation cannot finish one document a day on
  the free tier.
- `GEMINI_MAX_PER_DAY` is a **cost** ceiling, independent of Access, which is an **access**
  ceiling. It still holds if Access is misconfigured or a loop runs away. Budget is spent only on
  a real outbound call, so re-reading a cached document is free. Set it to `0` to disable Gemini
  without removing the key.

## Text processing

Three stages, in order: `strip_markdown` → `normalize` → (gTTS only) `speak_paths`. Their output
is never shown to the user — the UI always displays the original text.

Every rule is deliberately narrow, and golden tests lock behaviour in **both** directions: what
must change, and what must stay untouched. Before widening any rule, read
[docs/text-processing.md](docs/text-processing.md).

Translation does **not** go through these stages: `translate.py` sends the user's raw text to
Gemini and the requirements live in the prompt.

The key boundary: only strip what is *purely syntax*. gTTS also pronounces `% $ = @ & ^ < >`, but
those are content — "30%" should read as "ba mươi phần trăm". Stripping them is the bug, not the
fix.

Do not guess how a TTS engine reads something. Measure it: synthesize and compare audio duration,
because spelling out is far longer than reading. A ready-made snippet is at the end of
[docs/text-processing.md](docs/text-processing.md).

## Conventions

- Identifiers in English, including test function names.
- Comments in Vietnamese, **with diacritics**.
- Comments should explain *why*, especially where the code looks odd — that is what stops the next
  person from "simplifying" a hard-won fix.
- Commits: `<type>(<scope>): <message>`, English, imperative.

## Further reading

`docs/architecture.md`, `docs/text-processing.md`, `docs/translation.md`, `docs/frontend.md`,
`docs/api.md`, `docs/configuration.md`, `docs/development.md`, `docs/operations.md`.
