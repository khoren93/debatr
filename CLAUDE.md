# AI Debates (Debatr) — developer guide

Full-stack service that orchestrates structured debates between LLMs via OpenRouter, streams
them to the browser in real time, voices them and renders videos in the browser. Users have
accounts with prepaid credits (Stripe top-ups); finished debates can be published to a gallery.
The `debatr` CLI / MCP server (`cli/`) drives the same public API from a terminal or an AI agent.
The UI follows the Claude Design mockup (brand "Debatr", dark studio theme, accent `#D9FF3D`);
a local export may sit in the git-ignored `design/` folder (`Debatr Studio.html`).

## Layout

```
backend/            FastAPI API + RQ worker (Python 3.12+, managed with uv)
  app/main.py         FastAPI app, AdminGate + session + CORS middleware, /api/health (+ /full:
                      workers and scheduler, for an outside uptime monitor)
  app/worker.py       RQ worker entrypoint (`python -m app.worker`)
  app/manage.py       operator commands on the server, not part of the public CLI: `admin grant |
                      revoke | list | reset-2fa | revoke-sessions | enroll-code`, `credits …`
                      (balance changes through the ledger)
  app/admin/          admin console access: gate (host / IP / Fetch Metadata / Origin, outermost
                      middleware), access (sessions → AdminContext, CSRF, roles, sudo)
  app/scheduler.py    periodic jobs (`python -m app.scheduler`, RQ cron on the background queue:
                      hourly trending check, recovery check every minute, alerts check every 5
                      minutes, IndexNow flush every minute in production; `--refresh-trending`
                      builds a batch now)
  app/core/           config (pydantic-settings), db (async SQLAlchemy), redis, logging,
                      ratelimit, auth (session cookie or Bearer API token; session-only deps),
                      security (bcrypt, Fernet, API token format/hash), ids
  app/api/admin/      admin console API (`/api/admin/*`): routes_auth (sign-in, 2FA, sessions,
                      sudo), routes_passkeys (WebAuthn sign-in, sudo, add / remove), routes_overview
                      (tiles, series, money, attention, tops), routes_users (list, CSV, card,
                      ledger, debates, account changes), routes_debates (list, card, moderation
                      queue, debate changes), routes_trending (batches, hide / show, build now),
                      routes_system (queues, workers, scheduler, runs, limits, providers, health),
                      routes_finance (finance series, CSV, models), routes_audit (audit log page,
                      facets, security summary), routes_settings (levers, alerts + test message)
  app/api/            routers: auth, tokens (API tokens + `debatr login` device flow), billing
                      (Stripe), debates, gallery (+ leaderboard), motions (topic page, wizard
                      suggestions), reactions (likes/votes), models,
                      presets, topics (trending per format, AI topic ideas), stream (SSE),
                      media, covers (AI covers of a
                      debate), oembed (`GET /api/oembed`: a pasted link → the player, CORS `*`),
                      status (`GET /api/status`:
                      sign-ups / maintenance for the site), seo (outside /api: robots.txt, the
                      sitemaps, the IndexNow key file); serializers.py builds the shared response
                      models
  app/services/       orchestrator (RQ jobs), formats/ (show formats: seats, limits, turn order,
                      prompts, verdict, round labels; `debate`, `rap_battle`), scheduler (the debate's turn
                      order), prompt_builder (the debate's prompts),
                      api_tokens (token budget, private-by-default, device flow in Redis),
                      openrouter_client, free_router (pins a Free Router participant's model),
                      events (pub/sub), queue_manager, credits (ledger),
                      ledger (row category/title, monthly usage per day, CSV export),
                      estimate (pre-run cost), verdict (structured verdict), moderation (AI gallery
                      check + auto-publish), views (view counter by source: beacon, bots, referrer
                      classes, `view_days`, embedding sites), motions (topics: versions,
                      grouping rules, gallery groups, suggestions, admin move / merge),
                      engagement (likes/audience votes), ranking (trending score, model leaderboard),
                      studio (live scenes per turn, disputes, judge evidence), factcheck (web
                      check of on-screen figures), markers ([visual: …] / [dispute N: …]),
                      trending (RSS news → daily debate and rap battle topics with source
                      links), topic_ideas (the wizard's AI button: own words → topics),
                      seo (canonical paths `/d/{slug}/{kebab}`, robots.txt, sitemap XML),
                      embed (the player for other sites: which page a link names, iframe size
                      and HTML, the oEmbed answer),
                      indexnow (changed public pages → api.indexnow.org once a minute),
                      resume (failed turn → Resume), heartbeat / recovery / fair_share /
                      free_quota (worker safety, see "Workers and queues"), debate_control (stop),
                      usage (provider_usage booking, debate context, ContextThreadPool),
                      activity (user_activity_days, last_seen_at), runtime_settings (levers of
                      the console, cached per process), alerts (Telegram: rules, antispam, job),
                      alert_events (the alert kinds the console can mute)
  app/services/admin/ totp (codes, recovery / enrollment codes, QR), sessions (Redis: sessions,
                      sign-in tickets, code failures), passkeys (WebAuthn options / checks),
                      audit (append-only admin_audit_log: writing, the audit page's queries),
                      stats (overview queries + pure periods / buckets / attention rules),
                      users (list query with SQL totals, pure card statistics, CSV, deletion),
                      debates (debate list / card / moderation queue / trending batches),
                      system (RQ / cron snapshot, runs in flight, limits, health, media scan),
                      finance (money per day / week / month, Stripe reconciliation, model rows)
  app/services/media/ audio pipeline: script (markdown→speech), tts/ (elevenlabs, edge),
                      ffmpeg, highlights (the host model picks shorts), visuals (LLM director),
                      sketch (SVG line art → sanitized path data), images (Commons photos / AI
                      pictures + vision check), jobs (build_media_job), timeline, cover (AI
                      covers: brief, prompt, check, versions, build_cover_job), cover_logos (logo
                      references from the site's renderer + their descriptions)
  app/schemas/timeline.py  Timeline contract shared with frontend/src/api/timeline.ts;
                      visuals.py = scene specs shared with frontend/src/api/visuals.ts
  app/models/         SQLAlchemy ORM models (User, CreditTransaction, Debate, Turn, ProviderUsage,
                      UserActivityDay, ViewDay, AdminAuditLog, …)
  app/schemas/        Pydantic request/response schemas (schemas, auth, billing, media, admin)
  migrations/         Alembic (async env)
  tests/              pytest (pure unit tests, no DB/Redis needed)
frontend/           React 19 + React Router 8 (framework mode, server rendering) + Vite 8 + Tailwind 4 + TypeScript
  react-router.config.ts  `ssr: true`, `appDirectory: src`, `routeDiscovery: initial` (the route
                      manifest comes with the page: navigations never ask the Node server)
  src/root.tsx        the HTML document (`<html lang>` from the page's `handle.lang`, the fonts'
                      preloads, ToastProvider, last-resort ErrorBoundary; no title: every page
                      has `<Seo>`)
  src/fonts.ts        the site's and the console's fonts from our own origin (fontsource variable
                      files with the opsz axis, families "… Variable"; no Google Fonts), the latin
                      files to preload; index.css adds Arial fallbacks with their metrics
                      (`size-adjust` etc., latin only) so the swap moves nothing
  src/routes.ts       route tree: `_site` (AppShell; session + site status + `siteUrl` from the
                      server) → public pages (home, gallery, leaderboard, d/:slug/:kebab?,
                      t/:slug/:kebab?: rendered on the server) | `_client` (login, register,
                      debate/:id: browser only, HydrateFallback, `X-Robots-Tag: noindex`) →
                      `_private` (library, create, account, device: also a session) | `*` (a real
                      404); `embed/:slug` (outside `_site`: the player for other sites' iframes,
                      no session, `handle.framed`); resource routes `og/d/:file`, `og/t/:file`, `og/site.png` (link preview
                      pictures, see "Search engines"), `og/logo.png` (a model's logo as the AI covers'
                      reference picture) and `healthz` (Docker health check)
  src/routes/         route modules: one `load(get)` per public page serves the server `loader`
                      (`serverGet`, the visitor's cookie) and the `clientLoader` (`routeGet`,
                      straight to the API); ErrorBoundary = RouteError / DebateError; public pages
                      add the `microcache` middleware
  src/server/         `*.server.ts`: microcache (cookie-less GETs of public pages, LRU 200 entries /
                      32 MB / 30 s; key = URL + whether the session is known; `sharedMicrocache`:
                      the embed, the same with a cookie or without), siteStatus (30 s memo),
                      site (`siteOrigin`: SITE_URL, else the request's origin); og/ = the link preview
                      cards (Takumi): card.server.tsx (the card's JSX), fonts (bundled + fetched
                      scripts), logos (public/model-icons in the bundle), cache (disk), render
                      (memory LRU, drawing, `ogRoute` for the image routes)
  admin.html, src/admin-main.tsx  the admin console, a separate SPA (vite.admin.config.ts →
                      build/admin with its own admin-assets/; `npm run dev` serves admin.html on
                      /admin* through a plugin in vite.config.ts); vitest.config.ts = unit tests
  src/index.css       Tailwind theme tokens (colors ink/surface/accent/pro/con/host…, fonts, radii)
  src/api/            client.ts = the site's fetch client in axios' shape (`api.get<T>(path,
                      { params })` → `{ data }`, `ApiError.response`; the console keeps axios,
                      `getErrorMessage` reads both), typed API functions per area (auth, billing, debates,
                      gallery, media, models, topics), shared types.ts, timeline.ts;
                      status (site levers); route.ts = route data (`ApiGet`, `routeGet` /
                      `routeError` for client loaders, `toQuery`, `routeErrorOf`); server.server.ts
                      = the SSR server's API client for route loaders (`serverApi` / `serverGet`:
                      API_INTERNAL_URL, else VITE_DEV_API_TARGET, else localhost:8000; forwards
                      cookie, X-Forwarded-For, User-Agent, Accept-Language; 3 s timeout; 4xx → the
                      same status, failure → 503 with Retry-After; never in the browser bundle);
                      admin/ = the console's own client (CSRF header,
                      401 → sign-in), types, auth (+ passkeys), webauthn (navigator.credentials
                      ⇄ JSON), audit, settings
  src/auth/           AuthContext (useAuth; starts from the server's `Viewer`), RequireAuth route
                      guard; viewer.ts (`Viewer`, `viewerContext`) + viewer.server.ts (`readViewer`,
                      `firstParty`); AdminAuthContext (useAdminAuth, RequireAdmin) for the console
  src/hooks/          useDebateStream (SSE), useDebateMedia (polling), useTrendingTopics,
                      useModels, useBillingConfig, useVoices (wizard voice catalogue),
                      useLeaderboard (cached model ranking), useElevenLabsKeyStatus (checks
                      the browser's ElevenLabs key), useEstimate (debounced wizard estimate),
                      useSiteStatus (sign-ups closed / maintenance banner, cached a minute),
                      useMotionSuggestions (debounced: the topic the wizard's text joins),
                      useSiteStatus (+ SiteStatusProvider: the status the server rendered with),
                      useHydrated (false on the server and during hydration), useSiteUrl (the
                      `_site` loader's origin for canonical links)
  src/components/ui/  design-system primitives (Button, Card, Chip, Segmented, Field, Pill,
                      Progress, Modal/ConfirmDialog, Toast, Avatar/SpeakerBadge, Thumb, Logo,
                      Dropdown — custom select, portalled list; SwitchTrack,
                      ModelIcon — provider logo of a model id via src/lib/modelIcons.ts,
                      ClientOnly — browser-only UI after hydration, RelativeDate — "5 days ago",
                      the UTC date until hydrated)
  src/components/layout/AppShell.tsx  sidebar + mobile top bar/bottom tabs, Page, PageTitle
  src/components/Seo.tsx  a page's head: title, description, robots, canonical, Open Graph,
                      twitter:card (React 19 hoists them into `<head>`), JSON-LD scripts
  src/components/cards/    DebateCard (library / gallery / landing; title under the cover, CardStats =
                           likes / views / length), DebateCover (face-off cover: each debater's logo
                           on a half in its speaker colour, slanted seams, VS; markup, never the winner),
                           CardCover (a card's 16:9 cover: the AI cover when there is one, else DebateCover;
                           `priority` for a page's first card), VideoPoster (the long video's first
                           frame in markup: brand, format chip, face-off, question; the landing's
                           hero and the player's poster)
  src/components/create/   three-step wizard + wizardState.ts (state, persistence, config mapping;
                           `applyFormat` / `fitFormat`: seats, prompts, rounds follow the format):
                           StepTopic (format cards on top, a locked one says why; TrendingBrowser =
                           today's news topics of the format's list in rank order, categories,
                           10 per page; its search field is also the "write your own" field:
                           typing turns "Surprise me" into the AI button (Enter too) = three
                           topics in the format's style (IdeasPanel) or "use my words as they
                           are"; + sticky "Your debate" panel; TopicVersions =
                           remix chip, "joins a published topic", similar topics), StepSpeakers
                           (SpeakerRow per speaker: model / side / voice / persona fields + voice
                           preview when the voice has a sample, prompt editor, remove; no randomizer;
                           rap battle: fixed FOR / AGAINST seats, a flow in place of a voice, the
                           "one track" card in place of the voice engine),
                           StepLaunch (style, outputs, scenes, keys + summary, estimate, start);
                           ModelPicker (searchable OpenRouter list: logos, prices, rank, Latest
                           filter), VoicePicker (voice list with previews, debate-language / all scope),
                           PresetPicker (short preset list: PersonaPicker = persona presets + Custom,
                           rappers' flows), PickerFace, usePickerPopover
  src/components/debate/   DebatePlayer (Remotion Player with own controls; browser-only, lazy;
                           `usePlaying` = play state as an external store, `deferred` = play asked
                           before the chunk; `embed` = EmbedShell: fills the iframe, controls and
                           header float and hide while it plays; `startMs` = the embed's `t=`),
                           PlayerShell (frame, SegmentBar = seek bar by turns,
                           PlayerPoster = the AI cover or VideoPoster until the first play,
                           PosterFace = it with the play button, PlayerPending = the ready player's
                           layout in the server's HTML and while its chunk loads, PlayerPlaceholder
                           = no audio yet / voicing), LiveCard (lazy; live frame: cast, speaker,
                           streamed captions), DebateActions (16:9 / 9:16 format icons + Like/Share/Remix/Export/… toolbar,
                           SharePopover = link + embed code (EmbedPanel: 16:9 / Short, start at the
                           player's moment, live preview) + gallery switch + moderation), ExportRail
                           (slide-over: ExportCard browser MP4 render, MP3, CoverCard = the owner's AI
                           cover and versions, PublishKit = YouTube
                           title/description with chapters/tags + canvas thumbnails, youtubeKit.ts),
                           Transcript (row click = seek, ● NOW; Markdown via lib/markdown),
                           VerdictTab (lazy; VerdictGate = the blind-vote cover), DetailsTab (lineup,
                           facts), AudienceVote (blind vote), RegenerateAudioDialog (lazy), TurnScenes
                           (scene board under each turn: SceneStill = lazy Remotion stills + replay
                           modal, fact-check/dispute badges), VersionsStrip (the topic's other public
                           versions, no winners); helpers.ts: speakerLineup, videoChapters,
                           timelineSrt, transcript/Markdown exports
  src/components/account/  Account page tabs (tabs.ts: `?tab=overview|keys|billing|security`,
                           accountPath): ProfileHeader, BalanceCard, UsageCards (bar per day),
                           Ledger (recent activity + full ledger), ProviderKeys (browser keys),
                           API tokens (ApiTokensCard, TokenOptionsFields, CopyBlock), SecurityCard;
                           auth layout/fields
  src/video/          Remotion compositions (DebateLong 16:9, DebateShort 9:16, ScenePoster =
                      one scene for the transcript board) + render.ts; browser-only except
                      constants.ts and timing.ts (frame / segment arithmetic, no Remotion);
                      visuals/ = scene renderer (SceneStage, 22 scene views, rough.js strokes,
                      drawn Lucide pictograms in icons.ts, lazy world map in geo.ts,
                      PictureScenes: sketch strokes + Ken Burns pictures)
  src/pages/          page components (routes in src/routes wrap them; Landing, Gallery,
                      Leaderboard, Topic render from route data, DebateView starts from it):
                      Landing (/), Library (/library), Gallery (/gallery), Leaderboard (/leaderboard),
                      CreateDebate (/create, `?draft=<id>`, `?remix=<id>`),
                      DebateView (/debate/:id and public /d/:slug), Topic (/t/:slug: a topic's
                      public versions), Embed (/embed/:slug: the facade, then DebatePlayer
                      `embed`), Account (/account?tab=…),
                      Device (/device?code=…, approves `debatr login`), Login (/login),
                      Register (/register); admin/ = the admin console (/admin/*, AdminApp mounted
                      by src/admin-main.tsx, outside the site's AppShell and AuthProvider: AdminLogin, AdminOverview, AdminUsers
                      (filters in the URL), AdminUser (/admin/users/:id), AdminDebates,
                      AdminDebate (/admin/debates/:id), AdminModeration (keyboard queue),
                      AdminTrending, AdminFinance, AdminModels, AdminSystem (#runs #queues
                      #limits #providers #health), AdminSettings (levers + alerts), AdminAudit
                      (`?tab=security`, filters in the URL, diff per entry),
                      AdminSecurity (sessions, recovery codes, passkeys); components/admin:
                      AdminShell, SudoDialog (code or passkey), ActionDialog (reason + sudo
                      retry, ⌘↵), DataTable + Pager, FilterBar + FilterChip + filters.ts (URL
                      filters), RecoveryCodes, PasskeysCard, AlertsCard, StatTile, AttentionList;
                      users/ =
                      the account card's actions and sections; debates/ = the debate card's
                      actions, video (VideoPanel), transcript and panels; system/ = the System
                      page's sections
                      (useLoad.ts: load + poll); components/admin/charts:
                      LineChart, StackedColumns, ChartCard (legend + table view), palette.ts =
                      validated chart colours)
  src/lib/cli.ts      install / login / MCP setup snippets shown on the Account page
  src/lib/gallery.ts  the gallery's URL filters (sort, period, format, category, model, voices, page) and
                      its API path (24 cards a page) / page address (`galleryHref`)
  src/lib/seo.ts      search and preview metadata of every page (pure, vitest): title / description
                      templates, canonical redirects, robots rules, JSON-LD (see "Search engines")
  src/lib/embed.ts    the player for other sites (pure, vitest; mirrors backend services/embed):
                      `?format=short&t=` parsing, `/embed/…` paths, the iframe code, `EmbedDebate`
                      (the route's small data), the oEmbed address
  src/lib/markdown.ts the models' Markdown as HTML (micromark + GFM, raw HTML escaped, dangerous
                      link targets dropped; same output on the server and in the browser)
  src/lib/og.ts       link preview cards (pure, vitest): the card data of a debate / topic / the site,
                      its version (`?v=`), alt text and image URL (`OG_DESIGN`: bump on a redesign)
  src/lib/formats.ts  show formats as the wizard runs them (mirrors backend services/formats:
                      seats, limits, premium-only, music, length / rounds wording, default
                      prompts) and the rappers' flows (mirrors media/music.FLOWS)
cli/                `debatr` package (PyPI): CLI + MCP server, Python 3.10+, uv, only the public API
  src/debatr/cli.py   Typer commands (login, run, watch, resume, show, list, stop, delete, publish, audio,
                      models, formats, gallery, leaderboard, whoami, logout, mcp); `run --format
                      rap_battle --flow …` (flow ids checked against `GET /api/formats`)
  src/debatr/api.py   async httpx client (ApiError messages, SSE parser), shared with the MCP server
  src/debatr/mcp_server.py  MCPServer (mcp>=2.3) tools: start/get/estimate/stop/resume debates
                      (`format`, `flows`), models, formats, gallery, leaderboard (per format),
                      account; DEBATR_MAX_COST_USD cap
  src/debatr/debate.py  build_config (mirrors DebateConfig), debate refs, digest (--json / agents)
  src/debatr/config.py  server URL + token resolution, saved logins (0600 config.json)
  src/debatr/markers.py, styling.py, render.py  live terminal output (markers hidden, inline Markdown)
  tests/              pytest on a fake server (httpx.MockTransport) and the SDK's in-process client
scripts/backup-db.sh  `make backup` / `make backup-check`: Postgres dumps (pg_dump -Fc, 0600,
                    pruned after BACKUP_KEEP_DAYS, optional rclone upload) and a restore check
                    into a scratch database; the last good backup is noted in Redis `backup:last`
scripts/screenshots/  `make screenshots`: README images (numbered phone screens, a 16:9 frame, the
                    hero = three phones, also the social preview: JPEG under 1 MB) shot from the
                    local stack with playwright-core and the installed Chrome; views / likes /
                    votes / model ratings are invented per id in the browser (SHOWCASE=off: real).
                    Account/debate in its git-ignored .env; output in out/ (git-ignored: the
                    images are dragged into a GitHub comment box and README links the
                    user-attachments URLs, never committed; PNG screens since that takes no WebP)
design/             local Claude Design export (`Debatr Studio.html`), git-ignored
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
uv run python -m app.scheduler                      # periodic jobs (optional natively, see "Trending topics")
uv run python -m app.scheduler --refresh-trending   # build a trending-topics batch now (`make trending`)
uv run alembic upgrade head               # apply migrations
uv run alembic revision --autogenerate -m "describe change"
uv run ruff check . && uv run ruff format .   # lint + format
uv run pyright                            # type check
uv run pytest -q                          # tests
```

Frontend (run from `frontend/`):

```bash
npm install
npm run dev        # react-router dev on :5173: SSR + HMR, the console on /admin, /api -> http://localhost:8000 (incl. SSE)
                   # VITE_DEV_API_TARGET=http://localhost: the Docker stack instead (proxy and SSR loaders)
npm run check      # react-router typegen + tsc + eslint + vitest
npm test           # vitest (pure modules, src/**/*.test.ts)
npm run build      # site → build/client + build/server, console → build/admin
npm start          # the built server (react-router-serve, :3000; API_INTERNAL_URL)
```

CLI (run from `cli/`; `make cli a="…"` runs it against the local stack):

```bash
uv sync
uv run debatr --url http://localhost login     # device flow: approve in the browser
uv run debatr --url http://localhost run "Tabs or spaces?" --rounds 1 --length very_short
uv run debatr --url http://localhost mcp       # MCP server on stdio
uv run ruff check . && uv run pyright && uv run pytest -q
```

Infrastructure:

```bash
docker compose -f docker-compose.dev.yml up -d   # Postgres :5432 + Redis :6379 for native dev
docker compose up -d --build                     # full stack on http://localhost (migrations auto-run)
./deploy.sh                                      # production (adds docker-compose.prod.yml)
make backup                                      # dump Postgres into ./backups (cron on the server)
make backup-check                                # restore the newest dump into a scratch DB, compare counts
docker compose exec api python -m app.manage admin grant you@example.com   # console access + enrollment code
docker compose exec api python -m app.manage credits user@example.com 5 --reason "…"  # ledger adjustment
```

## Architecture and data flow

0. Accounts: `POST /api/auth/register|login` set `request.session["uid"]` and `["epoch"]` in the
   signed session cookie (`SameSite=Strict`, `__Host-session` in production so sibling
   subdomains can neither read nor plant it, `session` over plain-http dev:
   `core/auth.session_cookie_options`). Document requests forward it to the API (`_site`
   middleware → `Viewer`), so pages render signed in; a link from another site arrives without
   it (Strict), so such a page renders anonymously with `Viewer.known=false` and the browser asks
   `/auth/me` itself (DebateView then reloads its personal copy). `_private` redirects to
   `/login` on the server only when the session is known to be missing. `get_current_user` drops a
   cookie whose epoch is not `users.session_epoch`: a password change (this browser is signed in
   again), "sign out everywhere", a temporary password or disabling in the console end every
   other cookie at once.
   `get_current_user` / `require_user` in `app/core/auth.py`. New accounts get
   `SIGNUP_BONUS_USD` credits. Admins sign in to the admin console separately (see "Admin
   console"); the public API grants them nothing.
1. `POST /api/debates` (signed-in users only) validates `DebateConfig` (`topic` ≤
   `TOPIC_MAX_LENGTH` = 150: it is drawn on the video; configs saved before the limit hold up to
   500 and are re-read with `DebateConfig.stored`; the wizard, CLI and trending topics keep to
   it), estimates the run
   (`services/estimate.py`) and rejects with 402 when credits are insufficient (on the system
   key every model needs a catalogue price, `estimate.unpriced_models`: unlisted ids such as
   `:nitro` variants or dropped models → 400, no catalogue → only free models; routers with a
   variable price, e.g. `openrouter/auto`, are left out of the catalogue), stores the debate
   (`status=queued`, or `draft` when `draft=true`) with `user_id` and `config_json.billing.own_key`,
   puts the OpenRouter key to use in Redis (`debate:{id}:provider_key`, TTL) — the request key or
   the account's encrypted key, never in Postgres — and enqueues `start_debate_job`.
   `POST /api/debates/{id}/start` queues a draft; `PATCH` replaces a draft's config.
   Reply lengths: the site calls `very_short` / `short` / `medium` Short / Medium / Long (~50 /
   ~100 / ~250 words; battles 4 / 8 / 12 lines); `long` (~500 words) was retired: a new config
   that sends it runs as `medium` (`DebateConfig._retired_length`), saved ones keep it.
2. The worker chains RQ jobs: `start_debate_job` → `process_turn_job(seq_index)` per turn →
   `conduct_verdict_job` → `finish_debate_job`. Each job opens its own blocking DB session
   (`NullPool`, safe across RQ forks). With visual scenes on, every saved turn first goes
   through `studio.design_turn` (scenes, sketches, fact-checks; see "Visual scenes") before the
   next turn is queued.
3. The debate's format (`services/formats`, `DebateConfig.format`, `format_of(conf)`: none or
   unknown → `debate`) is the single source of truth for turn order (`Format.schedule`), the
   prompts (`host_messages` / `debater_messages` / `verdict_messages`), the verdict's word budget
   (`verdict_words`, also used by the estimate; `voiced_verdict_words` / `spoken_text`: what of
   it is voiced, a battle's score card is not), the round labels (`round_label` → `TurnOut`,
   `turn_started`, timeline segments) and its limits (`problems`, checked by `DebateConfig`).
   The orchestrator, the estimate, the recovery and the console never branch on a format id.
   `debate` (the only format so far) wraps `scheduler.build_schedule()` and `prompt_builder`:
   each round = moderator (intro / transition) + every debater; debater turn types are
   `opening` / `rebuttal` / `closing` (or `argument` for single-round debates). The verdict
   (`turn_type=verdict`, `round_id=verdict`) is appended after the last scheduled turn; its word
   budget follows the length preset. A config without sides gets byte for byte the prompts of
   before formats (`tests/fixtures/debate_prompts_v1.json`). Sides (`ParticipantConfig.side`:
   `for | against | own`, unset = the persona carries the stance) add a "Your side" line, mark the
   participants list and the judge's prompt; the wizard always sets them (old personas' default
   stance sentences are turned into sides: `sideFromPersona`). Formats with fixed seats
   (`Seat(label, side)` by speaking position) refuse sides from the user. The leaderboard ranks
   within a format (`format=debate` by default); the gallery has a `format` filter.
   `rap_battle` (`formats/rap_battle.py`): an MC (required) opens, exactly two rappers trade verses
   for 1–3 rounds (the second opens round 2), Rapper One for the topic and Rapper Two against
   (for "A or B?" topics: A / B); a verse is exactly N lines (very_short 4, short 8, medium 12,
   long 16 in old configs; `finish_text` tidies the answer into lines). The MC is a ring announcer
   (≤ 40 words, names in CAPITALS after "...", `[shouts]`-style cues; never scores). The judge
   writes a score card first ("Round N: A 8, B 7 - why" per round, "Total: A 15, B 14", in English
   whatever the language: `verdict_json.rounds` from the structuring call or
   `fallback_round_scores`), then a shouted announcement that is the only voiced part
   (`spoken_text`): the totals and "and the winner is... NAME!", plus the deciding moment
   (Medium) or a line per round (Long); no scenes, the
   output style is always spoken, the gallery check allows trash talk (`moderation_note`). Audio
   is optional but premium only (`voices="elevenlabs"`: Edge → 400, no Edge fallback in
   `_auto_media`) and comes from one generated track (`soundtrack="music"`, see the media
   pipeline). `GET /api/formats` lists the formats with their flows (`FormatOut.flows`,
   `default_flows`) for the CLI and agents. The wizard: format cards in step 1 (a switch keeps
   models and styles, trims seats, swaps default prompts and clamps rounds); a battle always
   builds its audio on ElevenLabs, sends `media_plan.flows` and voices only for the MC and the
   judge, no sides, no scenes; it is locked without a balance unless the browser's ElevenLabs
   key is on a paid plan (`GET /media/voices` answers `paid_plan` for an own key; a free-plan key
   is left out of a battle, which then runs on our key and credits). The regenerate dialog
   offers flows for the rappers and says whether the track is reused (same verses and flows) or
   made again (paid). `VerdictOut.rounds` (`verdict.stored_round_scores`) carries the judge's
   scores to the verdict tab (a score sheet), the CLI and agents; `Timeline.format` labels the
   video ("RAP BATTLE", `lib/formats.timelineFormat`: older battle timelines are told by their
   verses). Gallery cards of battles carry a RAP BATTLE badge (`CoverBadge`), the gallery has a
   format filter (`?format=rap_battle`), the ranking a Rappers tab (`/leaderboard?format=…`,
   `useLeaderboard` caches per format) and `/create?format=rap_battle` opens the wizard on it.
4. `openrouter_client.stream_chat_completion()` streams deltas and returns usage
   (tokens + cost). On HTTP 400 with a system prompt it retries once with the system prompt
   merged into the user message. Mid-stream `{"error": ...}` chunks raise `OpenRouterError`.
   `LLM_TURN_TIMEOUT` (300 s, wall clock) caps one answer: keep-alive comments and reasoning
   chunks reset the read timeout, so without it a stuck provider held the turn until
   `TURN_JOB_TIMEOUT` killed the job and the debate; now the turn is saved as failed and the
   debate goes on.
   `StreamChunk.model` is the model that answered. `openrouter/free` picks a random free model
   per request, so `services/free_router` pins the `:free` model of a participant's first real
   answer (≥ 20 words, no guard/safety classifier — the router picks those too; a classifier
   pick is dropped at the stream's first chunk before any text is published, and a too-short
   router answer is asked again, `ROUTER_TRIES`; a try after streamed text re-sends
   `turn_started` so viewers restart the turn) in
   `DebateParticipant.model_id` (lineup, gallery filter, leaderboard, video
   via `resolved_participants`); `config_json` keeps the router, so remixes/drafts ask it again
   (`ParticipantOut.router`). A pinned model that fails before writing anything falls back to the
   router for that turn (free models often 429 upstream). When the router picks a classifier on
   every try of a turn, a `:free` model that argued well in the last week answers instead and is
   pinned (`free_router.fallback_models`, from `provider_usage`). `Turn.model_used` = the model that
   answered for router turns, the configured id otherwise. Names stay "Free Router A/B" (the
   host introduces them before any debater speaks).
5. The worker publishes events to Redis channel `debate:{id}`; `GET /api/debates/{id}/stream`
   relays them as SSE and closes on a terminal event (or immediately if the debate is already
   finished). After the verdict turn `services/verdict.py` structures it with the cheap
   `VERDICT_MODEL` (old name `MEDIA_HIGHLIGHTS_MODEL` still read; a fixed model, since the
   author picks the host; regex fallback) into `debates.verdict_json` (`winner_id`, `headline`,
   `feedback`). When every participant argues on a free model it is the lever
   `free_verdict_model` instead (`:free` only, env `FREE_VERDICT_MODEL`,
   `orchestrator._verdict_model`; on the system key it takes a free-quota slot, none in 60 s →
   regex verdict and the check fails closed), so a free debate costs us nothing but its visual
   scenes. At the terminal state `services/credits.py` charges the owner (`cost × markup`, at
   least the minimum once completed, at the prices the run started with — `billing.prices`, see
   "Credits and payments"; skipped with an own key; minus what earlier runs of the debate were
   charged, so repeats and resumed runs are safe: `charge_due`, refs `…:llm`, `…:llm:2`;
   `totals_json.cost` = turns + fact-checks (`analysis_cost`) + discarded turns, while the verdict
   structuring and the gallery check go to `service_cost`, which nobody is billed for) and
   `_auto_media` queues the audio build when `config_json.media_plan.outputs` contains `audio`.

SSE events: `connected`, `debate_started`, `turn_started`, `turn_delta`, `turn_completed`,
`turn_error`, `turn_visuals`, `verdict_ready`, `media_progress`, `cover_progress`,
`debate_completed`, `debate_error`, `debate_stopped`. `turn_completed` / `turn_error` carry the full serialized turn
(`TurnOut`); `turn_visuals` carries `{seq_index, visuals: TurnVisualsOut}` (designing →
checking → ready).

Debate statuses: `draft | queued | running | completed | error | stopped`.
Access: owners manage a debate; public (`is_public`, `slug`, `/d/{slug}`,
`GET /api/gallery/{slug}`) and ownerless legacy rows are readable by anyone
(`app/api/serializers.can_view / can_manage`; admins work in the console, never through this
API). `POST /api/debates/{id}/publish` assigns the slug.

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
- Flagged debates stay private: the owner's Publish only sets `publish_requested`; the console's
  Moderation page approves (publishes when the owner asked) or rejects them, each audited.
  Rejected debates cannot be published by the owner.
  `moderation` in `DebateDetail` goes to the owner only; configs from before auto-publish count
  as `false`.
Stopping: `POST /api/debates/{id}/stop` sets the status, sets `debate:{id}:stop` in Redis
(checked by the worker every few chunks) and publishes `debate_stopped`.
Failed turns: a turn (or verdict) without an answer — provider error, `LLM_TURN_TIMEOUT`, empty
reply — stops the debate (`status=error`, `error_message` names speaker and model) instead of
letting the others argue against silence. `POST /api/debates/{id}/resume` (owner, same body as
`/start`; Resume button in the error banner, `debatr resume`, MCP `resume_debate`;
`POST …/resume/estimate` prices it without starting) drops the failed turn and anything after it
(`services/resume`: `resume_point`, their cost kept as `totals_json.discarded_cost`), keeps the
earlier turns and pinned models, re-checks credits for the rest only
(`estimate_debate(from_turn=…)`) and queues `start_debate_job(from_seq=…)`. A run that used an own
OpenRouter key cannot resume on the system key (409); media goes back to `none`.

### Topics: debates as versions of one topic (`services/motions`)

- `motions` (`slug` random, `key` = `normalize_topic` text — NFKC, casefold, everything but letters
  and digits → spaces — unique, nullable; `merged_into_id`) and `debates.motion_id`,
  `debates.remix_of_id`. Migration 0014 grouped the debates before it (with a frozen copy of the
  rule; `test_motions` fails if the two drift apart: changed keys need a re-keying migration).
- `assign_motion` runs at create and at draft edit (`routes_debates`): a remix parent the user may
  see (`DebateConfig.remix_of`, request-only like `draft`, ignored otherwise) gives its topic when
  the text is the same after normalizing or the language differs (a translation); else the topic
  of the key (merged ones lead on, one hop: merges are flattened); else a new topic. Nothing groups
  by meaning: trending topics and the wizard's "Use" put the text in word for word.
- A topic stores no counters: versions, the cover and the title (first public version by
  publication) come from the public debates (`public_clause` = `is_public` + slug, the gallery's
  condition), so publish / unpublish / moderation / delete paths never update topics.
  `GET /api/gallery?group=motion` (the site; default `none` for the CLI): `covers_query` ranks
  versions per `coalesce(motion_id, id)` with the sort's own keys, the cover is the best matching
  one (trending: most trending, new: newest, top: most liked) and topics order by it; trending
  multiplies by `ranking.topic_trending_score` (`1 + 0.2·ln(versions)`). `GalleryItem.motion` =
  `MotionRef` (slug, title, public versions, models) for the "N versions" badge.
- `DebateDetail.motion` (up to 12 public versions, the viewed one always in, `current`; null
  without a public version) and `remix_of` (public parents only) via `serializers.topic_context`;
  no verdicts on versions (blind voting). `GET /api/motions/{slug}` (the topic page, a merged slug
  answers with its target) and `GET /api/motions/suggest?topic=&language=&remix_of=` (`match` =
  the topic this text would join, `similar` = pg_trgm `%` + `similarity ≥ 0.35`) show only topics
  with public versions: a topic of private debates exists for nobody else.
- The wizard keeps `remix` (`{id, topic}`, set by `?remix=`, × unlinks) and sends `remix_of`;
  `DebateSettingsOut.news` lets a remix of someone else's trending debate keep its story.
- Console: the debate card's "Topic" fact and `POST /api/admin/debates/{id}/motion`
  (`moderation`, reason, audit `debate.motion_changed`): move into the topic of a link / id /
  slug (`parse_target`), split off (no target: a keyless topic; the text keeps joining the old
  one) or merge the whole topic (`whole`).

### Search engines and link previews (`services/seo`, `lib/seo.ts`)

- Canonical addresses carry the topic's words: `/d/{slug}/{kebab}`, `/t/{slug}/{kebab}`
  (`seo.kebab`: letters, marks and digits of any script, lowercase, ≤ 60 characters cut between
  words; Unicode paths, percent-encoded only in sitemaps, IndexNow and `Location`). The API sends
  them as `path` (`DebateDetail` — null while private —, `GalleryItem`, `MotionRef`, `MotionOut`,
  `MotionVersion`, `MotionPage`, `RemixParentOut`, `PublishOut`); `share_url` = SITE_URL + path.
  The `d/:slug/:kebab?` and `t/:slug/:kebab?` loaders answer every other spelling (no kebab, an
  old topic text, a merged topic) with a 301 to it (`canonicalRedirect`, query kept), also in
  the client loaders. `GET /api/gallery/{slug}` answers 410 for a slug that is no longer public
  (slugs outlive unpublishing), 404 for none; the page keeps the status.
- `<Seo>` per page (`lib/seo.ts`): debate "{topic} — A vs B" (battle "… — A vs B rap battle"; the
  topic is shortened first, the lineup dropped when too little topic would be left), the first
  debater's opening (whole sentences when possible) + "Watch A vs B and vote who won.", an
  `Article` + `BreadcrumbList` (Gallery › topic › debate); topic "{topic}: N AI debates" with a
  `CollectionPage`; home `WebSite` + `Organization`; gallery / ranking texts in
  `brand.SEO_COPY`. Titles ≤ 60, descriptions ≤ 160. No preview, description or JSON-LD names a
  winner (blind voting).
- Link preview pictures (`og:image`, `twitter:image`, JSON-LD `image` / `primaryImageOfPage`,
  sitemap `<image:image>`): 1200×630 cards drawn by the `web` server with Takumi (`takumi-js`,
  Rust, no browser, ~20–40 ms) from `lib/og.ts` card data: the long video's first frame —
  the debaters face off on slanted sides in their speaker colours (logos, VS, names), the brand,
  the format chip ("AI DEBATE", "RAP BATTLE"; a topic: "N VERSIONS" over the models of its
  versions) and the question; never the winner. `/og/d/{slug}.png`, `/og/t/{slug}.png` (from the
  API's public copy, fetched without the cookie: not public → 404 / 410, API down → the site's
  card for a minute), `/og/site.png` (home, gallery, ranking). A debate with an AI cover (a topic:
  its first version with one) serves the cover's `og_url` file instead (fetched from the API,
  kept in memory; gone → the drawn card for 5 minutes). Pages add `?v=` = `ogVersion`
  (hash of the card + `OG_DESIGN`): a matching `v` is cached for good (`immutable`), none or an
  old one for an hour (sitemaps name the address without it: `seo.debate_image_path`). Cards are
  kept by `cardKey` (same data = one file) in memory (64) and in `OG_CACHE_DIR` (volume
  `og_cache`, pruned past `OG_CACHE_MAX_MB`); PNG, or JPEG q90 past 300 KB (gradients make PNGs
  heavy; WhatsApp wants ≤ 300 KB). Fonts: Takumi reads no system fonts — the site's families and
  Noto (Cyrillic, Greek, Devanagari, Armenian, Arabic, Hebrew) from node_modules, Twemoji's COLR
  font for emoji; Chinese / Japanese / Korean / Thai / other Indic scripts are fetched from
  Google Fonts per headline (only the subsets it uses, `scriptFamilies`; kept in the cache's
  `fonts/`); a failed fetch draws the card with gaps and keeps it 5 minutes only.
- Robots: public pages `index, follow, max-image-preview:large…`; gallery views other than the
  plain list, its rap-battle view and their `?page=N` (sort, category, model, premium voices) are
  `noindex, follow` with the plain list as canonical; topics with one public version are
  `noindex` (a thin copy of that debate) and stay out of the sitemap
  (`TOPIC_INDEX_MIN_VERSIONS`, mirrored); `_client` pages `noindex, nofollow` (meta +
  `X-Robots-Tag`); errors `noindex`.
- The debate page's HTML is complete for crawlers: the topic in `<h1>` (visually hidden under
  the player's poster), the page an `<article>`, rounds in `<h2>`, every turn, the Details tab
  (lineup, models, facts) rendered `hidden` when folded, and the judge's ruling in the DOM
  under the "Reveal" gate (`hidden`, like a folded accordion) while the viewer's vote is blind.
- `app/api/routes_seo.py` (outside /api, Caddy routes them): `robots.txt` (production: all but
  the private prefixes, AI crawlers refused only with `SEO_ALLOW_AI_CRAWLERS=false`, `Sitemap:`
  line; elsewhere `Disallow: /`), `sitemap.xml` (index) → `sitemaps/pages.xml` (home, gallery,
  ranking and their battle views), `sitemaps/topics.xml`, `sitemaps/debates-{n}.xml` (10 000 per
  file, `lastmod` = latest of published / ended; topics and debates name their preview picture);
  only `public_clause`; `max-age=3600`.
- IndexNow (`services/indexnow`, production with an https SITE_URL and `INDEXNOW_KEY`, key file
  `/{key}.txt`): publish / unpublish / delete (owner or console), approve / reject, topic moves,
  disabling an account with "unpublish" and deleting one note the debate's URL and `motion:{id}`
  in the Redis set `indexnow:pending` (`announce` / `announce_sync`, never failing the caller);
  the scheduler's `flush_job` (every 60 s, background queue, only registered when on) resolves
  topics to their address now and POSTs up to 10 000 URLs to api.indexnow.org; 429 / 5xx /
  network errors put them back. Not booked in `provider_usage` (free).

### Embedding on other sites (`/embed`, oEmbed; `lib/embed.ts`, `services/embed`)

- `/embed/{slug}` (`?format=short` = the Short's first highlight, `?t=` = start in seconds,
  `parseEmbedQuery`): outside `_site` — no AppShell, no session (the API is asked without the
  cookie: a third-party frame never gets the SameSite=Strict one), `sharedMicrocache`, no
  `X-Frame-Options` and no `frame-ancestors` (`*` would still refuse `srcdoc` / `about:` parents —
  WordPress previews oEmbed players in one — and `app://` / `file://`), `X-Robots-Tag: noindex`, `Cache-Control: public, max-age=300` (60 s for
  errors). The loader keeps only `EmbedDebate` (no transcript in the HTML). `handle.framed`
  drops `<ScrollRestoration>` (WebKit leaves `history.state` empty in third-party frames).
