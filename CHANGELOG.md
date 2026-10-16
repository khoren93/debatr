# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Visual scenes in the video**: while a speaker talks, the centre of the frame draws a scene
  that illustrates exactly what is being said — counting numbers, bar, line and pie charts,
  "1 in 4" pictogram grids, ticked-off points, pros vs cons, quotes, struck-through rebuttals,
  kinetic headlines, cause → effect chains and cycles, timelines and pictograms. Scenes are drawn
  stroke by stroke in a hand-drawn marker style and appear on the exact words thanks to the
  word timestamps. A cheap "visual director" model designs them per turn during the audio
  build; numbers that the speaker did not say are rejected. On by default, switchable in the
  wizard and in the audio dialog.

### Changed

- **New video layout**: the host sits on top, debaters in side columns (up to 2 + 2), the
  visual stage in the centre and captions below; the topic is shown big at the start and then
  stays as a small chip in the corner. The Short gets the same stage between the debaters and
  the captions.

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

[Unreleased]: https://github.com/khoren93/debatr/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/khoren93/debatr/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/khoren93/debatr/releases/tag/v1.0.0
