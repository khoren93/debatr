# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Email confirmation and password reset.** A new account gets a link to confirm its email;
  "Forgot password?" on the sign-in page mails a link to set a new one (an hour, once; other
  devices are signed out). New accounts publish to the gallery and add credits once their email
  is confirmed: a debate finished or published before stays private and goes public with the
  confirmation. Accounts from before are only asked to confirm (Account → Security). Mail goes
  through an SMTP relay (`MAIL_SMTP_*`); without one the letters are only logged.
- **Mail in the admin console.** A Mail page lists every letter the site sent or tried to send
  (address, subject, kind; never the text) with what the relay answered or why it refused, plus
  the relay's settings and a "Send a test letter" button; an account's card shows its letters.
  With the sending service's webhook (`POST /api/mail/events`, `MAIL_WEBHOOK_SECRET`; Resend's
  signed events) each letter also shows whether it was delivered, bounced or marked as spam. A
  refused or bounced letter, or production without a relay, raises the "Mail not delivered"
  alert and an item on the overview. Letters are kept `MAIL_LOG_DAYS` (90) days.
- Mail goes out on port 587 (STARTTLS) by default instead of 465: hosts such as Hetzner Cloud
  drop outgoing 25 and 465, so every letter timed out. A relay that cannot be reached says where
  and, for a timeout on 25 / 465, to set `MAIL_SMTP_PORT=587`.

- **The site's own account.** `python -m app.manage official EMAIL --name Debatr` makes an
  account the site's: its debates show the Debatr logo as the author's avatar and a check mark
  next to the name (gallery, home page, topic pages, the debate page). Other accounts cannot take
  the brand's name, in any spelling.
- The home page says the project is open source: a GitHub link in the hero's facts, a "Built in
  the open" block, and a link under the sidebar on every page.
- The home page mentions rap battles (the label above the headline, the description, a link to
  the battles in the gallery) and hangs a battle's stage lights over the hero (still for visitors
  who ask for less motion).
- **The home page plays the most popular debate.** The hero shows the gallery's top trending
  English debate with its video and plays it in place (the player loads on hover or the first
  click); without one it keeps the static poster.
- Admin console: each visit is marked as a person, a bot or an AI agent, with the reasons; the
  Audience page leaves bots out of its numbers unless "Include bots" is on.
  `python -m app.manage audience classify` marks the visits from before.

### Changed

- The top-up card counts debates at today's prices: about how many typical debates on top models
  each amount buys, and how many with premium voices (`GET /api/billing/config` answers
  `debate_usd` and `voiced_debate_usd`). It used to promise more, leaving the voices out.
- Gallery cards no longer show the debate's language (the language filter stays).
- Contact: the server's `SUPPORT_EMAIL` on the privacy page (a GitHub issue without one) and a
  "Contact" link under the sidebar; it is also the Reply-To of the site's mail unless
  `MAIL_REPLY_TO` is set. No address is built into the code any more: `MAIL_FROM` and
  `SUPPORT_EMAIL` come from the server's .env.