- The server's HTML is the facade (`pages/Embed.tsx`): the AI cover with the question on top (or
  `VideoPoster` / the 9:16 `ShortPoster`), Play, the episode's length, "Watch on Debatr"
  (`?ref=embed`, new tab). Intent (pointer enter, focus) loads the Remotion chunk and the media
  (`GET /media` + timeline) and mounts `DebatePlayer embed` under the poster, so the click itself
  plays (Apple's WebKit; a click before that plays on the next one). Nothing loads in idle time:
  the frame comes with every visit of the other page. A view counts on the first play (beacon).
  Not voiced → "Read it on Debatr" card; not public / unknown → a card with the API's status.
- Share popover → "Embed on a website" (`EmbedPanel`, public debates with ready audio): 16:9 or
  the Short, "Start at" the page player's moment (same format; the Short only on its first
  highlight), a live preview iframe, `embedCode` (responsive: `width:100%;aspect-ratio`, a Short
  ≤ 360 px; `allow="autoplay; picture-in-picture"` + `allowfullscreen` — `fullscreen` in `allow`
  makes Chrome warn on the other page).
- oEmbed `GET /api/oembed?url=&maxwidth=&maxheight=&format=json` (`routes_oembed`, CORS `*`,
  `max-age=3600`): links of SITE_URL's host (port and `www.` ignored) to `/d/…`, `/t/…` (the most
  liked public version with audio, else the most liked) or `/embed/…` (its format and start kept);
  `type: video` with ready audio, else `rich`; size in the video's proportions within the limits
  (640×360 / 360×640 by default, up to 1280 / 405 wide); thumbnail = the preview picture
  (`/og/d/{slug}.png`, 1200×630); private / unknown → 404, `format=xml` → 501. `debateSeo` /
  `topicSeo` set `oembed`, so `<Seo>` adds `<link rel="alternate" type="application/json+oembed">`.
