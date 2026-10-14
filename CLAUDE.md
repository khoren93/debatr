# AI Debates (Debatr) — developer guide

Full-stack service that orchestrates structured debates between LLMs via OpenRouter, streams
them to the browser in real time, voices them and renders videos in the browser. Users have
accounts with prepaid credits (Stripe top-ups); finished debates can be published to a gallery.
The UI follows the Claude Design mockup in `design/AI Debates Studio.dc.html` (brand "Debatr",
dark studio theme, accent `#D9FF3D`).

## Layout

```
backend/            FastAPI API + RQ worker (Python 3.12+, managed with uv)
  app/main.py         FastAPI app, session + CORS middleware, admin panel, /api/health
  app/worker.py       RQ worker entrypoint (`python -m app.worker`)
  app/core/           config (pydantic-settings), db (async SQLAlchemy), redis, logging,
                      ratelimit, auth (session-cookie login deps), security (bcrypt, Fernet), ids
  app/api/            routers: auth, billing (Stripe), debates, gallery, models, presets,
                      stream (SSE), media; serializers.py builds the shared response models
  app/services/       orchestrator (RQ jobs), scheduler (turn order), prompt_builder,
                      openrouter_client, events (pub/sub), queue_manager, credits (ledger),
                      estimate (pre-run cost), verdict (structured verdict), views (view counter)
  app/services/media/ audio pipeline: script (markdown→speech), tts/ (elevenlabs, edge),
                      ffmpeg, highlights (LLM picks shorts), jobs (build_media_job), timeline
  app/schemas/timeline.py  Timeline contract shared with frontend/src/api/timeline.ts
  app/models/         SQLAlchemy ORM models (User, CreditTransaction, Debate, Turn, …)
  app/schemas/        Pydantic request/response schemas (schemas, auth, billing, media)
  migrations/         Alembic (async env)
  tests/              pytest (pure unit tests, no DB/Redis needed)
frontend/           React 19 + Vite 8 + Tailwind 4 + TypeScript
  src/index.css       Tailwind theme tokens (colors ink/surface/accent/pro/con/host…, fonts, radii)
  src/api/            axios client, typed API functions per area (auth, billing, debates,
                      gallery, media, models), shared types.ts, timeline.ts
  src/auth/           AuthContext (useAuth), RequireAuth route guard
  src/hooks/          useDebateStream (SSE), useDebateMedia (polling), useAudioClock,
                      useModels, useBillingConfig, useVoices (wizard voice catalogue)
  src/components/ui/  design-system primitives (Button, Card, Chip, Segmented, Field, Pill,
                      Progress, Modal/ConfirmDialog, Toast, Avatar/SpeakerBadge, Thumb, Logo…)
  src/components/layout/AppShell.tsx  sidebar + mobile top bar/bottom tabs, Page, PageTitle
  src/components/cards/    DebateCard (library / gallery / landing)
  src/components/create/   wizard steps + wizardState.ts (state, persistence, config mapping)
  src/components/debate/   player, live card, turn timeline, transcript, verdict, audio tab,
                           regenerate-audio dialog, exports aside (browser MP4 render), lineup
  src/components/account/  credits, usage, key, ledger, security cards; auth layout/fields
  src/video/          Remotion compositions (DebateLong 16:9, DebateShort 9:16) + render.ts
  src/pages/          Landing (/), Library (/library), Gallery (/gallery), CreateDebate (/create),
                      DebateView (/debate/:id and public /d/:slug), Account (/account),
                      Login (/login), Register (/register)
design/             the Claude Design mockup (`AI Debates Studio.dc.html` + `support.js`)
docker-compose.yml  full stack; docker-compose.dev.yml = only Postgres + Redis for native dev
```

## Commands

Backend (run from `backend/`):

```bash
uv sync                                   # create .venv and install (incl. dev tools)
uv run uvicorn app.main:app --reload      # API on :8000 (docs at /api/docs)
RQ_SIMPLE_WORKER=true uv run python -m app.worker   # worker for both queues (SimpleWorker avoids fork issues on macOS)
uv run python -m app.worker --queues media          # media-only worker (needs ffmpeg on PATH)
uv run alembic upgrade head               # apply migrations
uv run alembic revision --autogenerate -m "describe change"
uv run ruff check . && uv run ruff format .   # lint + format
uv run pyright                            # type check
uv run pytest -q                          # tests
```

Frontend (run from `frontend/`):

```bash
npm install
npm run dev        # Vite on :5173, proxies /api -> http://localhost:8000 (incl. SSE)
npm run check      # tsc + eslint
npm run build
```

Infrastructure:

```bash
docker compose -f docker-compose.dev.yml up -d   # Postgres :5432 + Redis :6379 for native dev
docker compose up -d --build                     # full stack on http://localhost (migrations auto-run)
./deploy.sh                                      # production (adds docker-compose.prod.yml)
```

## Architecture and data flow

