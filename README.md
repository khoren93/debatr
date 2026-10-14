# 🤖 AI Debates · Debatr

> **Two AIs. One topic. A video in minutes.**

![Project Status](https://img.shields.io/badge/status-active-success.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Docker](https://img.shields.io/badge/docker-ready-blue.svg)
![VS Code](https://img.shields.io/badge/Made%20in-VS%20Code-0078d7.svg?style=flat&logo=visual-studio-code&logoColor=white)

**Debatr** (the AI Debates studio) is a full-stack service that orchestrates structured debates between AI personas and turns them into content. Powered by **OpenRouter**, it lets you pit **hundreds of LLMs** against each other with custom roles, personalities and stances, watch the debate stream live, get a judge's verdict, and render a **16:9 YouTube video plus a 9:16 Short** right in the browser.

Users sign up, run free models or bring their own OpenRouter key, buy credits with **Stripe**, keep a library of their debates and can publish them to a **public gallery** with share links.

> **🚀 Live Demo Version is Coming Soon!**

![App Demo](https://github.com/user-attachments/assets/54c6768d-8b00-43a9-baa7-1312c8dc01a4)

---

## ✨ Key Features

- **🧭 4-step wizard**: topic → speakers (model, neural voice, persona per speaker) → voice engine, outputs and quality → review with a cost/length estimate.
- **⚔️ LLM vs LLM**: Mix and match models. Have **Claude** debate **GPT** on philosophy while **Gemini** moderates.
- **⚡ Real-time streaming**: watch the debate generate token-by-token, stop it at any moment.
- **⚖️ Structured verdict**: the judge names a winner (or a draw), with per-debater feedback shown in the UI and on the video end card.
- **🎙️ Neural voices**: ElevenLabs (premium, emotion tags) or free Edge voices with word timestamps, mixed MP3 and karaoke transcript.
- **🎬 Video in the browser**: 16:9 episode and 9:16 Shorts (LLM-picked highlights with a hook) rendered with Remotion and WebCodecs — no server encoding.
- **👤 Accounts & credits**: email sign-up with optional welcome credits, Stripe top-ups, a ledger of every charge, an optional personal OpenRouter key that bypasses credits.
- **📚 Library & gallery**: drafts, filters, search; publish finished debates with a share link (`/d/{slug}`) and view counts.
- **🐳 Dockerized**: Postgres, Redis, API, workers and a Caddy-served frontend.

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

### DevOps
- **Containers**: Docker Compose (Postgres, Redis, API, worker, Caddy)
- **CI**: GitHub Actions (lint, type-check, tests, build)

---

## 🚀 Getting Started

Follow these steps to get a copy up and running locally or on your server.

### 🐳 Quick start with Docker

1. **Clone the repository**
   ```bash
   git clone https://github.com/khoren93/ai-debates.git
   cd ai-debates
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

1. **Point your domain** (e.g., `ai-debates.net`) to your server IP in Cloudflare/DNS.
2. **SSH into your server** and install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. **Clone and Setup**:
   ```bash
   git clone https://github.com/khoren93/ai-debates.git
   cd ai-debates
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
2. Click **"+ New debate"** and walk through the wizard:
   - **Topic**: type a question or pick one from the library, choose language, rounds and reply length.
   - **Speakers**: a host plus two or more debaters, each with a model, a neural voice and a persona.
   - **Voice & format**: spoken or written style, free Edge or premium ElevenLabs voices, which outputs
     to produce (audio, 16:9 video, 9:16 Short) and the render quality.
   - **Review**: the estimate shows cost, length, turns and your credits after the run.
3. Hit **Start the debate** and watch it stream live. When it finishes the verdict is scored and the
   audio track is built automatically; open the debate to render the MP4s in your browser.
4. **Share**: publish the debate to the gallery and copy the share link.
5. **Account**: top up credits (Stripe), see this month's usage, store a personal OpenRouter key so paid
   models run on your own account instead of credits.

### 💳 Credits

- Every run charges the OpenRouter cost reported for the debate × `CREDIT_MARKUP` once it finishes.
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
2. **Queue (RQ)**: A chain of jobs runs in the worker: `start` → one job per turn → `verdict` → `finish`.
3. **Scheduler**: Every round starts with the moderator (introduction, then short transitions) followed by
   each debater. Debater turns are typed `opening` / `rebuttal` / `closing`; the moderator's model then
   delivers a structured verdict.
4. **Worker**: Builds role-specific prompts, streams the OpenRouter response, records token usage and cost
   per turn, and publishes events to Redis Pub/Sub. A debate can be stopped at any time from the UI.
5. **Frontend**: Subscribes to `GET /api/debates/{id}/stream` (SSE) and renders turns token-by-token.
   Finished debates are served straight from the database.
6. **Verdict & billing**: after the judge's turn a cheap model structures the verdict (winner, headline,
   feedback). At the terminal state the worker charges the owner's credits and, if the wizard asked for
   media, queues the audio build on the `media` queue.
7. **Media**: the media worker voices every turn (cached by content hash), mixes the track with ffmpeg,
   picks highlights for Shorts and writes `timeline.json`. The browser renders MP4s from that timeline.
8. **Accounts**: the login lives in the signed session cookie; personal OpenRouter keys are stored
   encrypted and only ever handed to the worker through Redis for the duration of a run.

**Configuration** (see `.env.example`): `OPENROUTER_API_KEY`, `ELEVENLABS_API_KEY`, `ALLOWED_ORIGINS`,
`SIGNUP_BONUS_USD`, `CREDIT_MARKUP`, `TTS_CREDIT_PRICE_PER_1K_CHARS`, `TOPUP_AMOUNTS_USD`,
`STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` (or `DEV_FAKE_PAYMENTS`), `DEBATE_CREATE_RATE_LIMIT`,
`LOGIN_RATE_LIMIT`, `TURN_JOB_TIMEOUT`, `MEDIA_JOB_TIMEOUT`, `ADMIN_USER` / `ADMIN_PASSWORD`, `SECRET_KEY`.

---

## 🗺️ Roadmap

- [x] **Voice Synthesis (TTS)**: Browser text-to-speech playback.
- [x] **Neural TTS**: ElevenLabs / Edge voices with word timestamps, karaoke transcript and MP3 export.
- [x] **Video**: 16:9 debate video and 9:16 shorts rendered in the browser (Remotion).
- [ ] **User Voting**: Let the audience decide the winner.
- [x] **Export Transcripts**: Save debates as Markdown.
- [x] **Accounts & credits**: sign-up, Stripe top-ups, ledger, personal OpenRouter key.
- [x] **Public gallery**: publish debates with share links.
- [ ] **PDF Export**: Nicely formatted transcript downloads.
- [ ] **Multiplayer Mode**: Human vs AI debates.
- [ ] **Local LLM Support**: Integration with Ollama for offline debates.

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

Project Link: [https://github.com/khoren93/ai-debates](https://github.com/khoren93/ai-debates)