- JS before hydration: ~149 KiB gzip, of which React DOM + React Router are ~110 and the root's
  shared chunks ~22; the player's own code ~17 KiB.

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
- `GET /api/gallery?sort=new|trending|top&period=week|month|year|all&model=<id>&premium_voices=true`;
  trending is `services/ranking.trending_score` mirrored in SQL by `routes_gallery.trending_sql`.
  Anyone may publish (free models and Edge voices too); quality is a ranking signal, not a gate:
  ready ElevenLabs audio (`serializers.has_premium_voices` / `premium_voices_sql`) counts like two
  likes (`PREMIUM_VOICES_BONUS`), cards mark it (`GalleryItem.premium_voices`), the gallery has a
  "Premium voices" filter (`?voices=premium`) and the landing's trending row puts such debates first.
- `GET /api/gallery/leaderboard`: Bradley–Terry ratings (Elo-like scale, 1000 = average,
  `PRIOR_GAMES` virtual games damp single votes) from audience votes on public completed debates;
  each vote is a win of the chosen model over every other model in the debate, mirror matches are
  ignored. Lists only models that argued in a public debate; `is_free` comes from the OpenRouter
  catalogue. `rated=false` until a model met another one in a debate with votes (its 1000 is just
  the prior): such models come last without a place or rating (page, wizard ranks, CLI, MCP).
  The judge never feeds the rating. Unpinned `openrouter/free` participants (debates from before
  pinning) are left out. The wizard's model fields and model list show each rated model's rank.

