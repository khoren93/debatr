# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`GET /api/health/full`** for an outside uptime monitor: besides the database and Redis it
  answers 503 when a queue (`default`, `background`, `media`) has no worker or the cron
  scheduler is gone, which the Telegram alerts cannot report since they run on those processes.

### Changed

- **Short-video highlights are picked by the debate's host model** (a Free Router host: the free
  model it pinned) instead of a fixed one: free debates cost nothing for it. The picks are kept
  per transcript, so rebuilding the audio with other voices asks the model nothing.
- **Free debates cost the operator nothing but their visual scenes**: when every participant
  argues on a free model, the verdict is structured and the gallery check answered by a free
  model (`FREE_VERDICT_MODEL`, a lever on the console's Settings page; `:free` models only), on
  the shared free-model quota like the turns. If it gives no answer, the regex verdict is used
  and the debate waits in the moderation queue.
- **`MEDIA_HIGHLIGHTS_MODEL` is now `VERDICT_MODEL`**: it only structures the judge's verdict and
  answers the hidden gallery check, which stay on a fixed model since the debate's author picks
  the host. The old name is still read.
- **CLI 0.2.1**: `debatr run` and the MCP tools refuse topics over 150 characters before asking
  the server (it draws the topic on the video); the leaderboard (`debatr leaderboard`, MCP
  `get_leaderboard`) shows models without audience votes as "no votes" instead of a 1000 rating;
  clearer `debatr resume --help`.

### Fixed

- **Paid models on the system key with an empty balance**: the estimate priced a model missing
  from the OpenRouter catalogue (`:nitro` / `:online` variants, models OpenRouter dropped) at $0
  and routers with a variable price (`openrouter/auto` and similar) below zero, so the balance
  check let such runs through. On the system key every model now needs a catalogue price (else
  400; without a catalogue only free models run), and variable-price routers are no longer
  listed. An own OpenRouter key still takes any model id. A model OpenRouter dropped now fails
  at once with a clear message instead of on the first turn.

## [1.2.0] - 2026-10-18

### Added

- **Topics from today's news**: the wizard's first step lists debate-ready questions drawn from
  the day's headlines (BBC, The Guardian, NPR, The New York Times, Al Jazeera, DW, Google News,
  Hacker News, Ars Technica, The Verge, ScienceDaily…), ranked by how hot a story is and how
  many outlets carry it, with search, categories and a link to the original article. The
  story's brief goes into every prompt, since the models do not know recent news. A new batch is
  built once a day, and a strict safety filter keeps tragedies, violence and sexual content out.
- **Visual scenes in the video**: while a speaker talks, the centre of the frame draws a scene
  that illustrates exactly what is being said — counting numbers, bar, line and pie charts,
  "1 in 4" pictogram grids, ticked-off points, pros vs cons, quotes, struck-through rebuttals,
  kinetic headlines, cause → effect chains and cycles, timelines and pictograms. Scenes are drawn
  stroke by stroke in a hand-drawn marker style and appear on the exact words thanks to the
  word timestamps. A cheap "visual director" model designs them per turn during the audio
  build; numbers that the speaker did not say are rejected. On by default, switchable in the
  wizard and in the audio dialog.
- **More scene types**: a balance that tips towards the heavier arguments, a 2×2 matrix, Venn
  diagrams, top lists and pyramids, dictionary cards for key terms and a world map that fills
  in and circles the countries a speaker names. The director's prompt now shows an example
  per type and which type fits which content.
- **Judge's scoreboard**: when the judge announces the result, the stage shows the debaters
  side by side and crowns the winner (or stamps a draw), built from the structured verdict
  without another model call.
- **Sketches and pictures**: the director can ask for a hand-drawn illustration of an object or
  metaphor (an illustrator model draws it as SVG; the server keeps only plain line data, which
  the video inks in stroke by stroke) and, if you choose so, a picture of a real place or thing:
  a freely licensed photo from Wikimedia Commons with its author and licence, or an AI image
  paid from your balance. A vision model checks every picture before it is used.
- **Live scenes**: scenes are designed right after every turn and appear under the text while
  the debate runs (click one to replay it); the audio build reuses them.
- **Debaters direct the visuals**: with visual scenes on, debaters may ask for a visual
  (`[visual: …]`) and challenge one of their opponent's on-screen figures
  (`[dispute N: …]`); the markers are neither voiced nor shown, and a challenged scene carries a
  "disputed by …" stamp.
- **Fact-check** (wizard switch, paid like the debate): a web search checks the figures and
  quotes on screen — verified, disputed or unverified, with sources. Opponents see the results,
  the judge weighs them, and the model leaderboard shows each model's accuracy.
- **`debatr` command-line tool** (`cli/`, `uv tool install debatr`): sign in by approving your
  computer in the browser (`debatr login`), then run a debate with one command and watch the
  turns stream into the terminal, with the judge's verdict at the end. Also `watch`, `show`
  (Markdown / JSON export), `list`, `stop`, `publish`, `audio` (MP3 download), `models`,
  `gallery` and `leaderboard`; `--json` everywhere for scripts. Paid runs are estimated first
  and need a confirmation or `--yes` / `--max-cost`.