0. Accounts: `POST /api/auth/register|login` set `request.session["uid"]` in the signed session
   cookie (the admin panel uses the same cookie under `token`). `get_current_user` /
   `require_user` in `app/core/auth.py`. New accounts get `SIGNUP_BONUS_USD` credits.
1. `POST /api/debates` (signed-in users only) validates `DebateConfig`, estimates the run
   (`services/estimate.py`) and rejects with 402 when credits are insufficient, stores the debate
   (`status=queued`, or `draft` when `draft=true`) with `user_id` and `config_json.billing.own_key`,
   puts the OpenRouter key to use in Redis (`debate:{id}:provider_key`, TTL) — the request key or
   the account's encrypted key, never in Postgres — and enqueues `start_debate_job`.
   `POST /api/debates/{id}/start` queues a draft; `PATCH` replaces a draft's config.
2. The worker chains RQ jobs: `start_debate_job` → `process_turn_job(seq_index)` per turn →
   `conduct_verdict_job` → `finish_debate_job`. Each job opens its own blocking DB session
   (`NullPool`, safe across RQ forks).
3. `scheduler.build_schedule()` is the single source of truth for turn order:
   each round = moderator (intro / transition) + every debater; debater turn types are
   `opening` / `rebuttal` / `closing` (or `argument` for single-round debates). The verdict
   (`turn_type=verdict`, `round_id=verdict`) is appended after the last scheduled turn.
4. `openrouter_client.stream_chat_completion()` streams deltas and returns usage
   (tokens + cost). On HTTP 400 with a system prompt it retries once with the system prompt
   merged into the user message. Mid-stream `{"error": ...}` chunks raise `OpenRouterError`.
5. The worker publishes events to Redis channel `debate:{id}`; `GET /api/debates/{id}/stream`
   relays them as SSE and closes on a terminal event (or immediately if the debate is already
   finished). After the verdict turn `services/verdict.py` structures it with the cheap
   `MEDIA_HIGHLIGHTS_MODEL` (regex fallback) into `debates.verdict_json`
   (`winner_id`, `headline`, `feedback`). At the terminal state `services/credits.py` charges the
   owner (`cost × CREDIT_MARKUP`, skipped with an own key; idempotent via `provider_ref`) and
   `_auto_media` queues the audio build when `config_json.media_plan.outputs` contains `audio`.

SSE events: `connected`, `debate_started`, `turn_started`, `turn_delta`, `turn_completed`,
`turn_error`, `verdict_ready`, `media_progress`, `debate_completed`, `debate_error`,
`debate_stopped`. `turn_completed` / `turn_error` carry the full serialized turn (`TurnOut`).

Debate statuses: `draft | queued | running | completed | error | stopped`.
Access: owners and the admin session manage a debate; public (`is_public`, `slug`, `/d/{slug}`,
`GET /api/gallery/{slug}`) and ownerless legacy rows are readable by anyone
(`app/api/serializers.can_view / can_manage`). `POST /api/debates/{id}/publish` assigns the slug.
Stopping: `POST /api/debates/{id}/stop` sets the status, sets `debate:{id}:stop` in Redis
(checked by the worker every few chunks) and publishes `debate_stopped`.

### Media pipeline (audio on the server, video in the browser)

6. `POST /api/debates/{id}/media` (finished debates only) stores the chosen TTS options in
   `debates.media_json`, sets `media_status=queued` and enqueues `build_media_job` on the
   `media` RQ queue (`MEDIA_JOB_TIMEOUT`). An optional user ElevenLabs key goes to Redis
   (`debate:{id}:tts_key`), never to Postgres. ElevenLabs builds on the system key are paid
   from the owner's credits (admin session or `X-Media-Token` are exempt). The system key is
   probed (`tts/elevenlabs.system_key_status`, cached) so a rejected key disables premium
   voices in the UI instead of failing later; the key needs the Text to Speech, Voices read,
   User read and Forced alignment permissions.
7. The job cleans each turn's Markdown (`media/script.py`), synthesizes it with the provider
   (`elevenlabs` with word timestamps / forced-alignment fallback, or the free `edge` voices),
   normalizes loudness with ffmpeg, caches per-turn WAV+JSON by content hash under
   `MEDIA_ROOT/{debate_id}/turns/`, mixes `full.wav`/`full.mp3`, asks a cheap LLM for
   short-video highlights and writes `timeline.json` (`app/schemas/timeline.py`).
   Progress lives in `media_json` (polled by `GET /api/debates/{id}/media`); `media_status`
   is `none | queued | running | ready | error`.
8. Files are served by `MediaStaticFiles` at `/api/media/files/{debate_id}/...` (Range
   requests work). The debate page plays the track with karaoke words (`AudioTab`) and renders
   MP4s **in the visitor's browser** (`components/debate/ExportCard.tsx` +
   `@remotion/web-renderer`) — the server never encodes video; finished renders are reported to
   `POST /api/debates/{id}/renders` for the usage stats. Premium voices on the system ElevenLabs
   key cost `TTS_CREDIT_PRICE_PER_1K_CHARS` in credits (charged after the build); own keys are free.
   `output_style=spoken` in `DebateConfig` asks the models for plain spoken prose with
   optional `[emotion]` tags, which ElevenLabs v3 understands.