### Media pipeline (audio on the server, video in the browser)

6. `POST /api/debates/{id}/media` (finished debates only) stores the chosen TTS options in
   `debates.media_json`, sets `media_status=queued` and enqueues `build_media_job` on the
   `media` RQ queue (`MEDIA_JOB_TIMEOUT`). An optional user ElevenLabs key goes to Redis
   (`debate:{id}:tts_key`), never to Postgres. ElevenLabs builds on the system key are paid
   from the owner's credits (`X-Media-Token` = MEDIA_API_TOKEN is exempt). The system key is
   probed (`tts/elevenlabs.system_key_status`, cached) so a rejected key disables premium
   voices in the UI instead of failing later; the key needs the Text to Speech, Voices read,
   User read and Forced alignment permissions.
7. The job cleans each turn's Markdown (`media/script.py`), synthesizes it with the provider
   (`elevenlabs` with word timestamps / forced-alignment fallback, or the free `edge` voices),
   normalizes loudness with ffmpeg, caches per-turn WAV+JSON by content hash under
   `MEDIA_ROOT/{debate_id}/turns/`, mixes `full.wav`/`full.mp3`, designs the visual scenes
   (below, when `MediaOptions.visuals`), asks the host's model (pinned for a Free Router; system
   key, not billed; a free one takes a free-quota slot, a turned-off one gives the deterministic
   fallback) for short-video highlights, kept in `highlights.json` per transcript
   (`jobs.highlights_key`: a rebuild with new voices asks nothing), and writes
   `timeline.json` (`app/schemas/timeline.py`).
   Progress lives in `media_json` (polled by `GET /api/debates/{id}/media`); `media_status`
   is `none | queued | running | ready | error`.
8. Files are served by `MediaStaticFiles` at `/api/media/files/{debate_id}/...` (Range
   requests work). The debate page plays the video in the Remotion Player with its own controls
   (`DebatePlayer`; transcript rows jump to their turn, `helpers.videoChapters` maps turns to the
   long video / Short clock). The player is a facade: the server's HTML has its layout with the
   poster (the AI cover, else `VideoPoster`) and a play button, the page's largest paint; the
   Remotion chunk (~290 KB gzip) loads on hover / focus, in idle time after the page's load (not
   on Save-Data / 2G) or on the first click, mounts under the poster, and the poster goes on the
   first play. A click on the poster or a transcript row before the chunk is there spins and
   plays once it is (`deferred`; Apple's WebKit waits for the next click, audio needs the
   gesture) and renders MP4s **in the visitor's browser** (`ExportRail` →
   `components/debate/ExportCard.tsx` +
   `@remotion/web-renderer`) — the server never encodes video; finished renders are reported to
   `POST /api/debates/{id}/renders` for the usage stats. Premium voices on the system ElevenLabs
   key cost `TTS_CREDIT_PRICE_PER_1K_CHARS` in credits (charged after the build); own keys are free.
   There are no plans, only the prepaid balance (like OpenRouter): with an empty balance and no
   own key premium voices are locked in the wizard and the regenerate dialog, and `POST /media`
   answers 402. Only an own key ElevenLabs accepts unlocks them: `useElevenLabsKeyStatus` checks
   it via `GET /media/voices` (502 = rejected) and a rejected key is neither used nor sent.
   `output_style=spoken` in `DebateConfig` asks the models for plain spoken prose with
   optional `[emotion]` tags, which ElevenLabs v3 / v4 understand. New builds default to
   `eleven_v4` (`TTS_DEFAULT_MODEL_ID`, wizard `ELEVENLABS_MODEL`: tags, `previous_text`,
   `language_code`); `voice_settings.stability` is 0.5 unless the format sets
   `voice_stability` (rap battle: 0 = the widest emotional range; part of the turn cache key).
   Formats with `announcer_voices` (rap battle) give the host and the judge Voice Library
   announcers by default (`tts/elevenlabs.ANNOUNCERS` per language, English for the rest; found
   by search until the first use copies them into the account; `GET /media/voices?format=`).

