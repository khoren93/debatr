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
  app/api/            routers: auth, billing (Stripe), debates, gallery (+ leaderboard), reactions
                      (likes/votes), models, presets, stream (SSE), media; serializers.py builds
                      the shared response models
  app/services/       orchestrator (RQ jobs), scheduler (turn order), prompt_builder,
                      openrouter_client, events (pub/sub), queue_manager, credits (ledger),
                      estimate (pre-run cost), verdict (structured verdict), moderation (AI gallery
                      check + auto-publish), views (view counter),
                      engagement (likes/audience votes), ranking (trending score, model leaderboard)
  app/services/media/ audio pipeline: script (markdown→speech), tts/ (elevenlabs, edge),
                      ffmpeg, highlights (LLM picks shorts), visuals (LLM visual director),
                      jobs (build_media_job), timeline
  app/schemas/timeline.py  Timeline contract shared with frontend/src/api/timeline.ts;
                      visuals.py = scene specs shared with frontend/src/api/visuals.ts
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
                      useModels, useBillingConfig, useVoices (wizard voice catalogue),
                      useLeaderboard (cached model ranking), useElevenLabsKeyStatus (checks
                      the browser's ElevenLabs key)
  src/components/ui/  design-system primitives (Button, Card, Chip, Segmented, Field, Pill,
                      Progress, Modal/ConfirmDialog, Toast, Avatar/SpeakerBadge, Thumb, Logo,
                      ModelIcon — provider logo of a model id via src/lib/modelIcons.ts)
  src/components/layout/AppShell.tsx  sidebar + mobile top bar/bottom tabs, Page, PageTitle
  src/components/cards/    DebateCard (library / gallery / landing)
  src/components/create/   wizard steps + wizardState.ts (state, persistence, config mapping),
                           ModelPicker (searchable OpenRouter list: logos, prices, rank, Latest
                           filter), VoicePicker (voice list with previews, debate-language / all scope),
                           PersonaPicker (persona preset dropdown), usePickerPopover
  src/components/debate/   player, live card, turn timeline, transcript, verdict, audio tab,
                           regenerate-audio dialog, exports aside (browser MP4 render), lineup,
                           AudienceVote (blind vote), LikeButton
  src/components/account/  credits, usage, local keys, ledger, security cards; auth layout/fields
  src/video/          Remotion compositions (DebateLong 16:9, DebateShort 9:16) + render.ts;
                      visuals/ = scene renderer (SceneStage, 20 scene views, rough.js strokes,
                      drawn Lucide pictograms in icons.ts, lazy world map in geo.ts)
  src/pages/          Landing (/), Library (/library), Gallery (/gallery), Leaderboard (/leaderboard),
                      CreateDebate (/create, `?draft=<id>`, `?remix=<id>`),
                      DebateView (/debate/:id and public /d/:slug), Account (/account),
                      Login (/login), Register (/register)
design/             the Claude Design mockup (`AI Debates Studio.dc.html` + `support.js`)
docker-compose.yml  full stack; docker-compose.dev.yml = only Postgres + Redis for native dev
```

## Commands

The root `Makefile` wraps the commands below (`make` lists them: `make up`, `make down`, `make check`,
`make deploy` runs `deploy.sh` (on the server), `make logs s=api`, …).

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

### Gallery moderation and auto-publish

- Debates are public by default: `DebateConfig.auto_publish` (wizard switch on the Review step,
  default on). The cheap verdict-structuring call (`services/verdict.py`) also returns a hidden
  `moderation` answer (`services/moderation.MODERATION_RULES`: controversy is fine; hate, sexual
  content, incitement, harmful instructions, attacks on real private people, spam/tests are not).
  It is stored in `debates.moderation_status` (`none | approved | flagged | rejected`) and
  `moderation_json` (`reason`, `source` llm|fallback|admin, `publish_requested`), never in
  `verdict_json`. `finish_debate_job` runs a stand-alone check when the verdict step gave no answer
  (fails closed: flagged) before the status turns `completed`, then publishes approved debates
  whose owner wants them public and whose turns all succeeded (`moderation.should_auto_publish`).
- Flagged debates stay private: the owner's Publish only sets `publish_requested`; the admin panel
  (Debates, filter Moderation=flagged) has Approve / Reject actions, and publishing from the admin
  session approves. Rejected debates cannot be published by the owner. `moderation` in
  `DebateDetail` goes to the owner/admin only; configs from before auto-publish count as `false`.
Stopping: `POST /api/debates/{id}/stop` sets the status, sets `debate:{id}:stop` in Redis
(checked by the worker every few chunks) and publishes `debate_stopped`.

### Likes, audience votes and the model ranking

- `debate_likes` / `debate_votes` (PK `user_id, debate_id`) with denormalized
  `debates.likes_count` / `votes_count` (atomic increments in `services/engagement.py`; the admin
  Like/Vote views call `recount` after deletes). Only signed-in non-owners can like or vote, only on
  public debates; votes also need `status=completed` and ≥2 debaters (`like_blocker`/`vote_blocker`).
- `PUT|DELETE /api/debates/{id}/like`, `PUT|DELETE /api/debates/{id}/vote` (`participant_id` of a
  debater; a second PUT moves the vote). `DebateDetail.engagement` carries likes, `liked` and the
  `audience` split (`counts`, `my_vote`, `can_vote`, `reason`).
- Blind voting is a frontend rule: for a viewer who could vote, the judge's verdict (Verdict tab,
  verdict turn in the transcript) and the split stay hidden until they vote or click reveal;
  gallery/landing cards show likes instead of the winner.
- `GET /api/gallery?sort=new|trending|top&period=week|month|year|all&model=<id>`; trending is
  `services/ranking.trending_score` mirrored in SQL by `routes_gallery.trending_sql`.
- `GET /api/gallery/leaderboard`: Bradley–Terry ratings (Elo-like scale, 1000 = average,
  `PRIOR_GAMES` virtual games damp single votes) from audience votes on public completed debates;
  each vote is a win of the chosen model over every other model in the debate, mirror matches are
  ignored. Lists only models that argued in a public debate; `is_free` comes from the OpenRouter
  catalogue. The wizard's speaker cards show each model's rank and link to `/gallery?model=`.

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
   `MEDIA_ROOT/{debate_id}/turns/`, mixes `full.wav`/`full.mp3`, designs the visual scenes
   (below, when `MediaOptions.visuals`), asks a cheap LLM for short-video highlights and writes
   `timeline.json` (`app/schemas/timeline.py`).
   Progress lives in `media_json` (polled by `GET /api/debates/{id}/media`); `media_status`
   is `none | queued | running | ready | error`.
8. Files are served by `MediaStaticFiles` at `/api/media/files/{debate_id}/...` (Range
   requests work). The debate page plays the track with karaoke words (`AudioTab`) and renders
   MP4s **in the visitor's browser** (`components/debate/ExportCard.tsx` +
   `@remotion/web-renderer`) — the server never encodes video; finished renders are reported to
   `POST /api/debates/{id}/renders` for the usage stats. Premium voices on the system ElevenLabs
   key cost `TTS_CREDIT_PRICE_PER_1K_CHARS` in credits (charged after the build); own keys are free.
   There are no plans, only the prepaid balance (like OpenRouter): with an empty balance and no
   own key premium voices are locked in the wizard and the regenerate dialog, and `POST /media`
   answers 402. Only an own key ElevenLabs accepts unlocks them: `useElevenLabsKeyStatus` checks
   it via `GET /media/voices` (502 = rejected) and a rejected key is neither used nor sent.
   `output_style=spoken` in `DebateConfig` asks the models for plain spoken prose with
   optional `[emotion]` tags, which ElevenLabs v3 understands.

### Visual scenes (charts and drawn schemes in the video)

- `services/media/visuals.py` ("visual director", `MEDIA_VISUALS_MODEL`, default Gemini Flash,
  system key, not billed; cost in `timeline.stats.visuals_usd`) runs per turn in parallel after
  the mix. `scene_budget` ≈ one scene per 18 s of speech; the reply holds one spare scene and
  `diversify` drops repeats across turns. Turn plans are cached in `turns/{seq}.visuals.json`
  (hash of text, opponent, model, `PROMPT_VERSION`); `force` re-plans. A failure only loses scenes.
- Scenes are typed data only (`app/schemas/visuals.py`) — never code or markup. The director
  may design 19 types (`DirectorScene`: stat, bars, line, pie, proportion, ranking, map, bullets,
  versus, scale, matrix, venn, definition, flow, timeline, quote, rebuttal, headline, icons); the
  prompt carries a JSON template, a sample phrase per type and a "which type fits" guide
  (`CHOOSING`). The models clip long strings instead of rejecting; `parse_scenes(speech=…)`
  enforces content rules: numbers must appear in the speech (`is_grounded`, small integers ≤ 12
  pass; `ranking`/`map` lose invented values instead of the scene), no self-quotes, `rebuttal`
  only with an opponent turn (its `claim_author` is set by code). The prompt lists the
  debaters' names; `debater_label` turns "Debater One" into "Debater 1", and the frontend paints
  a side named after a debater in that debater's colour (`sideColors`).
- `scoreboard` is not designed by the model: `scoreboard_visual` builds it from the structured
  verdict (`winner_id`, `headline`; a draw only when `verdict_json` came from the LLM), shows it
  when the judge announces the result (`announcement_index`: a win word next to the winner's
  name) or before the verdict ends, and `make_room` cuts the director's scenes around it.
- `map` scenes take ISO alpha-3 codes (`schemas/geo.py`: alpha-2, a few English names and `EU`
  are normalized; countries missing from the 110m atlas are dropped). `frontend/.../geo.ts`
  holds the same `COUNTRY_TABLE`, draws `world-atlas` 110m with d3-geo (Natural Earth, zoomed to
  the highlighted mainlands) and is a lazy chunk: `ExportCard` awaits `preloadSceneAssets`
  before an MP4 render, `useGeo` holds the frame with `useDelayRender` otherwise.
- Timing: every scene and element carries an `anchor` (exact words); `align_scenes` finds them in
  the word timestamps (`highlights.locate_quote`), so `Timeline.visuals[]` has absolute
  `start_ms`/`end_ms`/`item_ms`, non-overlapping, recomputed on every audio build. `item_ms`
  follows the order of the scene's lists; `UNORDERED_ITEMS` (ranking, scale, map) search every
  element on its own, since a countdown or the two pans are not said in list order.
- Rendering (`src/video/visuals/`): `SceneStage` sits in the centre of both compositions
  (16:9: host chip on top, debaters in side columns 1+1 / 2+1 / 2+2, captions below; 9:16:
  debater row, stage, captions) and shows the speaking character/topic when no scene is up.
  The web renderer serializes each `<svg>` into an image, so strokes animate via SVG attributes
  (`pathLength=1` + dashoffset), colours are attributes (no `currentColor`), text stays in HTML,
  and rough.js shapes use a fixed seed per scene (random seeds jitter between frames).
  Icon keys in `icons.ts` mirror `ICONS` in `schemas/visuals.py`.

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
- ElevenLabs voice lists: `/v1/voices` holds only the account's voices (premade ones are English).
  For other languages `tts/elevenlabs.list_voices` adds native Voice Library voices
  (`/v1/shared-voices?language=`, no surcharged ones) — on paid plans only: free plans get
  `402 paid_plan_required` for library voices, so those (incl. ones copied into "My Voices",
  `sharing.status=copied`) are hidden. The plan comes from `/v1/user/subscription`; lists are
  cached per key+language for 5 min.
- Without `ELEVENLABS_API_KEY` the UI offers only the free Edge voices (unofficial API, few
  voices per language) or a user-supplied ElevenLabs key.
- Model logos: OpenRouter's API has no icons. `frontend/public/model-icons/` holds a curated set
  of LobeHub Icons SVGs (MIT, see its README), mapped by model author in `src/lib/modelIcons.ts`;
  files without `-color` are drawn as a CSS mask in `currentColor`. Add a mapping (and the SVG)
  when a new provider appears; unknown authors get a letter tile.
- Browser MP4 export: `@remotion/web-renderer` rounds scaled sizes up and H.264 needs even
  sides, so 720p uses exactly `SCALE_720P = 2 / 3` (0.6667 gave 1281×721 and failed).
- Old rows may have `turn_type=moderator_comment` and inline `"[Error ...]"` text; both are still
  handled (`scheduler.MODERATOR_TURN_TYPES`, `lib/format.isErrorTurn`). Debates created before
  accounts have `user_id=NULL`: readable via their link, manageable only from the admin panel.
- The wizard keeps its in-progress state in `localStorage` (`debatr.wizard.v1`). Browser-only
  keys (`debatr.openrouter_key`, `debatr.elevenlabs_key`) live in `src/lib/localKeys.ts`
  (`useLocalKey`), are managed on the Account page (`LocalKeysCard`; the wizard only shows their
  status and links there in a new tab — the `storage` event syncs them back), and are
  sent as transient `user_provider_key` / `user_tts_key` (never in `config_json`, stripped from
  draft saves). The wizard's default model is `openrouter/free` (`FREE_ROUTER_ID`). With `user_tts_key` the API parks it in Redis (`debate:{id}:tts_key`) so
  `_auto_media` builds premium audio on the user's key without charging credits.