- The home page lists English debates only.
- The server calls itself Debatr instead of AI Debates: the API docs' title, the Stripe product
  ("Debatr credits"), CSV exports (`debatr-ledger-….csv` and the console's), the app name sent to
  OpenRouter, the backend and frontend package names.
- Database backups are named `debatr-<stamp>.dump`; older `ai_debates-*` dumps are still pruned
  and checked.
- Docker: the external proxy reaches the site by the `caddy_net` alias `debatr-frontend`
  (`reverse_proxy debatr-frontend:80`) instead of a fixed container name; `ai-debates-frontend-1`
  stays an alias until the proxy is switched.

## [1.9.0] - 2026-10-21

### Added

- **Gallery by language.** The gallery shows English debates by default; a language dropdown
  switches to another language (only the languages with debates, with their counts) or to all of
  them (`?lang=ru`, `?lang=all`). The API takes `language=<code>` and answers how many cards each
  language has.
- Gallery cards show the debate's language.
- Admin console: an Audience page with visit statistics.
- A privacy page (`/privacy`).
- **CLI 0.6.0**: `debatr gallery --language ru` and the MCP `search_gallery` tool's `language`;
  the gallery table shows each debate's language.

### Changed

- The gallery's filters take less room: the format and premium voices on the left, the order
  (trending, new, top this week … of all time, one dropdown) and the language on the right,
  smaller category chips under them; two compact rows on phones.

## [1.8.1] - 2026-10-21

### Fixed

- **A drawn battle crowned a winner in the video.** When the judge scored 15:15 and called a
  draw, the video's scoreboard and last card still named the rapper the judge mentioned first.
  The video now follows the judge's verdict, draws included; `refresh-timeline` fixes videos
  built before.

## [1.8.0] - 2026-10-21

### Added

- **Rap battle videos come alive.** The verse being rapped takes the middle of the frame line by
  line, word by word on the track, rhymes underlined; club lights in the rappers' colours swing
  and flash on the beat; "ROUND 1" and "ROUND 2" slam in on a kick; a punchline pushes the camera
  in, then flashes, shakes the frame and makes the other rapper flinch, and the crowd reacts
  ("ooh", an eruption for the round's best, a roar as the winner is crowned). A battle's Short
  starts with the beat and ends on a punchline.
- **Livelier debates too.** The background drifts and turns to the speaker's colour, the camera
  breathes, the speaking logo moves with the voice, round 2 and later get a card, and the
  sharpest lines (zingers) stay highlighted in the captions. A studio audience can react as
  well: "Crowd reactions" in the wizard and the regenerate dialog (off by default for debates,
  on for battles).
- `python -m app.manage media refresh-timeline <ids> | --format rap_battle`: brings finished
  videos up to date (the beat, the lines that land, the Shorts) without rebuilding the audio.

### Changed

- The host model that picks the Shorts also marks the lines that land (one call, as before), in
  the style of the show: a battle's punchlines, a debate's zingers.

## [1.7.0] - 2026-10-21

### Changed

- **New address: debatr.tv.** The site moves from ai-debates.net to debatr.tv; every old link
  (debates, topics, the gallery, embedded players) leads to the same page on the new domain. You
  need to sign in once more there, and keys you kept in the browser (OpenRouter, ElevenLabs) have
  to be entered again on the Account page: browsers keep them per site.
- **CLI 0.5.0**: talks to https://debatr.tv by default; `--url ai-debates.net` and logins saved
  for it by older versions mean the new address. Older versions keep working against the old
  address.

### Added

- `python -m app.manage indexnow --all [--dry-run]`: announces every page of the sitemaps to
  IndexNow at once, for a move to a new domain.
- `SITE_ALIASES`: former hosts of the site; links to them still count as the site's own (oEmbed
  answers for them, views from them are internal).

## [1.6.1] - 2026-10-21

### Fixed

- **Rap battle topics**: the safety review dropped most of them (9 of 20 were left), often only
  because the story behind "Office or remote work?" or "Handheld or console?" mentioned layoffs or
  a lawsuit. The writer now knows who may be a side (no politicians or groups of people) and the
  review judges the sides, not the news story around them: 20 of 20 in a test run.

## [1.6.0] - 2026-10-20

### Added

- **Rap battle topics from the news**: the wizard shows rap battles their own trending list,
  rivalries like "Ronaldo or Messi?" or "Office or remote work?" made from the same news as the
  debate topics (in the same daily batch, reviewed for battles: no politicians or groups of people
  as sides).
- **Write your own topic with AI**: the search field of the first step is also where you write a
  topic of your own. As soon as you type, "Surprise me" turns into an AI button (Enter works too)
  that writes three topics from your words in the style of the chosen format, in your language,
  or takes your words as they are. Free, up to 40 an hour. A topic you picked stays picked when
  you switch the format, news story included.
- **Earlier topics in search**: the list shows today's topics (20 a day per format); a search also
  finds the topics of earlier days.
- **Admin console**: Settings → Topics sets how many topics a day are written and how many are
  shown, the model that writes them (and the AI topics) and the model that reviews them. Model
  settings use the wizard's model picker, turned-off models too.

### Changed

- **Better trending topics**: Claude Haiku 5.5 writes them (sharper and cheaper than Gemini 2.5
  Flash in a side-by-side run) from a wider pool of headlines; Gemini 2.5 Flash reviews them, so
  no model checks its own topics.

## [1.5.1] - 2026-10-20

### Fixed

- **Verdicts of free debates**: the free model that structures them and checks them for the
  gallery (Nvidia's Nemotron 3 Super) now answers every request with an error, so free debates
  fell back to a plain-text verdict and were held back from the gallery. They use MiniMax M3.1
  Flash (free) instead; the console's lever can still switch it.

## [1.5.0] - 2026-10-20

### Changed

- **Rap battles sound like a show**: the MC calls the rappers into the ring like a ring announcer
  (short, shouted, about 15 seconds instead of 25), and the judge no longer reads the round scores
  aloud: the score sheet shows them while the judge shouts the totals and "and the winner is…".
  Medium battles add the moment that decided it, Long ones a line per round.
- **Eleven v4** voices new audio (ElevenLabs' most emotive model, same price); in rap battles the
  MC and the judge get announcer voices and the widest emotional range.
- **Three reply lengths**: Short, Medium and Long (~50, ~100 and ~250 words; 4, 8 and 12 lines a
  verse). The old Long (~500 words) is gone: a request for it runs as the new Long.
- **CLI 0.4.1**: `--length` (and the MCP tools' `length`) offers `very_short`, `short` and
  `medium` (~50, ~100 and ~250 words); `long` is gone.

## [1.4.1] - 2026-10-20

### Fixed

- **Embeds in editors and apps**: the player sent `frame-ancestors *`, which browsers read as
  "any http(s) page" and so refused inside `srcdoc` previews (WordPress shows oEmbed players in
  one), desktop apps and local files. It now sends no frame restriction at all.

## [1.4.0] - 2026-10-20

### Added

- **Found by search engines**: public pages (home, gallery, ranking, debates, topics) arrive as
  complete HTML, rendered by the new `web` service (React Router 8): each with its own title and
  description, the whole transcript, Open Graph and JSON-LD, and real 404 / 410 answers. Debate
  and topic addresses carry the topic's words (`/d/<slug>/<topic-words>`; older links redirect),
  `robots.txt` and the sitemaps come from the API, and changed pages are announced through
  IndexNow (`INDEXNOW_KEY`). Nothing tells who won: the audience still votes blind.
- **Link preview pictures**: a 1200×630 card for every debate, topic and listing — the debaters
  face off in their colours with the question — in Telegram, X, WhatsApp, Slack and the rest.
- **AI covers**: an eye-catching thumbnail per debate, drawn by GPT Image from a brief an art
  director writes without seeing the verdict. Runs paid from the balance or on an own OpenRouter
  key get one when they finish (console lever `ai_covers`); owners draw new versions with their
  own hook from the Export panel. The cover leads the gallery card, the link preview and the
  YouTube kit.
- **Embeddable player**: `/embed/<slug>` plays a public debate on other sites (the 16:9 episode,
  or the Short with `?format=short`; `?t=` starts at a second). The poster, the question and the
  length arrive as plain HTML, the player loads when the visitor reaches for it, and a view
  counts when it plays. The Share menu hands out the code with a live preview and can start it
  at the moment you are watching; `GET /api/oembed` turns a pasted debate or topic link into the
  player in apps that read oEmbed, and the pages name the endpoint. Only the player may be framed
  by other sites: the rest of the site now also sends `frame-ancestors 'self'`.
- **Where views come from**: the admin console's overview has an Audience section (views of the
  period, the share from search, AI assistants, social networks and embeds, a chart of views by
  source per day and the sites that embed debates), and the debate card a Views panel. Only
  counts are kept per day, source and place (the page or a player elsewhere): no IP, address or
  account. Visitors see the total as before.
- **CLI 0.4.0**: `debatr cover DEBATE [--hook] [-o FILE]`, `run --cover/--no-cover`, MCP
  `generate_cover` (within `DEBATR_MAX_COST_USD`) and the cover's URL in `--json` / `get_debate`;
  `show` and the other commands take the new `/d/<slug>/<topic-words>` links.

### Changed

- **The admin console is a build of its own**, served only on its host (`ADMIN_HOST`): the site
  carries none of its code. Gallery and library cards are 16:9, like the AI covers.
- **Self-hosting**: compose adds the `web` service (Node, 256 MB) between Caddy and the API; new
  optional settings `INDEXNOW_KEY`, `SEO_ALLOW_AI_CRAWLERS`, `AI_COVERS`, `COVER_*` and
  `OG_CACHE_MAX_MB` (see `.env.example`).
- **Honest view counts**: a view is counted only by the page itself once it has loaded (or by an
  embedded player when it starts), never by bots or by reading a debate through the API (the
  CLI, agents, the page renderer); one per visitor and debate in six hours, as before.

- **Faster public pages**: the debate player is a facade — the page arrives with the poster (the
  AI cover, or the video's first frame drawn in markup) and a play button, and the video player
  loads in idle time, on hover or on the first click (a click before it is there plays once it
  is, from the chosen turn). The page's first JavaScript is ~20 % smaller (Markdown through
  micromark, the export panel, the verdict tab and the owner's dialogs load when opened, the site
  calls the API with `fetch` instead of axios), fonts come from the site itself instead of Google
  Fonts with size-matched fallbacks, and nothing shifts while a page loads. On a throttled phone
  a debate page with a video and an AI cover paints its largest element in 3.1 s instead of 8.8 s.

## [1.3.0] - 2026-10-20

### Added

- **Rap battles** (`format: "rap_battle"`): an MC opens, two models trade verses of 4–16 lines
  over one beat for 1–3 rounds, and the judge scores every round. ElevenLabs Music generates the
  beat and the rapped verses as one track (each rapper picks a flow in place of a voice; the MC
  and the judge talk over it), paid per minute of music from the balance or on an own ElevenLabs
  key on a paid plan. The wizard has format cards, the video and the verdict tab show the
  judge's score sheet, the gallery a format filter and the ranking a Rappers tab.
- **One topic, many versions**: debates on the same question (the same text after normalizing,
  a remix, a translation) share one gallery card, whose cover is the version that earned it its
  place; the debate page switches between the versions, `/t/<slug>` lists them all, the wizard
  says which topic a question joins, and the console moves or merges topics.
- **Sides**: debaters argue for or against the topic, or a position of their own (a structured
  field instead of a sentence in the persona); round labels come from the server.
- **CLI 0.3.0**: `debatr run --format rap_battle --flow …`, `debatr formats`, `--format` for
  `gallery` and `leaderboard`, the judge's round scores in the output; MCP `list_formats` and
  `format` / `flows` in `start_debate` and `estimate_debate`.
- **Admin console** on its own host (`ADMIN_HOST`, optional `ADMIN_ALLOWED_IPS`): sign-in with a
  password and a TOTP code or a passkey, recovery codes, sessions you can revoke and a fresh code
  for sensitive actions. Overview with charts and an attention list; users (filters, CSV, a card
  with spend and activity, credits, disable, tokens, sign out everywhere, delete); debates (a
  card with the video, the transcript with per-turn usage, provider calls; stop, resume, rebuild
  audio, refund, publish); a keyboard-driven moderation queue; trending batches; finance (margin
  per day / week / month, Stripe reconciliation); models (failures, speed, wins); system
  (queues, workers, scheduler, runs in flight, limits, providers, health); settings that change
  levers without a deploy (sign-ups, maintenance, turned-off models, prices, free limits); an
  append-only audit log. Roles are granted only on the server (`python -m app.manage admin
  grant`). It replaces the old sqladmin pages.
- **Telegram alerts** (`ALERT_TELEGRAM_BOT_TOKEN`, `ALERT_TELEGRAM_CHAT_ID`): console sign-ins,
  new accounts and debates, flagged or failing debates, stuck runs, low provider balances,
  top-ups, a full disk; kinds can be muted in the console.
- **Provider usage and activity data**: every paid provider call (cost, tokens, time, errors) and
  one activity row per user and day, behind the console's statistics.
- **Database backups**: `make backup` (compressed dumps, pruning, optional encrypted off-site copy
  with rclone) and `make backup-check` (restores the newest dump into a scratch database).
- **Premium voices in the gallery**: debates voiced with ElevenLabs rank higher in Trending, carry
  a badge and have their own filter.
- **Face-off covers**: gallery cards, the video's first frame and the Short's hook show the
  debaters' logos on slanted halves in their colours.
- **`GET /api/health/full`** for an outside uptime monitor: besides the database and Redis it
  answers 503 when a queue (`default`, `background`, `media`) has no worker or the cron
  scheduler is gone, which the Telegram alerts cannot report since they run on those processes.

### Changed

- **Prices are levers of the admin console** (Settings → Prices): the markup on the provider
  cost of models, fact-checks and AI pictures, a minimum for a completed paid debate (new) and
  the price of premium voices. A run is charged at the prices it was quoted when it started (a
  resume keeps them; an audio build at the prices of its request). The public billing
  configuration no longer shows the markup.
- **Limits of free debates**: an account without credits or an own OpenRouter key may start 5
  debates on free models in any 24 hours, of up to 3 rounds and 4 debaters with very short or
  short replies (they share OpenRouter's daily free-model quota). The wizard locks the longer
  options and shows how many are left; the API answers 402 / 429 with what to do. Credits or
  an own key lift the limits; the console's Settings page changes them.
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

- **Postgres 18 and Redis 8** in Docker Compose; Redis keeps its snapshot in a volume.

### Fixed

- **Real client IPs behind a proxy**: the frontend's Caddy trusts private-range proxies, so the
  API sees https and each visitor's address (rate limits, the console's IP checks, view counts).
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

[Unreleased]: https://github.com/khoren93/debatr/compare/v1.9.0...HEAD
[1.9.0]: https://github.com/khoren93/debatr/compare/v1.8.1...v1.9.0
[1.8.1]: https://github.com/khoren93/debatr/compare/v1.8.0...v1.8.1
[1.8.0]: https://github.com/khoren93/debatr/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/khoren93/debatr/compare/v1.6.1...v1.7.0
[1.6.1]: https://github.com/khoren93/debatr/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/khoren93/debatr/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/khoren93/debatr/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/khoren93/debatr/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/khoren93/debatr/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/khoren93/debatr/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/khoren93/debatr/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/khoren93/debatr/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/khoren93/debatr/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/khoren93/debatr/releases/tag/v1.0.0