- **MCP server for AI agents** (`debatr mcp`): Claude, Cursor and other MCP clients can start a
  debate, wait for it with progress per turn and read the verdict and transcript, browse the
  gallery and the model leaderboard. A per-debate cost cap (`DEBATR_MAX_COST_USD`) applies.
- **API tokens** (Account → API tokens): personal tokens for the CLI, scripts and agents, each
  with an optional spending limit and expiry, shown once and revocable at any time. A token can
  run and manage debates but never change the password, stored keys or payments, or create
  other tokens. Debates started with a token are private unless the request publishes them.
- **Resume a failed debate**: when a model fails to answer, the debate stops and its owner can
  resume it (Resume in the error banner, `POST /api/debates/{id}/resume`, and in CLI 0.2.0
  `debatr resume DEBATE` and the `resume_debate` MCP tool). The failed turn runs again with the
  same models, the turns before it stay, and only the turns that are left are checked against
  the balance and charged.
- **YouTube publish kit**: the export panel writes a title, a description with chapters and tags,
  and draws thumbnails for the video.

### Changed

- **Three-step creation wizard**: the topic (or a story from today's news), the speakers (one row
  each: model, voice with a preview, persona), then format and launch with the estimate.
  Speakers are named after their models ("Claude" vs "Gemini", "Free Router A / B") instead of
  typed names, so prompts and the judge always tell them apart.
- **Redesigned debate page**: the video plays in a player with its own controls and a seek bar
  split by turns, a click on a transcript row jumps to that turn, a toolbar holds like, share,
  remix and export, exports (MP4 rendered in the browser, MP3, the YouTube kit) open in a side
  panel, and a Details tab shows the lineup and the facts. The separate Audio tab is gone.
- **Provider keys on the Account page** (`?tab=keys`): the wizard shows whether your OpenRouter
  and ElevenLabs keys are set and links there.

- **A failed turn stops the debate** instead of letting the others argue against a speaker who
  said nothing (and the judge score it). An empty answer now counts as a failure too.
- **Free Router keeps its model**: OpenRouter's free router picks a random free model for every
  request; a Free Router speaker now keeps the model of its first real answer for the whole
  debate, so the lineup, the video and the leaderboard show the actual model (remixes still ask
  the router). If that model is busy, the router answers that one turn. When the router picks
  a model that cannot debate (a safety classifier answering "User Safety: safe") or writes only
  a few words, it is asked again before the turn is saved, so such answers never reach the
  debate.
- **Shorter verdicts**: the judge now gets a word budget that follows the turn length (about 70
  words after "very short" turns up to 260 after "long" ones, a little more with more debaters)
  and a compact format: the winner and what decided it, then one short paragraph per debater.
  Before, a verdict ran to 250–480 words even after 50-word turns and could take half of the
  episode. Estimates use the same budget.
- **New video layout**: the host sits on top, debaters in side columns (up to 2 + 2), the
  visual stage in the centre and captions below; the topic is shown big at the start and then
  stays as a small chip in the corner. The Short gets the same stage between the debaters and
  the captions.
- **Redesigned Account page** with tabs (Overview, API keys, Billing, Security; `?tab=` links):
  a balance panel with a low-balance warning, top-up amounts with "~N debates" and this month's
  spending; tokens, voice minutes and renders with a bar per day; recent activity with what each
  charge paid for (model tokens, premium voices, AI pictures); one card per provider key; the
  full ledger grouped by day with paging and a CSV export (`GET /api/billing/transactions.csv`);
  password and session settings. `/api/billing/usage` now returns per-day buckets and ledger
  rows carry a `category` and a clean `title`.
- **Several debates at once**: debate turns run on several workers (`TURN_WORKERS`, 4 in
  Docker), so a slow model or a long turn no longer makes everyone else wait. Each user may have
  two debates and two audio builds going at a time (`MAX_ACTIVE_DEBATES_PER_USER`,
  `MAX_ACTIVE_MEDIA_PER_USER`); trending topics run on a background queue after any waiting turn.
- **Rate limits are waited out**: a model that answers "rate limited" or with a server error is
  asked again (after 3 s and 10 s) before the turn fails, and free models on the shared system
  key wait for a slot of OpenRouter's per-minute limit instead of failing.
- **Dependencies updated** to their latest releases (backend and frontend).

### Fixed

- **Video export in Safari**: the MP4 export froze after the first frame in Safari (and every
  browser on iOS), because WebKit's encoder held the frames back; it now renders like in Chrome.
  Colour provider logos (NVIDIA, Cohere, Poolside…) were drawn zoomed and cropped in Safari's
  exports and are now painted correctly everywhere.
