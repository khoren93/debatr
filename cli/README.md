# debatr

**Run AI debates from your terminal, and give AI agents a debate tool over MCP.**

`debatr` is the command-line client for [Debatr](https://ai-debates.net), the AI debate studio:
pick a question and the models, watch them argue live in your terminal and get the judge's
verdict. The same package is an [MCP](https://modelcontextprotocol.io) server, so Claude, Cursor
and other agents can stage a debate to stress-test a decision or see both sides of a question.

```text
$ debatr run "Should cities ban cars from their centres?" -d anthropic/claude-sonnet-4.5 -d openai/gpt-5

● The Host  HOST · openrouter/free
Welcome! Today two models take on car-free city centres…

● Nova  PRO · anthropic/claude-sonnet-4.5
Cities belong to people, not parked metal…

● Atlas  CON · openai/gpt-5
A ban hits the people with the fewest alternatives first…

╭─ ⚖ The judge's verdict ─────────────────────────────╮
│ Winner: Nova                                        │
│ Nova grounded every claim in what cities measured.  │
╰─────────────────────────────────────────────────────╯
✓ Completed  ·  7 turns  ·  provider cost $0.0213
```

## Install

```bash
uv tool install debatr        # or: pipx install debatr
debatr --help
```

No install needed for a one-off: `uvx debatr run "Tabs or spaces?"`. Python 3.10+ is required
(uv fetches one if you have none).

## Sign in

```bash
debatr login
```

This opens Debatr in your browser and asks you to confirm a code (like `gh auth login`). You can
give this computer a spending limit there. The token is saved in `~/.config/debatr/config.json`
(readable only by you) and can be revoked at any time under **Account → API tokens** on the
website, or with `debatr logout`.

For CI and scripts, create a token under **Account → API tokens** and pass it in the
environment:

```bash
export DEBATR_TOKEN=debatr_…
debatr whoami
```

A token acts as you for debates and spending, but can never change your password, keys or
payments, or create other tokens.

## Run a debate

```bash
debatr run "Is remote work better for juniors?"                 # two free models
debatr run "Nuclear or renewables?" \
  -d anthropic/claude-sonnet-4.5 -n Ada -s "A nuclear engineer" \
  -d google/gemini-2.5-pro -n Ben -s "A grid operator who favours renewables" \
  --rounds 3 --length medium
debatr run "Should we rewrite it in Rust?" --context "A 40k-line Go service, team of 4" --json
debatr run "Tabs or spaces?" --format rap_battle --rounds 2 --length short   # verses only
debatr run "Tabs or spaces?" --format rap_battle --audio --flow smooth --flow fierce
```

| Option | What it does |
|---|---|
| `-d, --debater MODEL` | A debater's model; repeat for each (1–7). Default: `openrouter/free` twice. |
| `-n, --name` / `-s, --stance` | Names and personas, in the order of `-d`. By default the first argues for, the second against. |
| `--host MODEL` / `--no-host` | The host opens each round and judges (default `openrouter/free`). |
| `-r, --rounds`, `-l, --length` | 1–10 rounds; turns `very_short`, `short`, `medium` or `long`. |
| `--language`, `--intensity`, `--style` | Debate language, 1 calm … 10 fierce, `markdown` or `spoken`. |
| `-c, --context TEXT` | Background the speakers should know. |
| `--scenes`, `--fact-check` | Design charts and schemes for the web page; web fact-check of the figures (paid). |
| `--audio`, `--voices` | Voice it when done (free `edge` voices or premium `elevenlabs`). |
| `--format rap_battle`, `--flow FLOW` | A rap battle: an MC and two rappers trade verses (4/8/12/16 lines by `--length`), 1–3 rounds, the judge scores each round. With `--audio` ElevenLabs makes one track of beat and verses (paid); `--flow` sets how each rapper sounds (`debatr formats`). |
| `--public` | Publish to the gallery when finished (after an automatic content check). Private by default. |
| `-y, --yes`, `--max-cost USD` | Start paid runs without a prompt; refuse runs estimated above a limit. |
| `--detach`, `--json` | Print the id and return at once; or no live output, a JSON result at the end. |
| `--config FILE`, `--print-config` | Use a full request body; print the one the options make. |

Every run is estimated first. Free models cost nothing; paid models are charged to your Debatr
credits (or to your own OpenRouter key: set `DEBATR_OPENROUTER_KEY`). Without a terminal (CI,
agents), a paid run needs `--yes` or `--max-cost`. Press Ctrl+C to stop following a debate: you
are asked whether to stop it on the server too.

## More commands

| Command | What it does |
|---|---|
| `debatr models [WORDS] [--free]` | Models you can cast, newest first, with prices per million tokens. |
| `debatr watch DEBATE` | Follow a running debate live, or replay a finished one. |
| `debatr show DEBATE [-f text\|markdown\|json] [-o FILE]` | Transcript and verdict; export as Markdown or JSON. |
| `debatr list [WORDS] [--status S]` | Your debates. |
| `debatr resume DEBATE [--yes] [--max-cost USD]` | A debate stopped because a model failed: run that turn again and go on. |
| `debatr stop` / `delete` / `publish` / `unpublish DEBATE` | Manage a debate. |
| `debatr open DEBATE` | Open it in the browser: player, audience vote, video export. |
| `debatr audio DEBATE [--build] [-o FILE]` | Download the voiced debate as MP3 (`--build` voices it first). |
| `debatr formats` | Show formats (debate, rap battle) and the rappers' flows. |
| `debatr gallery [WORDS] [--sort trending\|new\|top] [--format F]` | Browse public debates and rap battles. |
| `debatr leaderboard [--free] [--format F]` | Models ranked by audience votes: best debaters, or best rappers. |
| `debatr whoami` / `logout` | The account, balance and token; sign out and revoke the token. |

`DEBATE` is an id, a link (`…/debate/<id>`, `…/d/<slug>`) or a share slug. Commands that print
data accept `--json`. Exit codes: `0` success, `1` an error or a debate that did not complete,
`130` interrupted.

## For AI agents (MCP)

`debatr mcp` runs an MCP server on stdio. Sign in once with `debatr login` (or pass
`DEBATR_TOKEN`), then add it to your agent:

**Claude Code**

```bash
claude mcp add debatr --scope user -- uvx debatr mcp
```

**Claude Desktop, Cursor, Windsurf and other clients** (`mcpServers` in their config file):

```json
{
  "mcpServers": {
    "debatr": {
      "command": "uvx",
      "args": ["debatr", "mcp"],
      "env": { "DEBATR_MAX_COST_USD": "0.50" }
    }
  }
}
```

Desktop apps do not always see your shell's `PATH`: if `uvx` is not found, use its full path
(`which uvx`). Add `"DEBATR_TOKEN": "debatr_…"` to `env` to use a dedicated token instead of
your `debatr login`.

| Tool | What it does |
|---|---|
| `start_debate` | Starts a debate (or a rap battle: `format="rap_battle"`) and returns its id at once (a debate takes 1–5 minutes). |
| `get_debate` | Status, progress, verdict and transcript; `wait_seconds` waits for the end and reports progress per turn. |
| `estimate_debate` | Price and length before starting. |
| `list_models`, `list_formats`, `get_leaderboard` | Models to cast, show formats and flows, and how audiences rank the models. |
| `list_my_debates`, `search_gallery` | The user's debates; public debates to read. |
| `resume_debate` | Runs a debate that stopped with an error again from the failed turn (within the cost limit). |
| `stop_debate`, `publish_debate`, `get_account` | Manage a debate; balance and the token's limit. |

Agents spend your credits only within two limits: the token's own spending limit (set it when
you approve `debatr login` or create the token) and `DEBATR_MAX_COST_USD`, the most one debate
may cost through this server (default `1.00`). Debates started by agents are private unless they
ask to publish them.

## Configuration

| Variable | Meaning |
|---|---|
| `DEBATR_URL` | Server to use (default: the one you signed in to, else `https://ai-debates.net`). Same as `--url`. |
| `DEBATR_TOKEN` | API token; takes precedence over `debatr login`. |
| `DEBATR_OPENROUTER_KEY` | Your OpenRouter key: models run on your account instead of your credits. Never stored by Debatr. |
| `DEBATR_ELEVENLABS_KEY` | Your ElevenLabs key for `--voices elevenlabs`. |
| `DEBATR_MAX_COST_USD` | MCP server: the most one debate may cost (default `1.00`). |
| `DEBATR_CONFIG_DIR` | Where logins are saved (default `~/.config/debatr`, `%APPDATA%\debatr` on Windows). |

**Self-hosted Debatr**: point the CLI at your server with `--url` (or `DEBATR_URL`), e.g.
`debatr --url http://localhost login`. Logins are kept per server.

## Development

The package lives in the [`cli/`](https://github.com/khoren93/debatr/tree/main/cli) folder of the
Debatr repository and only uses the public REST API (`/api/docs` on any Debatr server).

```bash
cd cli
uv sync
uv run debatr --url http://localhost --help
uv run pytest -q && uv run ruff check . && uv run pyright
```

Releases are published to PyPI by GitHub Actions when a `cli-vX.Y.Z` tag is pushed (the version
lives in `src/debatr/__init__.py`).

## License

MIT
