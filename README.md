# 🤖 AI Debates · Debatr

> **Two AIs. One topic. A video in minutes.**

![Project Status](https://img.shields.io/badge/status-active-success.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Docker](https://img.shields.io/badge/docker-ready-blue.svg)
![VS Code](https://img.shields.io/badge/Made%20in-VS%20Code-0078d7.svg?style=flat&logo=visual-studio-code&logoColor=white)

**Debatr** (the AI Debates studio) is a full-stack service that orchestrates structured debates between AI personas and turns them into content. Powered by **OpenRouter**, it lets you pit **hundreds of LLMs** against each other with custom roles, personalities and stances, watch the debate stream live, get a judge's verdict, and render a **16:9 YouTube video plus a 9:16 Short** right in the browser.

Users sign up, run free models or bring their own OpenRouter key, buy credits with **Stripe**, keep a library of their debates and can publish them to a **public gallery** with share links.

> **🚀 Try it live: [ai-debates.net](https://ai-debates.net)**

![App Demo](https://github.com/user-attachments/assets/54c6768d-8b00-43a9-baa7-1312c8dc01a4)

---

## ✨ Key Features

### 🎬 Stage any debate
- **⚔️ Any model vs any model**: pick from hundreds of LLMs on OpenRouter. Have **Claude** take
  on **GPT** while **Gemini** moderates, with a persona, a stance and a voice for every speaker.
  Or let OpenRouter's free router pick free models: each speaker keeps the model it got, and the
  video and the leaderboard show which one argued.
- **📰 Topics from today's news**: debate-ready questions drawn from the day's headlines across
  major outlets, each with a short brief of what happened and links to the original articles,
  one click away in the wizard.
- **🧭 Ready in three steps**: a topic, the speakers (model, voice and persona), then format and
  launch with the exact cost and length before you hit start.
- **⚡ Watch it live**: arguments stream in word by word, and you can stop the debate at any moment.
  If a model fails to answer, the debate stops on that turn and resumes from there with one click.

### ⚖️ Who won?
- **🧑‍⚖️ AI judge**: a verdict with the winner (or a draw), a headline and feedback for every
  debater.
- **🗳️ Blind audience vote**: viewers pick who argued better *before* they see the judge's call,
  so you can find out whether people agree with the AI.
- **📊 Model leaderboard**: an Elo-style ranking of models built from audience votes, with a
  free/paid filter. Find out which model really wins arguments.

### 🎙️ From transcript to video
- **🔊 Neural voices**: premium ElevenLabs voices with emotion tags, or free Edge voices, with a
  karaoke-style transcript and an MP3 of the whole debate.
- **📹 YouTube video and a Short in minutes**: a 16:9 episode plus a 9:16 Short cut around the
  strongest moments, rendered right in your browser.
- **✏️ Visual scenes**: charts, maps, balances, matrices, Venn diagrams, top lists, schemes,
  hand-drawn sketches and photos appear next to every turn while the debate runs and in the
  video exactly when a speaker mentions them — only with numbers the speaker actually said — and
  the judge's scoreboard crowns the winner. Debaters can ask for visuals and challenge each
  other's figures on screen.
- **🔎 Fact-check**: a web search checks the figures and quotes on screen, the opponents and the
  judge see the result, and the leaderboard shows how accurate each model's figures are.
- **📝 Transcript export**: take the full debate with you as Markdown.

### 🌍 Share and discover
- **🖼️ Public gallery**: finished debates go public with their own share link after an automatic
  content check (or stay private if you prefer). Browse Trending, New and Top debates of the week,
  month or year.
- **❤️ Likes and remixes**: like the debates you enjoy, or remix any of them into your own version
  with a new cast.
- **👤 Your studio**: a library of drafts and finished debates, credits topped up via Stripe, or
  your own OpenRouter key to run models at your own cost.

### 🤖 From the terminal and for AI agents
- **⌨️ `debatr` CLI**: `uv tool install debatr`, approve your computer in the browser once and run
  a debate with one command. The turns stream into your terminal; `--json` makes it scriptable,
  transcripts and audio export from there too, and `debatr resume` picks up a failed debate.
- **🔌 MCP server**: give Claude, Cursor and other agents a debate tool (`debatr mcp`). They can
  stage a debate between any models to stress-test a decision or see both sides of a question,
  then read the verdict.
- **🔑 API tokens**: one per device or agent, each with an optional spending limit and expiry,
  revocable at any time. A token runs debates but can never touch your password, keys or payments.

### 🐳 Self-host it
- One `docker compose up`: Postgres, Redis, API, workers and a Caddy-served frontend.

## 🗺️ Roadmap

### 🔜 Coming next

- [ ] **🧑‍⚖️ Human vs AI**: step into the arena yourself. Argue against a model of your choice, turn
  by turn, and let the judge decide who made the stronger case.
- [ ] **🎭 New formats**: beyond the classic debate: rap battles, roasts, courtroom trials with a
  prosecutor, defence and jury, Shark Tank pitches, Socratic dialogues and podcast interviews.
- [ ] **🏛️ Historical & fictional characters**: Socrates vs Nietzsche, Sherlock vs Poirot. Cast
  famous minds from history and fiction as your speakers, each with their own voice and style.
- [ ] **🏆 Tournaments**: knockout brackets of 4–8 models on one question. Every match is a
  full debate, and the champion climbs the model leaderboard.
- [ ] **📅 Debate of the day**: a fresh debate on a topical question every day, voiced and
  published to the gallery, ready for your vote.
- [ ] **🎞️ Animated avatars**: speakers that talk, react and lip-sync in the 16:9 episodes and
  9:16 Shorts.
- [ ] **🔗 Embeddable player**: drop any public debate into a blog post or article with a simple
  `<iframe>` or an oEmbed link.

### 🧩 Also planned

- [ ] **Comments**: discussion under public debates (owner can switch it on/off).
- [ ] **PDF Export**: Nicely formatted transcript downloads.
- [ ] **Local LLM Support**: Integration with Ollama for offline debates.

## 🛠️ Tech Stack

### Backend
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.12+, managed with [uv](https://docs.astral.sh/uv/))
- **Database**: PostgreSQL (async SQLAlchemy 2 + Alembic migrations)
- **Queue**: Redis & RQ (Redis Queue) for reliable task orchestration
- **AI Integration**: [OpenRouter](https://openrouter.ai/) API (streaming, token & cost accounting)
- **Voices & media**: ElevenLabs / edge-tts, ffmpeg mixing, timeline contract for the browser renderer
- **Accounts & payments**: session cookie login (bcrypt), encrypted personal keys (Fernet), Stripe Checkout + webhooks
- **Quality**: ruff, pyright, pytest

### Frontend
- **Framework**: [React 19](https://react.dev/) + [Vite 8](https://vite.dev/) + TypeScript
- **Styling**: Tailwind CSS 4 with the Debatr design tokens (dark studio theme)
- **State/Routing**: React Router, Axios
- **Streaming**: Server-Sent Events (SSE)
- **Video**: Remotion Player + `@remotion/web-renderer` (MP4 encoded in the visitor's browser)

### CLI and MCP server
- **Package**: [`debatr`](cli/README.md) (Python 3.10+, [Typer](https://typer.tiangolo.com/) +
  [Rich](https://rich.readthedocs.io/), httpx), installable with `uv tool install debatr`
- **Agents**: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (stdio server)
- **Auth**: personal API tokens (`Authorization: Bearer debatr_…`) and a browser device login

### DevOps
- **Containers**: Docker Compose (Postgres, Redis, API, debate workers, media worker, scheduler, Caddy)
- **CI**: GitHub Actions (lint, type-check, tests, build)

---

## 🚀 Getting Started

Follow these steps to get a copy up and running locally or on your server.

### 🐳 Quick start with Docker

1. **Clone the repository**
   ```bash
   git clone https://github.com/khoren93/debatr.git
   cd debatr
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   For local testing you only need to set `OPENROUTER_API_KEY`. Keep `DOMAIN_NAME=localhost`.
   Set `DEV_FAKE_PAYMENTS=true` to top up credits instantly without Stripe while developing.

3. **Run**
   ```bash
   make up        # = docker compose up -d --build
   ```
   Database migrations run automatically when the API container starts. `make logs s=api`
   follows a service's logs, `make down` stops everything.

4. **Open**
   - **Frontend**: [http://localhost](http://localhost)
   - **API docs**: [http://localhost/api/docs](http://localhost/api/docs)
   - **Admin panel**: [http://localhost/api/admin](http://localhost/api/admin) (`ADMIN_USER` / `ADMIN_PASSWORD`)

### 💻 Local development (hot reload)

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 20.19+ and Docker.

```bash
make install   # backend (uv sync) + frontend (npm install) dependencies
make dev-up    # infrastructure only: Postgres on :5432, Redis on :6379
make migrate   # apply database migrations

make api       # backend API with reload (http://localhost:8000/api/docs)
make worker    # second terminal: RQ worker for both queues (SimpleWorker, safe on macOS)
make web       # third terminal: Vite on http://localhost:5173, proxies /api to the backend
```

Leave `DATABASE_URL` and `REDIS_URL` unset in `.env`: the defaults point at localhost, and
`docker compose` injects the container addresses itself.

**Checks**

```bash
make check     # everything CI runs: ruff, format check, pyright, pytest, tsc, eslint, build
make test      # backend tests only
make format    # ruff autofix + format
```

### 🧰 Make commands

Run `make` to list every target. The most useful ones:

| Command | What it does |
|---|---|
| `make up` / `make down` | Start (with rebuild) / stop the full Docker stack |
| `make restart s=worker` | Rebuild and restart one service (all without `s=`) |
| `make logs s=api` / `make ps` | Follow logs / show container status |
| `make dev-up` / `make dev-down` | Postgres + Redis only, for native development |
| `make api` / `make worker` / `make web` | Run the API, worker and frontend with hot reload |
| `make migrate` / `make migration m="..."` | Apply migrations / autogenerate a new one |
| `make check` | Lint, type check, tests and frontend build |
| `make deploy` | On the server: pull `main` and rebuild the production stack (`deploy.sh`) |
| `make prod-logs s=worker` / `make prod-ps` | On the server: production logs / container status |

---

### 🌐 Server Deployment (Hetzner/VPS)

1. **Point your domain** (e.g., `example.com`) to your server IP in Cloudflare/DNS.
2. **SSH into your server** and install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. **Clone and Setup**:
   ```bash
   git clone https://github.com/khoren93/debatr.git
   cd debatr
   cp .env.example .env
   ```
4. **Edit `.env`**:
   - Set `DOMAIN_NAME=your-domain.com`
   - Set `ACME_EMAIL=your@email.com` (for SSL)
   - Set `OPENROUTER_API_KEY=...`
   - Generate a strong `POSTGRES_PASSWORD`.
5. **Start everything**:
   ```bash
   ./deploy.sh
   ```
   `deploy.sh` pulls the latest code, rebuilds the containers (migrations run on start) and
   prunes old images. In production set `ENVIRONMENT=production` and replace every placeholder
   secret in `.env` (`SECRET_KEY`, `ADMIN_PASSWORD`, `POSTGRES_PASSWORD`).
6. **Update later**: SSH into the server and run it again from the project dir (pushes do not
   deploy automatically):
   ```bash
   make deploy    # same as ./deploy.sh
   ```

---

## 📖 Usage

1. Open the web interface at `https://your-domain.com` (or `http://localhost`) and create an account
   (new accounts receive `SIGNUP_BONUS_USD` of credits, 0 by default).
2. Click **"+ New debate"** and walk through the wizard's three steps:
   - **Topic**: type a question or pick one of today's trending topics from the news, choose language, rounds and reply length.
   - **Speakers**: a host plus two or more debaters, each with a model (OpenRouter's free router by
     default), a voice and a persona. The voice engine is chosen here too: free Edge voices or premium
     ElevenLabs voices.
   - **Review**: spoken or written style, which outputs to produce (audio, 16:9 video, 9:16
     Short) and the render quality, visual scenes (pictures, fact-check) and whether to publish to
     the gallery; the estimate shows cost, length, turns and your credits after the run. Your own
     OpenRouter / ElevenLabs keys are managed on the Account page.
3. Hit **Start the debate** and watch it stream live. When it finishes the verdict is scored and the
   audio track is built automatically; open the debate to render the MP4s in your browser. If a model
   fails to answer, the debate stops on that turn: **Resume** runs it again and goes on.
4. **Share**: publish the debate to the gallery and copy the share link.
5. **Account**: top up credits (Stripe), see this month's usage, store a personal OpenRouter key so paid
   models run on your own account instead of credits.

### ⌨️ Terminal and AI agents

The [`debatr` CLI](cli/README.md) talks to any Debatr server over its public API:

```bash
uv tool install debatr
debatr login                                  # approve this computer in the browser
debatr run "Should cities ban cars?" -d anthropic/claude-sonnet-4.5 -d openai/gpt-5
debatr show <id> --format markdown -o debate.md
```

For AI agents, `debatr mcp` is an MCP server, e.g. for Claude Code:
`claude mcp add debatr --scope user -- uvx debatr mcp`. Agents start a debate, wait for it with
progress per turn and read the verdict. They spend credits only within the token's spending
limit and `DEBATR_MAX_COST_USD` per debate, and their debates stay private unless they publish.

Scripts and CI can use a token from **Account → API tokens** (`DEBATR_TOKEN`). For a self-hosted
server pass `--url http://localhost` (or set `DEBATR_URL`).

### 💳 Credits

- Every run charges the OpenRouter cost reported for the debate × `CREDIT_MARKUP` once it finishes
  (a resumed debate is charged only for what the new run adds).
- Premium voices on the system ElevenLabs key cost `TTS_CREDIT_PRICE_PER_1K_CHARS` per 1,000 characters.
- Free models and free Edge voices cost nothing; a personal OpenRouter key makes model usage free.
- Top-ups go through Stripe Checkout (`STRIPE_SECRET_KEY`, webhook `/api/billing/webhook` with the
  `checkout.session.completed` event and `STRIPE_WEBHOOK_SECRET`). Every movement is recorded in the
  `credit_transactions` ledger and visible on the Account page and in the admin panel.

---

## 🏗️ Architecture Overview

The system uses an event-driven architecture to handle long-running LLM generation tasks without blocking the UI.

1. **API Layer**: `POST /api/debates` validates the configuration and saves the debate with status `queued`.
   A user-supplied OpenRouter key is kept only in Redis for the lifetime of the debate, never in the database.
2. **Queue (RQ)**: A chain of jobs per debate: `start` → one job per turn → `verdict` → `finish`.
   Several workers (`TURN_WORKERS`) serve the queue, so debates run side by side; each user may have
   two going at once, and a run whose worker died is picked up again by a recovery check every minute.
3. **Scheduler**: Every round starts with the moderator (introduction, then short transitions) followed by
   each debater. Debater turns are typed `opening` / `rebuttal` / `closing`; the moderator's model then
   delivers a structured verdict.
4. **Worker**: Builds role-specific prompts, streams the OpenRouter response, records token usage and cost
   per turn, and publishes events to Redis Pub/Sub. A debate can be stopped at any time from the UI.
   Rate limits and provider errors are retried; a turn that still fails stops the debate, which the
   owner can resume from that turn (`POST /api/debates/{id}/resume`).
5. **Frontend**: Subscribes to `GET /api/debates/{id}/stream` (SSE) and renders turns token-by-token.
   Finished debates are served straight from the database.
6. **Verdict & billing**: after the judge's turn a cheap model structures the verdict (winner, headline,
   feedback). At the terminal state the worker charges the owner's credits and, if the wizard asked for
   media, queues the audio build on the `media` queue.
7. **Media**: the media worker voices every turn (cached by content hash), mixes the track with ffmpeg,
   picks highlights for Shorts and writes `timeline.json`. The browser renders MP4s from that timeline.
8. **Accounts**: the login lives in the signed session cookie; personal OpenRouter keys are stored
   encrypted and only ever handed to the worker through Redis for the duration of a run.
9. **API tokens**: the CLI, scripts and agents send `Authorization: Bearer debatr_…`. Only a
   SHA-256 hash is stored; `debatr login` gets its token through a device flow (a short code
   confirmed in the browser). Runs remember the token that started them, so its spending limit
   counts their charges; account settings and payments accept only the browser session.

**Configuration** (see `.env.example`): `OPENROUTER_API_KEY`, `ELEVENLABS_API_KEY`, `ALLOWED_ORIGINS`,
`SIGNUP_BONUS_USD`, `CREDIT_MARKUP`, `TTS_CREDIT_PRICE_PER_1K_CHARS`, `TOPUP_AMOUNTS_USD`,
`STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` (or `DEV_FAKE_PAYMENTS`), `DEBATE_CREATE_RATE_LIMIT`,
`LOGIN_RATE_LIMIT`, `TURN_JOB_TIMEOUT`, `LLM_TURN_TIMEOUT`, `TURN_WORKERS`,
`MAX_ACTIVE_DEBATES_PER_USER`, `MAX_ACTIVE_MEDIA_PER_USER`, `FREE_MODELS_PER_MINUTE`, `MEDIA_JOB_TIMEOUT`, `ADMIN_USER` / `ADMIN_PASSWORD`, `SECRET_KEY`.

---

## 🤝 Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

## 📬 Contact

Project Link: [https://github.com/khoren93/debatr](https://github.com/khoren93/debatr)