- Rap battles (`soundtrack="music"`, `jobs._build_battle`): the MC's intro and the verdict are
  voiced by ElevenLabs TTS (`_synthesize_turn`, cached per turn); then `media/music.build_plan`
  makes the composition plan (an instrumental intro as long as the MC's speech + a bar, a
  section per verse with its rapper's flow — `MediaPlan.flows`, `music.FLOWS`, by default a male
  and a female voice —, a two-bar break before every new round, an outro under the verdict;
  92 BPM, a bar per line; every verse also names its voice — `solo male vocals` — and the other
  one as a negative style, plus "a new … vocalist takes the mic" when the voice changes: the
  model otherwise carried round 2's opening voice into the next verse; `PLAN_VERSION` 2) and `music.compose` makes one `POST /v1/music/detailed` call
  (`music_v2_5`, `with_timestamps`, `mp3_44100_128`; a 429/5xx is tried once more, a refusal
  fails the build with ElevenLabs' message). The track is cached by the plan's hash
  (`MEDIA_ROOT/{id}/music/<hash>.mp3` + words), so a rebuild with the same lyrics generates and
  charges nothing. `ffmpeg.normalize_music` + `mix_over` duck the beat under the MC and the judge
  into a stereo full.wav; verse segments are the sections' windows (v2 keeps their durations)
  with the rapped words. `provider_usage` purpose `music` (cost estimated at $0.15 a minute);
  the owner pays `music_price_per_min` (lever, default $0.30) after the build (ledger category
  `music`, every console summary counts it); the estimate adds the track's minutes
  (`Format.track_ms`). An own ElevenLabs key needs a paid plan (`elevenlabs.music_allowed`,
  402). Never run music builds in tests or QA without the owner's go-ahead: each costs money.

### Visual scenes (charts, drawn schemes, sketches and pictures)

- `services/media/visuals.py` ("visual director", `MEDIA_VISUALS_MODEL`, default Gemini Flash,
  system key, not billed) designs a turn's scenes. `scene_budget` ≈ one scene per 18 s of speech
  (at least one per debater hint); the reply holds one spare scene and `diversify` drops repeats
  across turns. With `media_plan.visuals` on, `services/studio.design_turn` runs it **live**
  right after each turn is saved (the next turn waits): plan → keys (`scene_key`: turn + hash of
  the director's fields) → picks (`diversify` over the turns so far) → sketches and fact-checks
  in parallel → `turns.visuals_json` (format in the studio docstring) + SSE `turn_visuals`. The
  media build reuses a stored plan when `PROMPT_VERSION` and the spoken text hash match
  (`usable_plan`), designs the missing turns (in parallel; `force` re-plans all) and writes them
  back, so the transcript board shows what the video shows. A failure only loses scenes.
- Scenes are typed data only (`app/schemas/visuals.py`) — never code or markup. The director
  may design 21 types (`DirectorScene`: stat, bars, line, pie, proportion, ranking, map, bullets,
  versus, scale, matrix, venn, definition, flow, timeline, quote, rebuttal, headline, icons,
  sketch, image — image only when `images` is not `off`, one per turn); the
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
  Formats whose judge scores every round (`verdict_scores`, rap battle) get it even without
  scenes, with `rounds` (the score sheet: `ScoreSheetView`, rows revealed one by one, totals,
  crown) up from the verdict's first word to its end; the crown comes on the judge's last call
  of the result (`final_call_index` → `ScoreboardScene.decide_ms`).
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
- Rendering (`src/video/visuals/`): the frame follows the mockup's player (unit = 1% of the
  width): the brand (`BrandLockup`: the favicon mark + wordmark) top-left, the speaking chip
  (logo, name, model, level bars) top-centre, the round chip top-right, all three as tall as
  the chip (`constants.barHeight`); debater cards with the provider logo
  (`components/ModelLogo.tsx`; no mascots or avatars), captions on a dark plate (current word in
  the accent). `SceneStage` sits in the centre of both compositions (16:9: cards in side columns
  1+1 / 2+1 / 2+2; 9:16: debaters 1–2 as a row of `SpeakerRowCard`s, the stage, debaters 3–4,
  captions; the stage's box is centred in the frame, with two debaters it takes the second
  row's place) and shows the round +
  topic when no scene is up. Intro, hook and end cards carry the same brand lockup. The long
  intro and the Short's hook card are a face-off (`components/FaceOff.tsx`, the gallery cover's
  look: slanted sides in speaker colours, big logos, VS) fully drawn on frame 0, which is the
  player's poster (`initialFrame` 0, the play button sits below the VS) and the MP4's first
  frame; `preloadSceneAssets` also loads the fonts before an export. Logos come from
  `TimelineSpeaker.model_id` (older timelines: the short name, `modelIcons` BY_NAME).
  The web renderer serializes each `<svg>` into an image, so strokes animate via SVG attributes
  (`pathLength=1` + dashoffset), colours are attributes (no `currentColor`), text stays in HTML,
  and rough.js shapes use a fixed seed per scene (random seeds jitter between frames). It only
  takes raster `mask-image`s (all logo SVGs are painted to PNG data URLs in `video/logos.ts`,
  preloaded before an export: WebKit draws em-sized SVG images zoomed and cropped), only
  unsized, centred `radial-gradient`s (one per element: see `components/Background.tsx`) and
  ignores box-shadow spread (use `outline`). Icon keys in `icons.ts` mirror `ICONS` in
  `schemas/visuals.py`.
- Safari / WebKit export: WebKit's H.264 encoder holds frames in `latencyMode: 'quality'` (which
  the renderer hard-codes) and the export froze after frame 1; `video/render.ts` switches the
  encoder to `realtime` there (`navigator.vendor` is Apple's). Reproduce Safari issues with
  Playwright's WebKit (see the video QA memory / a temporary render harness page).
- `sketch`: the director names a concrete subject; `media/sketch.py` asks `MEDIA_SKETCH_MODEL`
  (Gemini 3.5 Flash Lite, ~4 s) for SVG line art and `sanitize_svg` keeps only path/line/circle/
  ellipse/rect/polyline/polygon/g (no text, links, styles, `<use>`; DOCTYPE/ENTITY rejected),
  converts shapes to path data and validates `d`/`transform` against strict regexes (again on
  every load). `SketchView` inks the strokes in order, timed by path length. A failed drawing
  drops the scene.
- `image` (`MediaOptions.images`: `off | stock | ai`, wizard "Pictures"): resolved only in the
  media build (`media/images.ImageStudio`, at most `MEDIA_MAX_IMAGES`). `stock` searches
  Wikimedia Commons (free licences only, no logos/maps/flags, files from upload/thumb hosts);
  `ai` generates with `MEDIA_IMAGE_MODEL` (FLUX Klein, `POST /images`, ~$0.009) when the owner has
  a balance and falls back to photos. The visuals model checks every picture (subject, no
  identifiable people, logos, gore, text) before use. Pictures are re-encoded to WebP under
  `MEDIA_ROOT/{id}/visuals/<hash>.webp` (cache by subject) and served same-origin, so
  `<Img>` works in the web renderer. AI pictures are charged after the build
  (`credits.charge_images_sync`, cost × markup); `POST /media` answers 402 for `ai` without a
  balance.
- Debater hints and disputes (`services/markers.py`): with scenes on, `prompt_builder` lets
  debaters write `[visual: …]` (≤ 2, anchored after the words before it) and offers the
  opponents' disputable scenes as a numbered list (`studio.visual_claims`, with fact-check
  results) to challenge with `[dispute N: reason]`. The worker strips both before saving the
  turn (the frontend hides them while streaming, `hideStudioMarkers`), stores hints/disputes in
  `visuals_json`; hint numbers count as said for grounding. Disputed scenes get a "disputed by …"
  stamp in the video (`TimelineVisual.disputes`) and on the board.
- Fact-check (`DebateConfig.fact_check`, needs scenes; `services/factcheck.py`): up to
  `FACT_CHECK_MAX_PER_TURN` checkable scenes per debater turn (figures, dates, attributed quotes)
  go to `FACT_CHECK_MODEL` (`perplexity/sonar`, web search, ~$0.005) on the debate's key; the
  cost joins `totals_json.analysis_cost` (billed like the debate; estimated with
  `FACT_CHECK_PRICE_USD`). Results (`SceneCheck`: verified | disputed | unverified, note,
  sources from the JSON and `message.annotations`) replace the "claim · speaker" note, reach the
  next speakers and the judge (`studio.verdict_evidence`), and `totals_json.claims` (per
  participant) feeds the leaderboard's Accuracy column.

### AI covers (`services/media/cover.py`)

- A clickbait 16:9 thumbnail per debate, shown first wherever a cover goes: gallery / landing /
  library / topic cards (`CardCover`; else the markup `DebateCover`, both 16:9), the link preview
  (`/og/d/{slug}.png` serves its 1200×630 crop, `lib/og.ts` puts the version in `?v=`), JSON-LD,
  the PublishKit (first YouTube thumbnail) and the owner's Export panel (`CoverCard`). The video's
  first frame stays the face-off.
- Build (`build_cover_job`, background queue, `cover_beat_key` heartbeat, timeout 15 min): the
  art director (`COVER_DIRECTOR_MODEL`, Claude Sonnet, ~$0.007) reads format, topic, the debaters
  (name, side, speaker colour, logo words) and the turns — never the verdict turn — and answers
  JSON `{hook ≤ 4 words / 22 chars ALL CAPS, concept, setting, rivals[] one per debater,
  centerpiece}` (`parse_brief`, asked twice at most; `fit_hook` trims); code builds the prompt by
  a fixed template (exact text, site palette, 2 face off / 3–4 in a row, same-logo note, script
  note for non-Latin hooks, 8 % crop margins, top-right corner free for the site's badges, no
  other text / real faces / winner hints); `COVER_IMAGE_MODEL` (GPT Image 2.5 Sunburst,
  `COVER_IMAGE_QUALITY` medium, ~$0.03) draws it with the debaters' logos as
  `input_references`; `COVER_CHECK_MODEL` (empty = the visuals model, system key) checks the
  hook's spelling, stray text and the rules (`parse_check`; an unreadable answer passes); a
  rejected picture is drawn once more, then the build fails. Files under
  `MEDIA_ROOT/{id}/covers/`: `<v>.webp` 1536 wide, `<v>-768.webp`, `<v>-yt.jpg` 1280×720,
  `<v>-og.jpg` 1200×630 (ffmpeg `fill_jpeg`; JPEG without a WebP encoder), immutable caching,
  kept by `DELETE /media`.
- Logos: the worker asks the site's renderer (`WEB_INTERNAL_URL`, compose `http://web:3000`)
  for `/og/logo.png?model=…` — the gallery's SVG and author mapping as a 512 px PNG, `X-Logo` =
  the icon name — and `cover_logos.DESCRIPTIONS` (one line per icon file; a test checks every
  file of `public/model-icons` has one) words it; no logo (or no answer) = a glowing emblem in
  the speaker's colour. No logo PNGs live in git.
- State: `debates.cover_status` (none | queued | running | ready | error, the latest build) and
  `cover_json` (`current` version id — null shows the markup cover —, `versions[]` ≤ 5 with
  files, hook, brief, cost, tries, source auto | owner | admin, own_key; `request` = who pays and
  the prices of the queued build; `error`). `DebateDetail.cover` (`CoverOut`: everyone the
  current `CoverImageOut`; the owner versions, error, `can_generate` / `reason` off |
  not_finished | busy | no_balance, `price_usd`), `GalleryItem.cover`, `DebateSummary.cover`.
- Who gets one: lever `ai_covers` (env `AI_COVERS`): `off`, `paid` (default: a completed run
  that was not a free run — `billing.free_run`, set at start; older rows by key and models —
  gets one on its own OpenRouter key or, with a balance, from it; `DebateConfig.cover=false`
  opts out, API tokens get none unless they send `cover`), `all_public` (free public debates
  too, at our cost). Not for debates the gallery check rejected or flagged for their content;
  one flagged only because the check could not run (`source=fallback`) gets it and stays private.
  `finish_debate_job` decides (`orchestrator._cover_plan`) before the keys are dropped, so an
  own OpenRouter key stays in Redis for the cover job, which drops it. The estimate adds
  `cover` / `cover_cost_usd` (`COVER_PRICE_USD` × markup) for a run that will get one; the
  wizard's "AI cover" switch says why it is locked on free runs.
- On demand: `POST /api/debates/{id}/cover` (owner, `completed | stopped`, `{hook?,
  user_provider_key?}`: the request's or the account's OpenRouter key, else the balance ≥ the
  price, 402; 403 off or a limited API token without a key; 409 busy; 429 `require_cover_slot`
  = the media limit; 503 maintenance), `PUT …/cover {version|null}`, `DELETE …/cover/{v}`. The
  page polls `GET /debates/{id}` while a build runs; the job also publishes `cover_progress`.
- Money: a ready cover on the system key is charged its director + pictures cost × the run's
  markup (`credits.charge_cover_sync`, ref `debate:{id}:cover:{v}`, ledger category `cover`);
  failed builds and own keys are not charged, the check is ours. `provider_usage` purposes
  `cover_director`, `cover`, `cover_check` (finance counts the first two as billed).
- Recovery fails an orphaned build (never draws again on its own: each try costs money). The
  console: debate card "AI cover" panel (versions, "New version (free)" with a hook = source
  admin, free; show a version or the markup cover, both audited `debate.cover_*`), the cover next
  to the text in the moderation queue, the lever, `cover` in finance / user spend charts. CLI
  `debatr cover DEBATE [--hook] [-o FILE]`, `run --cover/--no-cover`; MCP `generate_cover`
  (within `DEBATR_MAX_COST_USD`), `cover_url` in `get_debate`.
- Never run real covers in tests or QA without the owner's go-ahead (~$0.04 each); tests fake
  every provider (`tests/test_cover.py`).

### API tokens, the CLI and MCP

- `api_tokens` (`debatr_` + 256 random bits; only `token_hash` = SHA-256 is stored, plus last4,
  `spend_limit_usd`, `expires_at`, `last_used_at` refreshed at most once a minute). `get_current_user`
  accepts `Authorization: Bearer …` before the cookie; a bad, revoked or expired token is a 401
  (with `WWW-Authenticate`), never an anonymous request. `request_api_token(request)` tells routes
  a token is in use; `require_session_user` (password, profile, stored OpenRouter key, token
  management, device approval, Stripe checkout/confirm) answers 403 to tokens.
- Spending limit: `debates.api_token_id` = the token that started the run (create or draft start;
  the browser clears it). `services/api_tokens.budget_left` = limit − net ledger of those debates −
  `config_json.billing.estimate_usd` of its queued/running runs (`media_estimate_usd` while their
  automatic media build runs); `_estimate` sets `EstimateOut.token_budget_usd` and `sufficient`,
  `_require_sufficient` answers 402. Limited tokens cannot start paid media builds (`POST /media`
  with premium voices or AI pictures → 403). `with_token_defaults`: token debates are private
  unless `auto_publish` is sent explicitly (`model_fields_set`).
- `debatr login` = device flow (RFC 8628 style): `POST /api/auth/device` (login rate limit) →
  `{device_code, user_code "WDJB-MJHT", verification_uri_complete = SITE_URL/device?code=…}`;
  the signed-in browser approves on `/device` (`GET|POST /api/auth/device/{code}[/approve|/deny]`,
  60 per hour per IP so codes cannot be guessed; creates the token with name / limit / expiry); the CLI polls `POST /api/auth/device/token`
  (`pending | approved | denied | expired`) and receives the token once (GETDEL). Requests live in
  Redis 10 min (`device:{sha256(device_code)}`, `device:user:{code}`, a `:claim` key so a request is
  decided once); the waiting token is Fernet-encrypted.
- The CLI streams `GET /stream` itself: `LiveView` prints a turn only from its `turn_started`
  (joined mid-turn → whole text on `turn_completed`), catches up from `GET /debates/{id}` on
  `connected` and after reconnects, hides studio markers (`markers.StreamedTurn` holds back a
  trailing `[`/blanks) and styles inline Markdown (`styling.InlineMarkdown`).
- MCP (`debatr mcp`, stdio): `start_debate` returns at once; `get_debate(wait_seconds)` follows the
  SSE stream with `ctx.report_progress` per turn (clients usually cancel calls after ~60 s, hence
  the default 45). The token is re-read from env/config on every call; ApiError → ToolError.

### Workers and queues

- A worker process runs one job at a time and waits on the model while it streams, so Docker
  runs `TURN_WORKERS` (4) replicas of `worker`. A turn is one job, so debates interleave turn by
  turn; ordering inside a debate holds because each job queues the next. Queues in priority
  order: `default` (debate steps), `background` (trending, recovery: only when no turn waits),
  `media` (its own worker: TTS/ffmpeg). Workers fork per job in Docker (a hung job is killed
  without its worker) and get `stop_grace_period: 6m`, so a deploy lets the running turn finish.
- Fair share (`services/fair_share`): `MAX_ACTIVE_DEBATES_PER_USER` (create, start, resume) and
  `MAX_ACTIVE_MEDIA_PER_USER` (`POST /media`) answer 429; the user row is locked until commit.
  Both, `FREE_MODELS_PER_MINUTE` and `SIGNUP_BONUS_USD` are only defaults: the console's levers
  (`services/runtime_settings`, see "Admin console") override them without a deploy.
- Free debates (`services/free_limits`): a run on the system key whose models are all free, by an
  account without credits, uses the site's shared `:free` quota, so the levers
  `free_debates_per_day` (5 in any 24 h; Redis sorted set `free-runs:{user}`, so deleting a
  debate gives nothing back; 429), `free_max_rounds` (3), `free_max_debaters` (4) and
  `free_lengths` (very_short, short; 402) limit it at create / draft start (resumes are not new
  runs; env `FREE_*`; 0 / empty = no limit). Credits or an own OpenRouter key lift them all.
  `POST /debates/estimate` answers `free_runs` (the day's allowance) and `free_limit` (why it
  would be refused); `GET /api/status` carries `free_debates`, so the wizard locks longer
  options when `paidLocked` and shows / sends the clamped rounds and length (`withinFreeLimits`).
- Passing provider failures (429, 5xx, dropped connection, empty answer; `RETRY_STATUSES`) are
  tried again after `RETRY_PAUSES` (3 s, 10 s) within the turn's deadline, only before any text
  was streamed, since a failed turn stops the debate.
- `services/free_quota`: OpenRouter allows 20 `:free` requests a minute per account, shared by
  every system-key Free Router debate; turns wait for a slot (`FREE_MODELS_PER_MINUTE`, fixed
  window in Redis) instead of failing on 429. Own keys skip it.
- Recovery (`services/recovery`, scheduler every minute): every debate job and the media build
  hold a heartbeat (`services/heartbeat`, Redis key refreshed every 20 s, TTL 60 s, by a thread).
  A queued/running debate or media build with no heartbeat and no job waiting in its queue, on
  two checks in a row, is queued again from its first missing turn (failed rows dropped) or as a
  build (cached turns reused), up to `RECOVERY_ATTEMPTS`; runs older than 6 h, or whose own
  OpenRouter key expired, fail instead (debate → Resume, media → generate again). An orphaned AI
  cover build fails at once (`cover_beat_key`; drawing again would cost again).

### Trending topics (news → debate topics) and AI topic ideas

- `services/trending.py`: `refresh_trending_job` reads the RSS feeds in `FEEDS` (BBC, Guardian,
  NPR, NYT, Al Jazeera, DW, Google News with the real outlet from `<source>`, Hacker News, Ars,
  Verge, ScienceDaily), keeps headlines ≤ 48 h old with http(s) links, drops blocked ones, sends a
  round-robin pool (3 headlines per wanted topic, 150–400) to the topic writer (lever
  `topic_model`, env `TOPIC_MODEL`: Claude Haiku 5.5, ~$0.007 a list, system key) and keeps only
  topics that cite pool headlines (no invented stories). Rank = model heat + 1.5 per extra outlet
  carrying the story (up to 3). The best `trending_daily_topics` per list (lever, env
  `TRENDING_TOPIC_COUNT`, 20) are saved as a `TrendingBatch` with `TrendingTopic` rows
  (`question`, `label`, `brief` — what happened, because the debaters do not know recent news —
  `category` from `TOPIC_CATEGORIES`, `heat`, `outlets`, `sources_json` = original articles). The
  wizard shows the newest batch, at most `trending_shown_topics` (lever, env
  `TRENDING_SHOWN_TOPICS`, 50); older batches are the archive (`stats_json`: feeds, headlines,
  dropped topics with reasons, `review_model`) that only answers searches:
  `GET /api/topics/trending/search?format=&q=` (every word in question / label / brief,
  `search_terms` escapes LIKE wildcards; newest first, 30 at most, repeats across days and of
  today's list once), `useTopicArchive` (debounced, keeps the last answer while typing) → "Earlier
  topics" under today's matches. Repeats across days are fine by design. Haiku 5.5 wrote clearly
  better lists than Gemini 2.5 Flash in a side-by-side run (battles: "Ronaldo or Messi?", "iPhone
  or Android?" against "Exports or domestic spending?") for less money; it takes ~45 s a list.
- Safety, three layers, all strict: `BLOCKED_TERMS` (sexual content, violence/gore, tragedies,
  suicide…) on every headline before the model sees it and on the generated text, then a second
  focused review call (`SAFETY_RULES`, "when in doubt, reject") by another model (lever
  `topic_review_model`, env `TOPIC_REVIEW_MODEL`: Gemini 2.5 Flash), so the writer never judges
  its own topics. No usable review answer → the batch is not saved (fails closed) and visitors keep
  the previous one. Admin: Trending topics → Hide; Trending batches → "Build a new batch now";
  Settings → Topics (the four levers; the model levers use the wizard's `ModelPicker`).
- Schedule: `TRENDING_REFRESH_HOURS` (24 in production, 720 in dev `.env`, 0 = off). The
  `scheduler` service enqueues the job hourly; the job builds only when `is_due` (newest batch
  older than the interval minus 30 min slack) and holds `trending:refresh:lock`, so restarts and
  extra triggers never add batches. `GET /api/topics/trending` (public) also enqueues it on a
  stale read (at most every 10 min via `trending:refresh:queued`), so native dev works without
  the scheduler. Step 1 of the wizard lists them (`?format=`, `useTrendingTopics(list)` caches
  per list); picking one sets `topic` and links the story
  (`DebateConfig.news`: brief, outlet, title, url, published_at), which always goes to the models:
  `prompt_builder._context_block` puts it into every prompt as "News background" (before the
  user's angle, `description`). A link never outlives its question: editing the question, clicking
  the picked card again or "×" unlinks it; switching topics also clears the angle. Switching the
  format keeps the topic and its story (`applyFormat`): a debate's news topic can become a battle.
- A list per show format: `Format.topic_style` (`formats/base.TopicStyle`: noun, the wording rule,
  how a story becomes such a topic, what makes it hot, an extra review rule). The rap battle writes
  rivalries ("A or B?" naming two concrete, familiar rivals, a yes/no hot take now and then, never
  abstract trade-offs; ≤ 60 characters; its review also rejects sides that are politicians, parties, real people
  other than athletes / artists compared on their work, or groups of people). Asking for "no
  abstract trade-offs" without making "A or B?" the rule swung the model to yes/no headlines
  ("US bans China's DeepSeek?"). A format with the debate's style shows the debate's list
  (`formats.topic_list_of`, `topic_styles`; the frontend mirrors it as `FormatSpec.topicList`).
  `build_batch` asks every list from the same pool in parallel (`usage.ContextThreadPool`) into
  one batch (`TrendingTopic.format`, ranks per list, `stats_json.formats` = asked / kept / error,
  dropped entries carry their format). The default format's list is required (no list → no
  batch); another one that fails only notes its error and `GET /api/topics/trending?format=`
  answers from the newest batch that has that list. Batches from before the column hold debate
  topics only (migration 0017), so a battle list appears with the next batch (or "Build now").
- AI topic ideas (`services/topic_ideas`, `POST /api/topics/ideas {text 3–300, format, language}`,
  signed in): one call to the topic writer (lever `topic_model`, the trending lists' writer: one
  voice for both; ~$0.0001, ~2–3 s, system key, not billed) writes 3 topics in the format's style (the sharpest form of the user's words, a bolder
  take, another angle) in the language of the text (`language` when unclear), or `[]` for text the
  gallery check would refuse; `parse_ideas` drops numbering / quotes, repeats, ones under 8 or over
  `TOPIC_MAX_LENGTH` characters. `TOPIC_IDEAS_PER_HOUR` (40) per account → 429; no key → 503; a
  failed call → 502. Booked as `topic_ideas` on the account (`usage.on_behalf_of`).

### Credits and payments

- Prices (`services/credits.Prices`): provider cost × `credit_markup` for models, fact-checks and AI
  pictures, at least `min_debate_charge_usd` for a completed paid debate (a stopped or failed run
  pays its usage only), `tts_price_per_1k_chars` for premium voices on the system key. All three
  are levers of the console (Settings → Prices; env `CREDIT_MARKUP`, `MIN_DEBATE_CHARGE_USD`,
  `TTS_CREDIT_PRICE_PER_1K_CHARS`). A run keeps the prices it was quoted: create / draft start
  store them in `config_json.billing.prices` (a resume keeps them), `POST /media` and
  `_auto_media` in `media_json.prices`; charges read the snapshot (`prices_of`, env values for rows
  from before it). The public `GET /api/billing/config` shows prices, never the markup.
- `users.credits_usd` is the balance; `credit_transactions` is the append-only ledger. Every
  change goes through `services/credits.apply_transaction(_sync)`; `provider_ref` makes charges
  and Stripe sessions idempotent. The balance may go slightly negative (actual cost > estimate).
  The user row is locked with `populate_existing` (`_locked_user`): a User already loaded in the
  session (the API's sessions never expire objects) would otherwise keep its old balance and
  overwrite a charge committed meanwhile. Manual credits: `python -m app.manage credits` (kind
  adjustment | bonus | refund, provider `admin`, internal reason in `meta_json.reason`).
- `POST /api/billing/checkout` creates a Stripe Checkout session (`stripe.StripeClient`,
  `v1.checkout.sessions`); `POST /api/billing/webhook` (`checkout.session.completed` / `async_payment_succeeded`) and
  `GET /api/billing/confirm?session_id=` (called by the Account page after redirect) credit it.
  `DEV_FAKE_PAYMENTS=true` (non-production) credits instantly without Stripe.
- `GET /api/billing/usage` aggregates the current month (tokens, voice ms, renders, spend) plus
  one UTC-day bucket per day (`services/ledger.build_usage`; debate metrics count on the day the
  debate was created). `GET /api/billing/transactions` pages with `limit`/`offset`; rows carry
  `category` (models | voices | pictures | topup | bonus | refund | adjustment) and `title`
  (debate title without the "Premium voices: " prefix). `GET /api/billing/transactions.csv`
  exports the whole ledger (formula-looking cells are escaped).
- A personal OpenRouter key (`PUT /api/auth/me/openrouter-key`) is validated against OpenRouter,
  stored encrypted with `SECRET_KEY` (`core/security.py`) and shown masked (`…last4`).

### Statistics data (provider costs, activity, views)

- `provider_usage` (`services/usage`): one row per paid provider call or try — purpose (`turn |
  verdict | verdict_structure | moderation | factcheck | director | sketch | image |
  image_check | highlights | trending | trending_review | topic_ideas | tts | …`), provider, the
  model that
  answered, `key_owner` (`system` | `user`: the debate's own OpenRouter key or an own ElevenLabs
  key), tokens, TTS chars, `cost_usd` (OpenRouter's `usage.cost`; ElevenLabs is an estimate from
  `USD_PER_1K_CHARS`, `meta_json.estimated`), `ok` + `error_kind` (`usage.classify_error`),
  `duration_ms`. Written only by `media/llm.py` (`complete` / `complete_message` /
  `generate_image`, each with a required `purpose`), `orchestrator._generate` (every try,
  `_book`) and the TTS step (`jobs._book_tts`). New provider calls must go through these. The
  debate comes from `@usage.attributed` jobs via a context variable (an account outside a
  debate from `usage.on_behalf_of`); worker thread pools use `usage.ContextThreadPool` so it
  reaches sketches / pictures / fact-checks. Booking never fails
  the caller. Unlike `totals_json` it includes retries, dropped router answers and the system-key
  studio calls (director, sketches) that are not billed to users.
- `turns.usage_json` also keeps `duration_ms`, `ttft_ms` and `error_kind` of the kept answer
  (`orchestrator.turn_usage`).
- Activity (`services/activity.note_activity`, called by `get_current_user` for cookies and
  tokens): `users.last_seen_at` at most every 10 min and one `user_activity_days` row per UTC day
  (migration 0012 backfilled days from sign-ups, logins, debates, likes, votes and tokens).
- Views (`services/views`): only the beacon `POST /api/debates/{id}/view` counts (reading a
  debate through the API never does: the renderer, client navigations, the CLI, agents). The
  debate page sends it on every mount of a public debate (`api/debates.countView`; the referrer's
  host only when it is the page the browser loaded, `isLandingPage`, else `internal`, plus
  `?ref=`); the embed on its first play (`place=embed`, the frame's referrer = the embedding
  site). Body: text/plain JSON (`ViewBeacon`, no preflight; unreadable = a page view, direct).
  Bots by User-Agent (`is_bot`) count nothing; one view per IP and debate in 6 h, never the
  owner's. `classify`: search | ai | social | embed (a player elsewhere or its `?ref=embed` link)
  | other | direct | internal (the site's own host, a navigation inside the site, the Share
  preview). Stored as counts only: `debates.views` + `view_days` (UTC day, debate, place, source;
  migration 0016) — no IP, address or account; embedding hosts in Redis sorted sets
  (`views:embeds:{id}` and `views:embeds`, 90 days since the last view).

### Admin console (`/admin`, `/api/admin/*`)

- Own origin: `ADMIN_HOST` (production: e.g. an `admin.` subdomain; empty in development =
  the site's origin; empty in production = console off, error at startup). `app/admin/gate.py`
  (outermost middleware) answers `/api/admin*` only on that host (404 elsewhere), 404s the rest of
  the API there, enforces `ADMIN_ALLOWED_IPS`, refuses `Sec-Fetch-Site` other than same-origin /
  none (every `*.ai-debates.net` app is the same *site*, so SameSite cookies do not protect the
  console from them) and unsafe methods without the console's Origin, and adds no-store / noindex
  / DENY headers. `frontend/Caddyfile` has the `http://{$ADMIN_HOST}` block: the console's own static build
  (`/srv/admin`, never the site's files), strict CSP. Without ADMIN_HOST in .env, compose leaves
  `ADMIN_ON_SITE` empty and the site's block serves the console at /admin as well (with it set,
  `ADMIN_ON_SITE=off` and /admin on the site is just a page the site does not have).
- Admins are accounts with `users.admin_role` (`admin` | `moderator`, `access.PERMISSIONS`),
  granted only by `python -m app.manage admin grant`, which prints a one-time enrollment code
  (Redis, 24 h). Sign-in (`routes_auth`): password (5 tries per 15 min per IP and per email, one
  answer for every refusal) → ticket cookie (10 min) → TOTP code or recovery code, or on the first
  sign-in the enrollment code + a code from the new authenticator → 10 recovery codes (hashes
  stored). Wrong codes: 5 per ticket, 5 per account in 15 min → locked; a code works once
  (`admin:totp_step`). TOTP secrets: Fernet with a key derived from `SECRET_KEY` + own context.
  `ADMIN_SKIP_2FA=true` (development only, `settings.admin_skip_2fa` is false in production):
  the password alone signs in (`next="done"`), no enrollment, `require_sudo` passes,
  `AdminMeOut.two_factor=false`.
- Sessions live in Redis (`services/admin/sessions`): `__Host-debatr_admin` cookie (HttpOnly,
  SameSite=Strict; no prefix over plain http), only its SHA-256 stored, idle and absolute 24 h
  (one sign-in a day), listed and revocable; `resolve_admin` re-checks role, `is_active`,
  enrollment and `users.session_epoch` (bumped by password change, 2FA reset, sign-out everywhere) on every
  request and never accepts an `Authorization` header. Unsafe methods need `X-CSRF-Token`
  (from `/auth/me`). `require_sudo`: a TOTP code (or a passkey) confirmed in the last 5 min (403
  with `X-Admin-Sudo: required`; the UI asks and retries).
- Passkeys (`services/admin/passkeys`, `routes_passkeys`, py_webauthn; table `admin_passkeys`,
  public keys only): added on the Security page after sudo (at most 10), then usable instead of
  the TOTP code at sign-in (`AdminLoginOut.passkey`, "Use a passkey") and for sudo
  (`AdminMeOut.passkeys`). TOTP stays the base: enrollment needs it, and it or a recovery code
  still works without the passkey. User verification required; RP ID / origin = `ADMIN_HOST`
  over https in production (never the request's headers), the page's origin in development. The
  challenge lives 5 min in the sign-in ticket or in Redis per session and is used once; a wrong
  answer counts like a wrong code. `app.manage admin reset-2fa` / `revoke` delete the passkeys.
  The frontend converts options and credentials by hand (`src/api/admin/webauthn.ts`).
- `admin_audit_log` is append-only (trigger refuses UPDATE / DELETE / TRUNCATE; no foreign
  keys). Everything goes in: sign-ins and failures, 2FA and passkeys, sessions, sudo, server
  commands (`record_sync`), every console change with its reason and before / after; `scrub`
  drops secret fields. The Audit log page (`routes_audit`, permission `audit` = admins only;
  `GET /audit` with `AuditQuery`: tab all | security (`auth.*`, `role.*`), search, actor, action
  exact or `prefix.`, target, outcome, UTC days; `/audit/facets` for the dropdowns;
  `/audit/security` = 7-day counts) shows a field-by-field diff per entry; cards link to it with
  `?target_type=&target_id=`. (Old rows may carry `db.*` actions of the sqladmin the console
  replaced.)
- Levers (`services/runtime_settings`, table `runtime_settings`, Settings page, permission
  `system`): `registration_open` (403 on `POST /auth/register`), `maintenance` +
  `maintenance_message` (503 with the message on create / start / resume / `POST /media`; drafts,
  estimates and running debates go on; the site shows a banner and the wizard's Start is off via
  public `GET /api/status`), `disabled_models` (left out of `GET /api/models` = wizard, CLI, MCP;
  400 on estimate / create / start / resume; the Free Router drops such a pick like a
  classifier's, a pinned one gives way to the router, and it is never a fallback),
  `signup_bonus_usd`, `free_models_per_minute`, `max_active_debates_per_user`,
  `max_active_media_per_user`, `muted_alerts` (see Alerts), `free_verdict_model` (verdict + gallery
  check of free debates), `free_debates_per_day`, `free_max_rounds`, `free_max_debaters`,
  `free_lengths` (see "Workers and queues"), `credit_markup`, `min_debate_charge_usd`,
  `tts_price_per_1k_chars` (see "Credits and payments"), `ai_covers` (off | paid | all_public, a
  "choice" lever; see "AI covers"), `trending_daily_topics`, `trending_shown_topics`,
  `topic_model`, `topic_review_model` (see "Trending topics"). Model levers (kind `model`) use the
  wizard's `ModelPicker` on the full catalogue (`SettingsOut.models` = `ModelInfo`, plus models a
  lever names that left it; the console cannot reach the public `/api/models`); turned-off models
  are added with it too. Only the fields of `Levers` exist (pydantic limits); without a row
  the env setting applies; a broken row is ignored. `PUT /settings/{key}` / `POST
  /settings/{key}/reset` need sudo and a reason and write the row + audit entry in one
  transaction; processes read through a 5 s cache (`CACHE_SECONDS`), so a change lands within
  seconds everywhere. Tests stub the table with the `levers` fixture (conftest).
- Alerts (`services/alerts`, optional `ALERT_TELEGRAM_BOT_TOKEN` + `ALERT_TELEGRAM_CHAT_ID`):
  a console sign-in (with how the second factor was passed), a locked second factor, a new
  account (`routes_auth.register`) and a debate that starts (create or draft start, not resume:
  `routes_debates._announce`) go out at once from the API (`notify_soon`, a background task;
  sign-ups and debates capped at 30 an hour each, `Alert.hourly`); a failed trending batch from
  its job; `check_alerts_job` (scheduler, every 5 min) gathers facts and `decide` (pure) raises:
  5+ failed console sign-ins in 15 min, newly flagged debates, 3+ failed debates in an hour at
  30 %+ of finished ones, runs without heartbeat or waiting job for 10+ min on two checks in a
  row, OpenRouter < $5 / < $1, ElevenLabs key rejected or < 10 % / < 2 % characters, new top-ups,
  disk ≥ 85 % / 95 %. Antispam: a quiet key per kind and severity (an escalation sends again);
  flagged debates and top-ups are told new by the ids the last check saw (the first check after
  a Redis reset reports none). The Settings page's "Telegram notifications" card mutes kinds
  (lever `muted_alerts`; catalogue with group / label / hint in `services/alert_events`, sent as
  `SettingsOut.alert_events`; a new alert kind goes there too): a muted alert is neither sent nor
  listed, and a change of the list is itself an alert that cannot be muted (`mutes`, like the
  test). Every other alert, sent or not, lands in `alerts:recent` (Settings page, "Send a test"). httpx errors print the URL with the bot token, so only their class name is
  kept. The alerts run on the scheduler and the background queue, so they cannot report their
  own end: `GET /api/health/full` (public, closed on the admin host) answers 503 when a queue
  has no worker (`queue_manager.process_checks`; a killed worker counts until its RQ key
  expires, ≤ ~7 min) or the cron scheduler is gone, for an outside uptime monitor. The
  container healthcheck stays on `/api/health` (the API works without workers).
- Overview (`GET /api/admin/overview?period=24h|7d|30d|90d|all&refresh=`): one cached answer
  (Redis 60 s per period and permission scope) built in a read-only transaction with a 5 s
  statement timeout (`access.read_only_db`). Tiles carry the previous period for deltas; series
  are UTC buckets (hour / day / week, gaps filled); money and top spenders need the `money`
  permission; `cost_tracked_since` marks periods older than `provider_usage`. Audience: views of
  the period's whole UTC days (`debates.views` / `views_by_source`; 24 h = today), the stacked
  "Views by source" chart (`series.views_<source>`, none hourly, `SOURCE_COLORS` validated) and
  "Embedded on" (`embeds`, 90 days); `views_since` marks periods older than `view_days`. The
  debate card has a Views panel (by source and place, before sources were kept, its embedding
  sites). The attention list
  (`stats.attention_items`, pure) covers runs without a heartbeat, OpenRouter balance (cached
  5 min), ElevenLabs key and character quota (`tts/elevenlabs.system_quota`), the last backup
  (Redis `backup:last`, production only), flagged / failed debates, failed audio, negative
  balances, failed console sign-ins, stale trending and the admin's last recovery codes.
  Charts follow the dataviz rules: one axis, legend for 2+ series, crosshair / per-column
  tooltips, keyboard arrows, a table view per chart, colours validated against the card surface.
- Users (`/api/admin/users*`, permission `users`; ledger and credits also `money`): the list
  (`UserListQuery`: search by email / name with `%` `_` escaped or an exact id, filters, sort,
  `limit` ≤ 200) computes ledger / debate / token totals per account in SQL so they filter and
  sort across pages; `POST /users/export` is the same list as CSV (sudo, audited, formula cells
  escaped). The card (`GET /users/{id}`): profile, 30-day and all-time stats (pure
  `users.period_stats`: runs without drafts, free vs paid models, spend by category, cost on
  system keys from `provider_usage`), spend per UTC day, favourite models, API tokens, likes and
  votes given by owner (many to one owner = boosting), the account's audit entries; ledger and
  debates page on their own. Changes are POSTs with a required `reason`, audited in the same
  transaction: credits (adjustment / bonus / refund through `apply_transaction`, `provider_ref =
  admin:<idempotency_key>` from the dialog so a retry never moves money twice, sudo above
  `ADMIN_SUDO_USD`, at most $1000), disable (bumps the epoch; optionally stops runs, revokes
  tokens, unpublishes) / enable, revoke one or all tokens, remove the stored OpenRouter key,
  remove every like and vote it gave (boosting; counters rebuilt), sign out everywhere,
  temporary password (sudo, shown once) and delete (sudo + typed email: debates
  and their `MEDIA_ROOT` folders go too, counters of debates it liked are rebuilt). Accounts with
  a console role and the admin's own are never disabled, deleted or given passwords here (409:
  `app.manage` on the server).
- Debates (`/api/admin/debates*`, read `debates.read`; money columns, provider calls, ledger and
  refunds `money`): the list filters by status (`active` = queued or running), moderation,
  audio, gallery, own key, API token, debater model, owner, period, and searches title / id /
  slug; turns, system-key cost (`provider_usage`) and net charge come from SQL subqueries. The
  card: the video once audio is ready (the public page's `DebatePlayer` in a lazy `VideoPanel`,
  16:9 / 9:16; files via `GET /debates/{id}/files/{path}`, rooted at the debate's folder, since
  `/api/media` is closed on the admin host; the console CSP allows `media-src data:` for the
  player's audio unlock), transcript with per-turn usage, timing, scenes and fact-checks,
  verdict and moderation, audio state, Redis state (heartbeats, recovery attempts, stop flag, keys waiting), provider
  calls by purpose, ledger rows, the stored config (key-like fields scrubbed) and its audit
  entries; opening someone's private debate is audited once an hour per admin (`debate.viewed`).
  Changes (reason required, audited): stop, resume (`debates`; system key only, the owner is
  charged for the rest as usual, shared `resume.reset_for_resume`), rebuild audio (free for the
  owner: `media_json.free` skips the build's charges), recount, delete (sudo); approve / reject
  (`moderation`; reason in `moderation_json.admin_reason`, approve publishes only when the
  owner wants the gallery), publish (only what the owner asked for) / unpublish; refund
  (`money`: up to the net charge, `provider_ref = admin:refund:<debate>:<idempotency_key>`, sudo
  above `ADMIN_SUDO_USD`). `GET /moderation` = flagged debates oldest first + recent decisions;
  the page is keyboard-driven (j/k, a, r, o). Moderators get `debates.read` + `moderation` only.
- Finance (`/api/admin/finance?period=30d|90d|12m|all`, `money`; CSV via `POST /finance/export`,
  sudo): ledger sums (top-ups, bonuses, refunds, adjustments, charges by category) against the
  system-key cost (`provider_usage`, by provider and purpose) per day / week / month; margin =
  charged − refunds − cost; effective markup = charged ÷ cost of the billed purposes (`turn`,
  `verdict`, `factcheck`, `image`, `tts`); the rest is "cost nobody pays"; liabilities, top payers
  and spenders; Stripe checkout sessions of the period reconciled with `stripe:<id>` top-ups when
  Stripe is configured. Models (`/api/admin/models?period=30d|90d|all`, `debates.read`; cost per
  turn with `money`): per answering model tries and failures by kind, p50 / p90 of turn time and
  first word (`percentile_cont`), tokens, judge / audience wins and fact-check accuracy
  (`ranking.build_leaderboard` over every finished debate), Free Router picks, turned off (a
  lever). The console's
  `/auth/me` carries the server's `version` (shown above "Sign out").
- Trending (`/api/admin/trending*`): batches with feed / headline / dropped counts and cost, a
  batch's topics, dropped topics and blocked headlines; hide / show a topic (`moderation`);
  build now (`system`).
- System (`/api/admin/system/*`, permission `system`; the page polls runs and queues every 15 s):
  RQ queues and registries, workers (`Worker.all`), the cron scheduler and its jobs (RQ 2.x keeps
  heartbeats and history in Redis: `rq:cron_jobs`, `rq:cron_job:<name>:jobs`), failed jobs with
  the end of the traceback (requeue / delete); runs in flight with heartbeat, waiting job and
  recovery attempts, and "recover now" (`recovery.recover_now`: refuses a run that has a worker
  or a job waiting; imported lazily, it pulls in the orchestrator); limits (free-model slots this
  minute, `:free` calls in 24 h against OpenRouter's daily cap, accounts at the fair-share limit
  now and refused in 24 h: `fair_share.note_refusal` keeps a Redis sorted set); providers
  (OpenRouter `/credits` + `/key`, cached 5 min; ElevenLabs key, plan and characters; payment
  settings); health (Postgres size, connections and largest tables, Redis memory, disk and
  MEDIA_ROOT folders with the heaviest ones and orphans, cached 5 min; `APP_VERSION` = the git
  commit passed as the `GIT_SHA` build-arg by deploy.sh / `make up`; alembic current vs head;
  settings with secrets as set / not set; the last backup). Deleting orphan folders (debates
  gone, untouched for an hour) needs sudo and re-checks every name on the server.

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
  never raw fetch or axios. No `alert`/`confirm`: use `useToast` and `ConfirmDialog`; no native `<select>`:
  use `Dropdown` (the design wants no system popups). Styling uses the
  theme tokens from `src/index.css` (`bg-surface`, `text-muted`, `font-display`, `rounded-panel`…).
- Routes (React Router 8 framework mode): every route with a server `loader` also has a
  `clientLoader` over the same load function, so client navigations never hit the Node server
  (no `.data` requests); `_site` never revalidates (the session lives in AuthProvider); filters
  live in the URL and change with `setSearchParams(…, { replace: true, preventScrollReset: true })`,
  loading = `useNavigation()`; loaders throw route error data (`data({status, detail})`) and the
  route's ErrorBoundary renders it with the same status code. A new public page = a route
  module with `load(get)`, `loader` + `clientLoader`, `ErrorBoundary`, `microcache` and exactly
  one `<Seo>` (data from `lib/seo.ts`; its canonical path comes from the API, never built in the
  frontend; `handle.lang` when its language is not English). Private pages render
  `<Seo {...privateSeo(title)} />`.
- SSR-safe frontend (public pages render on the server): router imports come from
  `react-router` (v8 dropped `react-router-dom`). Browser-only modules — Remotion
  (`src/video/**` except constants / timing), rough.js, d3-geo, the MP4 renderer, canvas work:
  the `CLIENT_ONLY` list in `eslint.config.js` (DebatePlayer, SceneStill, ExportRail,
  ExportCard, PublishKit, youtubeKit) — reach other code only through `lazy()` inside
  `<ClientOnly fallback=…>` with a fallback of the same size (the debate player is the
  exception: its facade state is false on the server and while hydrating, and only the lazy
  player sits in a Suspense — React streams a large boundary after the shell, which sent its
  markup twice); `no-restricted-imports` refuses
  static imports (type imports are fine) and any import of console code (`admin/`) from the
  site. What differs between the server and the viewer (time zone, the current moment,
  `window` / `document`, browser storage) waits for `useHydrated()` or lives in effects and
  handlers: `RelativeDate`, `useLocalKey` (`useSyncExternalStore` with a server snapshot);
  `formatDateShort(iso, 'UTC')` before hydration. Pages pass media folders as the API gives
  them (paths); only the Remotion islands make them absolute (`absoluteMediaBase`). Server
  code lives in `*.server.ts` modules, the only place `process` is allowed.
- Brand name and copy live in `src/lib/brand.ts`; speaker colours in `src/lib/format.ts` mirror
  `backend/app/services/media/timeline.py` (PALETTE / MODERATOR_COLOR / JUDGE_COLOR) and
  `cli/src/debatr/render.py`.
- `cli/pyrightconfig.json` must stay a pyrightconfig.json: pyright prefers the root
  `pyrightconfig.json` (backend) over any `[tool.pyright]`, so the CLI would silently be checked
  as the backend (locally green thanks to `backend/.venv`, red in CI).
- The CLI is a separate package that only uses the public API: when `DebateConfig`, `DebateDetail`
  or SSE events change, update `cli/src/debatr/debate.py` / `render.py` and the fake server in
  `cli/tests/conftest.py`. Its version lives in `cli/src/debatr/__init__.py`; pushing a
  `cli-vX.Y.Z` tag publishes it to PyPI (`.github/workflows/cli-release.yml`, trusted publishing,
  environment `pypi`). `hideStudioMarkers` in `lib/format.ts` and `cli/src/debatr/markers.py` are
  twins.
- Tests are pure (no DB/Redis). Use `httpx.MockTransport` via `OpenRouterClient(transport=...)`
  for client tests. Put integration checks behind Docker. `tests/conftest.py` keeps
  `provider_usage` rows in memory (`usage_rows` fixture) and stubs `note_activity`.

## Gotchas

- `.env` is shared by Docker and native dev: leave `DATABASE_URL`/`REDIS_URL` unset so the
  localhost defaults apply natively; docker-compose injects the container URLs.
- Postgres stays on major version 18 in compose. Since 18 the image keeps the cluster in
  `/var/lib/postgresql/18/docker` (volume `postgresql_data` at `/var/lib/postgresql`) and refuses
  a data directory of another major, so a bump needs the data moved (dump + restore or pg_upgrade;
  15 → 18 started from an empty database). The redis:8 image declares no `VOLUME`: `redis_data`
  keeps its RDB snapshot.
- Pages come from the `web` service (Node, react-router-serve :3000, `mem_limit: 256m`,
  `--max-old-space-size=160`; ~50 MB idle, ~100 MB under load). `frontend/Caddyfile`: `/api*` →
  api, `/assets/*` and other build files → `/srv`, the console → `/srv/admin`, everything else →
  `web:3000`; 502/503/504 from it → `offline.html` (503 + Retry-After); `/path/` → `/path` (301);
  `/robots.txt`, `/sitemap.xml`, `/sitemaps/*` and `/<8-128 chars>.txt` (the IndexNow key) → api
  (`npm run dev` proxies the first three too). Every response but `/embed/*` gets
  `X-Frame-Options: SAMEORIGIN` + `Content-Security-Policy: frame-ancestors 'self'` (deferred
  `header @framed`); the embed route sends no `frame-ancestors` (any parent).
  Views come only from the page's beacon after hydration (see "Statistics data"), so crawlers
  without JavaScript and micro-cached pages neither add nor hide views.
- The `frontend` container name (`ai-debates-frontend-1`) is referenced by the external Caddy
  on the production host via the `caddy_net` network. `frontend/Caddyfile` trusts private-range
  proxies (`trusted_proxies`) so the external Caddy's `X-Forwarded-Proto: https` and client IP
  reach uvicorn; without it the API sees `http` and every visitor shares one IP for rate limits,
  the console's IP checks and view counts.
- `DEBATE_CREATE_RATE_LIMIT` (per IP per hour) and `LOGIN_RATE_LIMIT` are extra abuse limits on
  top of accounts/credits; set 0 to disable.
- Stripe: without `STRIPE_SECRET_KEY` the checkout endpoint returns 503 and the Account page
  disables top-ups; the Stripe webhook must reach `/api/billing/webhook` (Caddy proxies `/api*`).
- Backups: nothing in the stack backs up Postgres by itself; run `scripts/backup-db.sh` from cron
  on the server and keep a copy off the VPS in an encrypted place (rclone `crypt` remote via
  `BACKUP_RCLONE_REMOTE`): a dump holds emails, password hashes and the ledger. Restore for real
  with `docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean
  --if-exists --no-owner' < backups/<file>.dump` after stopping api/worker/scheduler.
- Changing `SECRET_KEY` invalidates every login cookie and makes stored OpenRouter keys
  undecryptable (users must re-enter them) and the admins' TOTP secrets unreadable (reset each
  with `python -m app.manage admin reset-2fa <email>`).
- Production needs `ADMIN_HOST` in `.env`, a DNS record for it and a block in the external Caddy
  that proxies it to the frontend container like the site; without `ADMIN_HOST` the console is
  off. The external Caddy must pass the original Host header (its default). Passkeys are bound
  to that host: a passkey added on one `ADMIN_HOST` does not work on another.
- Media: `MEDIA_ROOT` is `./media` natively and the `media_data` volume (`/media`) in Docker;
  the worker image target installs ffmpeg, the api target does not. Docker runs `worker`
  (`TURN_WORKERS` replicas, `--queues default,background`), `media-worker` (`--queues media`)
  and `scheduler` (RQ cron, api image); natively one SimpleWorker takes every queue
  (`RQ_SIMPLE_WORKER=true` in `.env` is for macOS; compose overrides it to forking workers).
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
- Preview cards (`src/server/og`): `takumi-js/node` exports a JS wrapper around the native
  `Renderer`, whose `registerFont(font)` takes one argument (`key` inside the descriptor) and
  `unregisterFont({ name })`. Register fonts only that way (pinned): a render's `fonts` option
  goes through the binding's `cacheFont`, which the 2.17 native build lacks. Inline `<svg>` in the
  card's JSX becomes an image; logos are image sources keyed by `src`. Check a redesign with a
  Vite harness (`createServer` + `ssrLoadModule('/src/server/og/render.server.tsx')`, `ogImage`)
  and bump `OG_DESIGN`.
- Tailwind 4's `translate-x-*` / `-translate-y-*` set the CSS `translate` property, not
  `transform`: animate them with `transition-[translate,…]` (a `transition-[transform]` jumps).
- React 19 server rendering streams a Suspense boundary with large content after the shell (the
  fallback first, the content later with a swap script) even when nothing suspends: keep
  server-rendered markup that matters for the first paint out of Suspense boundaries.
- Fonts stay files in both builds (`build.assetsInlineLimit` refuses woff2): an inlined `data:`
  font weighs down the render-blocking stylesheet and the console's CSP (`font-src 'self'`)
  blocks it. The fallback faces' metrics in index.css were computed from the woff2 files
  (fontTools: average width of English text against Arial / Arial Bold at the weights and
  optical sizes in use); recompute them when a family changes.
- Browser MP4 export: `@remotion/web-renderer` rounds scaled sizes up and H.264 needs even
  sides, so 720p uses exactly `SCALE_720P = 2 / 3` (0.6667 gave 1281×721 and failed).
- Scene pictures: Homebrew's ffmpeg has no libwebp encoder, so native builds store JPEG
  (`ffmpeg.to_web_image` falls back; Debian's ffmpeg in Docker writes WebP). Wikimedia's API
  wants a descriptive User-Agent; its search matches every word, so `images.search_queries`
  retries with fewer words. `DELETE /media` keeps `visuals/` (the transcript board shows the
  pictures too).
- Live scenes delay the next turn (director ~2 s; with fact-checks or AI pictures 5–17 s) because
  later speakers must see the scenes they may dispute; `design_turn` never raises.
- Old rows may have `turn_type=moderator_comment` and inline `"[Error ...]"` text; both are still
  handled (`scheduler.MODERATOR_TURN_TYPES`, `lib/format.isErrorTurn`). Debates created before
  accounts have `user_id=NULL`: readable via their link, manageable only in the admin console.
- Speaker names: the wizard has no name fields. `lib/modelNames.speakerNames` calls the host
  "The Host" ("The MC" in a battle: `FormatSpec.hostName`) and debaters after their model family ("Claude", "Gemini", "GPT-5.5", "Free
  Router"); two different models of one family get full titles, the same model twice gets
  letters ("Free Router A/B") — prompts and the judge's "Winner: <name>" need distinct names.
  Drafts and remixes re-derive the names from the models.
- The wizard keeps its in-progress state in `localStorage` (`debatr.wizard.v1`). Browser-only
  keys (`debatr.openrouter_key`, `debatr.elevenlabs_key`) live in `src/lib/localKeys.ts`
  (`useLocalKey`), are managed on the Account page (`ProviderKeys`, `?tab=keys`; the wizard only shows their
  status and links there in a new tab — the `storage` event syncs them back), and are
  sent as transient `user_provider_key` / `user_tts_key` (never in `config_json`, stripped from
  draft saves). The wizard's default model is `openrouter/free` (`FREE_ROUTER_ID`). With `user_tts_key` the API parks it in Redis (`debate:{id}:tts_key`) so
  `_auto_media` builds premium audio on the user's key without charging credits.