- **Interrupted runs continue**: a debate or audio build whose worker was killed (deploy, crash)
  is found within a few minutes and continues from where it stopped; deploys let the running
  turn finish first. Runs that cannot continue fail with a message (Resume / generate again)
  instead of staying "running" forever.
- **Debates no longer hang on a stuck model**: a turn now gets at most `LLM_TURN_TIMEOUT` (300 s)
  to answer. Before, keep-alive messages and long reasoning kept the connection open until the
  10-minute job limit killed the whole debate.
- **720p video export**: the "720p · faster" quality rendered at 1281×721, which the browser's
  H.264 encoder rejects, so the export failed; it now renders at exactly 1280×720.

## [1.1.0] - 2026-10-16

AI Debates becomes **Debatr**: a redesigned studio that takes a debate from a live stream to a
voiced video you can share.

### Added

- **Studio UI** based on the Debatr design: dark theme, sidebar and mobile navigation, Landing,
  Library, Gallery, Leaderboard, Account, Login and Register pages.
- **Creation wizard** in four steps (topic, speakers, voices & format, review) with a cost and
  length estimate before the start, drafts, remixes of existing debates, persona presets and
  in-progress state kept in the browser.
- **Model picker**: searchable OpenRouter catalogue with provider logos, prices, leaderboard rank
  and a "Latest" filter; `openrouter/free` as the default model.
- **AI judge verdict** structured into a winner (or a draw), a headline and feedback for every
  debater.
- **Spoken output style**: plain spoken prose with optional `[emotion]` tags for ElevenLabs v3.
- **Audio pipeline** on a dedicated media worker: premium ElevenLabs voices (word timestamps,
  forced-alignment fallback) or free Edge voices, loudness normalization with ffmpeg, a full MP3
  of the debate and a karaoke-style transcript player.
- **Video rendering in the browser** with Remotion: a 16:9 episode and a 9:16 Short cut around
  highlights picked by an LLM.
- **Accounts**: registration and login with session cookies, per-user debate library.
- **Credits and payments**: prepaid balance with an append-only ledger, Stripe Checkout top-ups
  (webhook and redirect confirmation), monthly usage stats, `DEV_FAKE_PAYMENTS` for development.
- **Own keys**: personal OpenRouter key stored encrypted on the account, or browser-only
  OpenRouter and ElevenLabs keys that run debates and voices at your own cost.
- **Public gallery** with share links (`/d/:slug`), Trending / New / Top sorting by week, month,
  year or all time, and a filter by model.
- **Auto-publish with AI moderation**: finished debates go public after a hidden content check;
  flagged ones wait for an admin to approve or reject them.
- **Likes and blind audience votes**: viewers pick the winner before they see the judge's call.
- **Model leaderboard**: Bradley–Terry ratings on an Elo-like scale built from audience votes.
- **Stop button** for running debates.
- **Admin panel** views for users, credit transactions, likes and votes, plus moderation actions.
- Rate limits for debate creation and login.
- `Makefile` shortcuts for Docker, native development, checks and deployment; `deploy.sh` for
  the production server.
- CI with GitHub Actions (ruff, pyright, pytest, tsc, eslint, build) and a backend test suite.

### Changed

- Renamed the product to **Debatr** and the repository to `khoren93/debatr`.
- Backend moved to Python 3.12 with uv, async SQLAlchemy 2 and Alembic migrations that run on
  API start; the worker chains RQ jobs per turn, verdict and finish.
- Frontend moved to React 19, Vite 8, Tailwind CSS 4 and strict TypeScript.
- Debate history and live pages replaced by the Library and the debate page with player,
  transcript, verdict, audio and export tabs.
- Browser `speechSynthesis` playback replaced by the server-side audio pipeline.
- Docker Compose now runs Postgres, Redis, API, a debate worker, a media worker and a
  Caddy-served frontend; `DATABASE_URL` and `REDIS_URL` are injected by Compose.

### Removed

- `requirements.txt` (dependencies now live in `backend/pyproject.toml` / `uv.lock`).

## [1.0.0] - 2026-01-12

First public release of **AI Debates**.

### Added

- Structured debates between LLMs via OpenRouter: a moderator guides opening statements,
  rebuttals and closing arguments, and an AI judge gives a final verdict.
- Custom participants with a model, persona, stance, avatar and voice.
- Debate settings for language and response length, topic templates and style presets.
- Model list with free/paid grouping, prices, context length, model validation and the
  OpenRouter credit balance.
- Real-time token streaming over Server-Sent Events, with errors shown per turn.
- Read-aloud of debates with the browser's speech synthesis.
- Debate history with delete and Markdown export.
- Admin panel for debates, participants, turns and sessions.
- Docker Compose setup with FastAPI, PostgreSQL, Redis + RQ and a React + Vite frontend.

[Unreleased]: https://github.com/khoren93/debatr/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/khoren93/debatr/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/khoren93/debatr/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/khoren93/debatr/releases/tag/v1.0.0