### Credits and payments

- `users.credits_usd` is the balance; `credit_transactions` is the append-only ledger. Every
  change goes through `services/credits.apply_transaction(_sync)`; `provider_ref` makes charges
  and Stripe sessions idempotent. The balance may go slightly negative (actual cost > estimate).
- `POST /api/billing/checkout` creates a Stripe Checkout session (`stripe.StripeClient`,
  `v1.checkout.sessions`); `POST /api/billing/webhook` (`checkout.session.completed` / `async_payment_succeeded`) and
  `GET /api/billing/confirm?session_id=` (called by the Account page after redirect) credit it.
  `DEV_FAKE_PAYMENTS=true` (non-production) credits instantly without Stripe.
- `GET /api/billing/usage` aggregates the current month (tokens, voice ms, renders, spend).
- A personal OpenRouter key (`PUT /api/auth/me/openrouter-key`) is validated against OpenRouter,
  stored encrypted with `SECRET_KEY` (`core/security.py`) and shown masked (`…last4`).

## Conventions

- Python: ruff (line length 100, isort), pyright `standard`, type hints everywhere,
  `logging` instead of `print`. Keep worker code synchronous except the streaming loop.
- Schema changes: edit `app/models/models.py`, then `uv run alembic revision --autogenerate`.
  Timestamps are timezone-aware (`DateTime(timezone=True)`, UTC). JSON columns use `default=dict`.
- API responses use Pydantic models from `app/schemas/schemas.py`; keep `frontend/src/api/types.ts`
  in sync with them.
- Frontend: strict TS, `eslint-plugin-react-hooks` v7 (React Compiler rules: no synchronous
  setState in effects — fetch in effects with a `cancelled` flag and set state in the promise
  callbacks; no mutation of props/state, use refs for imperative DOM like seeking `<audio>`;
  no manual `useMemo` that the compiler cannot preserve). API calls go through `src/api/*`,
  never raw axios. No `alert`/`confirm`: use `useToast` and `ConfirmDialog`. Styling uses the
  theme tokens from `src/index.css` (`bg-surface`, `text-muted`, `font-display`, `rounded-panel`…).
- Brand name and copy live in `src/lib/brand.ts`; speaker colours in `src/lib/format.ts` mirror
  `backend/app/services/media/timeline.py` (PALETTE / MODERATOR_COLOR / JUDGE_COLOR).
- Tests are pure (no DB/Redis). Use `httpx.MockTransport` via `OpenRouterClient(transport=...)`
  for client tests. Put integration checks behind Docker.

## Gotchas

- `.env` is shared by Docker and native dev: leave `DATABASE_URL`/`REDIS_URL` unset so the
  localhost defaults apply natively; docker-compose injects the container URLs.
- Postgres stays on major version 15 in compose — bumping it requires migrating the volume.
- The `frontend` container name (`ai-debates-frontend-1`) is referenced by the external Caddy
  on the production host via the `caddy_net` network.
- `DEBATE_CREATE_RATE_LIMIT` (per IP per hour) and `LOGIN_RATE_LIMIT` are extra abuse limits on
  top of accounts/credits; set 0 to disable.
- Stripe: without `STRIPE_SECRET_KEY` the checkout endpoint returns 503 and the Account page
  disables top-ups; the Stripe webhook must reach `/api/billing/webhook` (Caddy proxies `/api*`).
- Changing `SECRET_KEY` invalidates every login cookie and makes stored OpenRouter keys
  undecryptable (users must re-enter them).
- Media: `MEDIA_ROOT` is `./media` natively and the `media_data` volume (`/media`) in Docker;
  the worker image target installs ffmpeg, the api target does not. Docker runs `worker`
  (`--queues default`) and `media-worker` (`--queues media`); natively one worker takes both.
- Without `ELEVENLABS_API_KEY` the UI offers only the free Edge voices (unofficial API, few
  voices per language) or a user-supplied ElevenLabs key.
- Old rows may have `turn_type=moderator_comment` and inline `"[Error ...]"` text; both are still
  handled (`scheduler.MODERATOR_TURN_TYPES`, `lib/format.isErrorTurn`). Debates created before
  accounts have `user_id=NULL`: readable via their link, manageable only from the admin panel.
- The wizard keeps its in-progress state in `localStorage` (`debatr.wizard.v1`). Browser-only
  keys (`debatr.openrouter_key`, `debatr.elevenlabs_key`) live in `src/lib/localKeys.ts`
  (`useLocalKey`), are managed on the Account page (`LocalKeysCard`) and in the wizard, and are
  sent as transient `user_provider_key` / `user_tts_key` (never in `config_json`, stripped from
  draft saves). With `user_tts_key` the API parks it in Redis (`debate:{id}:tts_key`) so
  `_auto_media` builds premium audio on the user's key without charging credits.
