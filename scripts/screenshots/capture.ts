/**
 * Captures the README images from a running Debatr: phone screenshots of the main screens, a
 * frame of the 16:9 video, and the hero composed from three of the screens.
 *
 *   make screenshots DEBATR_EMAIL=you@example.com DEBATR_PASSWORD=… [DEBATE=<id>]
 *
 * The same variables may sit in scripts/screenshots/.env (git-ignored like every .env); the
 * command line wins. The stack serves the built frontend: after UI changes run
 * `make restart s=frontend` first, or point DEBATR_URL at a Vite dev server.
 *
 * Needs the stack on DEBATR_URL (default http://localhost) with a batch of trending topics, and
 * an account whose newest finished debate has its audio built with scenes (DEBATE=<id> picks
 * another one). Nothing is created or changed on the server: the audience numbers (views,
 * likes, votes, model ratings) are invented in the browser, see "Showcase numbers"
 * (SHOWCASE=off shows the real ones). The browser is the installed Google Chrome
 * (SCREENSHOT_CHANNEL=chromium uses Playwright's own build instead).
 *
 * Screens are numbered in the order a debate is made and watched (01_topics … 06_leaderboard).
 * ONLY=episode,verdict shoots a subset (names without the number), ONLY=hero only recomposes the
 * hero; OUT=<dir> writes somewhere else than scripts/screenshots/out/ (git-ignored: the images
 * are uploaded to GitHub, not committed).
 */
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { type Browser, type BrowserContext, chromium, type Page, type Route } from 'playwright-core';

const root = join(import.meta.dirname, '..', '..');
const envFile = join(import.meta.dirname, '.env');
if (existsSync(envFile)) process.loadEnvFile(envFile);
const assets = process.env.OUT ?? join(import.meta.dirname, 'out');
const screens = join(assets, 'screens');
const BASE = (process.env.DEBATR_URL ?? 'http://localhost').replace(/\/$/, '');
const PHONE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 1000 };
const ONLY = process.env.ONLY?.split(',').filter(Boolean) ?? [];
const WIZARD_KEY = 'debatr.wizard.v1';

interface Debate {
  id: string;
  turns: unknown[];
}
interface TimelineVisual {
  seq_index: number;
  start_ms: number;
  end_ms: number;
  scene: { type: string; check?: { status?: string } | null };
}
interface Timeline {
  total_ms: number;
  visuals: TimelineVisual[];
  highlights: { start_ms: number; end_ms: number }[];
}

/**
 * The phone screens in the order a debate is made and watched: `screens/01_topics.png` … PNG,
 * since GitHub's attachments take no WebP.
 */
const SCREENS = ['topics', 'speakers', 'episode', 'verdict', 'short', 'leaderboard'];
const screenFile = (name: string) => join(screens, `${String(SCREENS.indexOf(name) + 1).padStart(2, '0')}_${name}.png`);
const wanted = (name: string) => ONLY.length === 0 || ONLY.includes(name);
const fail = (message: string): never => {
  console.error(`! ${message}`);
  process.exit(1);
};

async function signIn(context: BrowserContext): Promise<void> {
  const email = process.env.DEBATR_EMAIL;
  const password = process.env.DEBATR_PASSWORD;
  if (!email || !password) fail('Set DEBATR_EMAIL and DEBATR_PASSWORD (the account to shoot).');
  const response = await context.request.post(`${BASE}/api/auth/login`, { data: { email, password } });
  if (!response.ok()) fail(`Sign-in failed: ${response.status()} ${await response.text()}`);
}

async function getJson<T>(context: BrowserContext, path: string): Promise<T> {
  const response = await context.request.get(`${BASE}${path}`);
  if (!response.ok()) fail(`GET ${path}: ${response.status()}`);
  return (await response.json()) as T;
}

/** The debate to show: DEBATE, else the newest finished one with its video ready. */
async function pickDebate(context: BrowserContext): Promise<{ debate: Debate; timeline: Timeline }> {
  let id = process.env.DEBATE;
  if (!id) {
    const list = await getJson<{ id: string; media_status: string }[]>(context, '/api/debates?status=completed');
    id = list.find((d) => d.media_status === 'ready')?.id;
    if (!id) fail('No finished debate with audio on this account: run one with scenes and audio first.');
  }
  const debate = await getJson<Debate>(context, `/api/debates/${id}`);
  const media = await getJson<{ urls: { timeline?: string } | null }>(context, `/api/debates/${id}/media`);
  if (!media.urls?.timeline) fail(`Debate ${id} has no video timeline yet.`);
  const timeline = await getJson<Timeline>(context, media.urls!.timeline!);
  console.log(`· debate ${id}: ${debate.turns.length} turns, ${timeline.visuals.length} scenes`);
  return { debate, timeline };
}

/** Loads lazy images and fonts, so nothing is half-rendered. */
async function settle(page: Page, ms = 500): Promise<void> {
  await page.evaluate(async () => {
    for (const image of document.images) image.loading = 'eager';
    await Promise.all([...document.images].map((image) => image.decode().catch(() => undefined)));
    await document.fonts.ready;
  });
  await page.waitForTimeout(ms);
}

function save(path: string, data: Buffer): void {
  writeFileSync(path, data);
  console.log(`+ ${path.replace(`${root}/`, '')} (${Math.round(data.length / 1024)} KB)`);
}

/** Saves the viewport as `screens/<name>.png`. */
class Shooter {
  async shoot(page: Page, name: string): Promise<void> {
    await settle(page);
    save(screenFile(name), await page.screenshot({ type: 'png' }));
  }
}

const scrollTo = async (page: Page, selector: string, offset = 12) => {
  await page.locator(selector).first().evaluate((el, offset) => {
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - offset, behavior: 'instant' });
  }, offset);
};

/** Hides the big play button the paused player shows over the frame. */
const hidePausedOverlay = (page: Page) => page.addStyleTag({ content: 'div:has(> .bg-accent\\/92){display:none!important}' });

/** Seeks the player with its own slider (keyboard steps of 5 s from the start). */
async function seek(page: Page, ms: number): Promise<void> {
  const slider = page.getByRole('slider').first();
  await slider.waitFor();
  await slider.focus();
  await page.keyboard.press('Home');
  for (let i = 0; i < Math.round(ms / 5000); i++) await page.keyboard.press('ArrowRight');
  await slider.blur();
  await page.waitForTimeout(1200);
}

/** Player clock = `offset` + timeline clock (frontend helpers.videoChapters). */
const INTRO_MS = 1800;
const SHORT_HOOK_MS = 1600;
const SCENE_ORDER = ['bars', 'line', 'stat', 'map', 'pie', 'proportion', 'ranking', 'quote', 'scale', 'versus', 'matrix', 'flow', 'sketch', 'image', 'timeline', 'venn'];

/**
 * The player time to show the best scene in [from, to) at: charts first, fact-checked ones
 * before the rest, at a 5 s step (the slider's keyboard step) once its items are in.
 */
function sceneTime(timeline: Timeline, offset: number, from = 0, to = Infinity): number | null {
  const moments = timeline.visuals
    .filter((v) => SCENE_ORDER.includes(v.scene.type) && v.start_ms >= from && v.end_ms <= to)
    .map((v) => {
      const earliest = offset + v.start_ms + 2500;
      const latest = offset + v.end_ms - 400;
      const target = offset + v.start_ms + (v.end_ms - v.start_ms) * 0.75;
      const step = Math.min(Math.floor(target / 5000), Math.floor(latest / 5000)) * 5000;
      const score = SCENE_ORDER.indexOf(v.scene.type) - (v.scene.check?.status === 'verified' ? 6 : 0);
      return { at: step >= earliest ? step : null, score };
    })
    .filter((m) => m.at !== null)
    .sort((a, b) => a.score - b.score);
  return moments[0]?.at ?? null;
}

const longSceneTime = (timeline: Timeline) => sceneTime(timeline, INTRO_MS) ?? 30000;

function shortSceneTime(timeline: Timeline): number {
  const h = timeline.highlights[0] ?? { start_ms: 0, end_ms: Math.min(timeline.total_ms, 45000) };
  const offset = SHORT_HOOK_MS - h.start_ms;
  return sceneTime(timeline, offset, h.start_ms, h.end_ms) ?? Math.round((SHORT_HOOK_MS + (h.end_ms - h.start_ms) / 2) / 5000) * 5000;
}

/** Height of the sticky mobile top bar, so scrolled-to elements are not under it. */
const TOP_BAR = 70;

// --- Showcase numbers ---------------------------------------------------------------------

/*
 * A local stack has no audience: every debate says 0 likes and the model ranking is empty. The
 * screenshots show invented but plausible numbers instead, patched into the API responses in
 * the browser. They are derived from the debate or model id, so every run and every screen
 * (debate page, ranking, wizard ranks) shows the same ones.
 */

/** A stable number in [0, 1) for `key` (FNV-1a with a final mix). */
function unit(key: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 0x01000193);
  h ^= h >>> 15;
  h = Math.imul(h, 0x2c1b3c6d);
  h ^= h >>> 12;
  return (h >>> 0) / 2 ** 32;
}
const between = (key: string, min: number, max: number) => min + (max - min) * unit(key);
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

interface Participant {
  id: string;
  role: string;
}
interface Audience {
  total: number;
  counts: Record<string, number>;
}
interface DebateDetail {
  id: string;
  views: number;
  participants: Participant[];
  is_public: boolean;
  engagement: { likes: number; audience: Audience };
}
interface LeaderboardEntry {
  model_id: string;
  is_free: boolean;
  rating: number;
  rated: boolean;
  debates: number;
  votes: number;
  vote_share: number | null;
  audience_wins: number;
  audience_contests: number;
  judge_wins: number;
  judge_contests: number;
}
interface Leaderboard {
  entries: LeaderboardEntry[];
  total_votes: number;
}

/** Views (700–6.8k), likes (3.5–8.5 %), audience votes (2–5 %) and their split for one debate. */
function audienceOf(id: string, participants: Participant[]): { views: number; likes: number; audience: Audience } {
  const views = Math.round(Math.exp(between(`${id}:views`, Math.log(700), Math.log(6800))));
  const likes = Math.round(views * between(`${id}:likes`, 0.035, 0.085));
  const debaters = participants.filter((p) => p.role === 'debater').map((p) => p.id);
  if (debaters.length < 2) return { views, likes, audience: { total: 0, counts: {} } };
  const total = Math.round(views * between(`${id}:votes`, 0.02, 0.05));
  const weights = debaters.map((d) => 0.6 + unit(`${id}:${d}`));
  const sum = weights.reduce((a, b) => a + b, 0);
  const counts: Record<string, number> = {};
  let left = total;
  debaters.forEach((d, i) => {
    counts[d] = i === debaters.length - 1 ? left : Math.round((total * weights[i]) / sum);
    left -= counts[d];
  });
  return { views, likes, audience: { total, counts } };
}

function detailWithAudience(detail: DebateDetail): DebateDetail {
  if (!detail.is_public) return detail;
  const { views, likes, audience } = audienceOf(detail.id, detail.participants);
  const engagement = { ...detail.engagement, likes, audience: { ...detail.engagement.audience, ...audience } };
  return { ...detail, views, engagement };
}

/**
 * Ratings around 1000: paid models a little above free ones, the judge's record nudges them,
 * the rest is noise. Vote shares and audience wins follow the rating.
 */
function rankModels(board: Leaderboard): Leaderboard {
  const entries = board.entries.map((e) => {
    const judged = e.judge_contests > 0 ? e.judge_wins / e.judge_contests : 0.5;
    const rating = Math.round(1000 + (e.is_free ? -55 : 25) + (judged - 0.5) * 70 + between(`${e.model_id}:rating`, -45, 45));
    const share = clamp(0.5 + (rating - 1000) / 420, 0.22, 0.78);
    const votes = Math.round(e.debates * between(`${e.model_id}:votes`, 50, 180) * share);
    const wins = clamp(Math.round(e.debates * (share + between(`${e.model_id}:wins`, -0.15, 0.15))), 0, e.debates);
    return { ...e, rating, rated: true, votes, vote_share: Math.round(share * 1000) / 1000, audience_wins: wins, audience_contests: e.debates };
  });
  entries.sort((a, b) => b.rating - a.rating);
  return { ...board, entries, total_votes: entries.reduce((sum, e) => sum + e.votes, 0) };
}

/** Routes the model ranking and debate pages through the showcase numbers. */
async function showcase(context: BrowserContext): Promise<void> {
  if (process.env.SHOWCASE === 'off') return;
  const patch =
    <T>(transform: (json: T) => unknown) =>
    async (route: Route) => {
      const response = await route.fetch();
      if (!response.ok()) return route.fulfill({ response });
      await route.fulfill({ response, json: transform((await response.json()) as T) });
    };
  await context.route(/\/api\/gallery\/leaderboard(\?|$)/, patch(rankModels));
  await context.route(/\/api\/debates\/[0-9a-f-]{36}(\?|$)/, patch(detailWithAudience));
}

// --- Screens ---------------------------------------------------------------------------

async function captureWizard(context: BrowserContext, shooter: Shooter, debate: Debate): Promise<void> {
  const page = await context.newPage();
  if (wanted('topics')) {
    await page.goto(`${BASE}/create`);
    await page.evaluate((key) => localStorage.removeItem(key), WIZARD_KEY);
    await page.reload();
    await page.getByLabel('Search topics').waitFor();
    // Today's tech stories, the first one picked.
    await page.getByRole('tab', { name: /^Tech/ }).click();
    await page.locator('button[aria-pressed]').first().click();
    await page.waitForTimeout(600);
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await shooter.shoot(page, 'topics');
  }
  if (wanted('speakers')) {
    // A remix of the shown debate fills the wizard with its lineup.
    await page.goto(`${BASE}/create?remix=${debate.id}`);
    await page.waitForURL(`${BASE}/create`);
    await page.getByRole('button', { name: /^Continue/ }).last().click();
    await page.waitForTimeout(600);
    await shooter.shoot(page, 'speakers');
    await page.evaluate((key) => localStorage.removeItem(key), WIZARD_KEY);
  }
  await page.close();
}

async function captureDebate(context: BrowserContext, shooter: Shooter, debate: Debate, timeline: Timeline): Promise<void> {
  const page = await context.newPage();
  await page.goto(`${BASE}/debate/${debate.id}`);
  await page.getByRole('slider').first().waitFor();
  if (wanted('episode')) {
    // The finished episode as it opens: the face-off poster with its play button.
    await page.waitForTimeout(800);
    await shooter.shoot(page, 'episode');
  }
  await hidePausedOverlay(page);

  if (wanted('verdict')) {
    const tab = page.getByRole('tab', { name: 'Verdict' });
    await tab.click();
    await page.waitForTimeout(600);
    // The judge's ruling from the tabs down (the audience's split is on the episode screen).
    await tab.evaluate((el, offset) => {
      window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - offset, behavior: 'instant' });
    }, TOP_BAR + 8);
    await shooter.shoot(page, 'verdict');
    await page.getByRole('tab', { name: 'Transcript' }).click();
  }
  if (wanted('short')) {
    await page.getByRole('button', { name: 'Short 9:16' }).click();
    await seek(page, shortSceneTime(timeline));
    await scrollTo(page, '.__remotion-player', TOP_BAR);
    await shooter.shoot(page, 'short');
  }
  await page.close();
}

async function captureLeaderboard(context: BrowserContext, shooter: Shooter): Promise<void> {
  const page = await context.newPage();
  await page.goto(`${BASE}/leaderboard`);
  await page.getByRole('heading', { name: 'Model ranking' }).waitFor();
  await page.waitForTimeout(800);
  await shooter.shoot(page, 'leaderboard');
  await page.close();
}

/** One frame of the 16:9 episode at the hero scene (desktop page, player element only). */
async function captureFrame(browser: Browser, context: BrowserContext, debate: Debate, timeline: Timeline): Promise<Buffer> {
  const state = await context.storageState();
  const desktop = await browser.newContext({ viewport: DESKTOP, deviceScaleFactor: 2, colorScheme: 'dark', storageState: state });
  const page = await desktop.newPage();
  await page.goto(`${BASE}/debate/${debate.id}`);
  await hidePausedOverlay(page);
  await seek(page, longSceneTime(timeline));
  await settle(page);
  const png = await page.locator('.__remotion-player').first().screenshot({ type: 'png' });
  await desktop.close();
  return png;
}

// --- Hero ---------------------------------------------------------------------------------

/** The mark of frontend/public/favicon.svg. */
const MARK = `<svg width="46" height="46" viewBox="0 0 64 64"><rect width="64" height="64" rx="18" fill="#D9FF3D"/><path d="M14 18a6 6 0 0 1 6-6h11a19 19 0 0 1 0 38h-7l-10 8.5V18Z" fill="#0A0B0F"/><g fill="#D9FF3D"><rect x="20.9" y="26" width="5" height="10" rx="2.5"/><rect x="28.5" y="21" width="5" height="20" rx="2.5"/><rect x="36.1" y="24.5" width="5" height="13" rx="2.5"/></g></svg>`;

/** Phones on the hero: the big one in front, then the two smaller ones behind it (left, right). */
const HERO_PHONES = { main: 'episode', left: 'verdict', right: 'short' } as const;

const inline = (path: string) => `data:image/png;base64,${readFileSync(path).toString('base64')}`;

/** The README hero (1280×640): the pitch on the left, three phones on the right. */
function heroHtml(): string {
  const phone = (name: string, left: number, top: number, width: number, main = false) =>
    `<img class="phone${main ? ' main' : ''}" src="${inline(screenFile(name))}" alt="" style="left:${left}px;top:${top}px;width:${width}px">`;
  const pill = (color: string, label: string) => `<span class="pill"><i style="background:${color}"></i>${label}</span>`;
  return `<!doctype html><html><head><meta charset="utf-8">
  <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800&family=DM+Sans:opsz,wght@9..40,400..700&family=JetBrains+Mono:wght@400;500&display=block" rel="stylesheet">
  <style>
    body{margin:0}
    .hero{position:relative;width:1280px;height:640px;overflow:hidden;background:#0A0B0F;color:#F2F3F7;font-family:'DM Sans',sans-serif}
    .glow{position:absolute;border-radius:50%;filter:blur(110px)}
    .disp{font-family:'Bricolage Grotesque',sans-serif;font-weight:800;letter-spacing:-0.035em}
    .pill{display:flex;align-items:center;gap:9px;height:38px;padding:0 15px;border-radius:999px;background:#12141B;border:1px solid rgba(255,255,255,.09);font-size:15px;font-weight:500;color:#D5D8E2}
    .pill i{width:8px;height:8px;border-radius:50%}
    .phone{position:absolute;border-radius:30px;border:5px solid #1E212B;box-shadow:0 30px 60px rgba(0,0,0,.6)}
    .phone.main{border-radius:36px;border:6px solid #2C303C;box-shadow:0 40px 80px rgba(0,0,0,.7)}
  </style></head><body><div class="hero">
    <div class="glow" style="left:720px;top:110px;width:300px;height:320px;background:#6C9CFF;opacity:.2"></div>
    <div class="glow" style="left:960px;top:150px;width:300px;height:320px;background:#FF7A66;opacity:.16"></div>
    <div class="glow" style="left:-120px;top:380px;width:420px;height:320px;background:#D9FF3D;opacity:.08"></div>
    <div style="position:absolute;left:72px;top:0;height:640px;width:560px;display:flex;flex-direction:column;justify-content:center;gap:24px">
      <div style="display:flex;align-items:center;gap:14px">${MARK}<span class="disp" style="font-size:31px;font-weight:700;letter-spacing:-0.025em">Debatr</span></div>
      <h1 class="disp" style="margin:0;font-size:60px;line-height:1">Two AIs. One topic.<br><span style="color:#D9FF3D">A video in minutes.</span></h1>
      <p style="margin:0;font-size:19px;line-height:1.5;color:#B4B8C6;max-width:520px">Cast any models on OpenRouter, watch them argue live with charts and fact-checks on screen, get the judge's verdict, and export a 16:9 episode plus a 9:16 Short right in your browser.</p>
      <div style="display:flex;flex-wrap:wrap;gap:10px">${pill('#6C9CFF', 'Hundreds of models')}${pill('#FF7A66', 'Live visual scenes')}${pill('#52D889', 'Fact-checked')}</div>
      <div style="display:flex;gap:24px;font-family:'JetBrains Mono',monospace;font-size:13px;color:#8B90A0;letter-spacing:.08em">
        <span>OPEN SOURCE</span><span>SELF-HOST</span><span>CLI + MCP</span><span>MIT</span></div>
    </div>
    ${phone(HERO_PHONES.left, 706, 118, 226)}${phone(HERO_PHONES.right, 1032, 118, 226)}${phone(HERO_PHONES.main, 846, 56, 265, true)}
  </div></body></html>`;
}

/** GitHub takes social previews up to 1 MB. */
const SOCIAL_PREVIEW_MAX = 1024 * 1024;

/**
 * One image for the README and GitHub's social preview (Settings → Social preview takes no
 * WebP): a 2560×1280 JPEG, its quality lowered until it fits in 1 MB.
 */
async function captureHero(browser: Browser): Promise<void> {
  const page = await browser.newPage({ viewport: { width: 1280, height: 640 }, deviceScaleFactor: 2 });
  await page.setContent(heroHtml(), { waitUntil: 'networkidle' });
  await settle(page, 300);
  let jpeg: Buffer = Buffer.alloc(0);
  for (const quality of [92, 88, 84, 80, 75]) {
    jpeg = await page.screenshot({ type: 'jpeg', quality });
    if (jpeg.length <= SOCIAL_PREVIEW_MAX) break;
  }
  if (jpeg.length > SOCIAL_PREVIEW_MAX) console.warn('! hero.jpg is over 1 MB: too big for the social preview');
  save(join(assets, 'hero.jpg'), jpeg);
  await page.close();
}

// --- Main --------------------------------------------------------------------------------

// A full run starts from an empty folder, so no stale screens stay behind.
if (ONLY.length === 0) rmSync(screens, { recursive: true, force: true });
mkdirSync(screens, { recursive: true });
const channel = process.env.SCREENSHOT_CHANNEL ?? 'chrome';
const browser = await chromium.launch(channel === 'chromium' ? {} : { channel });
try {
  if ([...SCREENS, 'frame'].some(wanted)) {
    const context = await browser.newContext({
      viewport: PHONE,
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
      colorScheme: 'dark',
      locale: 'en-US',
    });
    await signIn(context);
    await showcase(context);
    const { debate, timeline } = await pickDebate(context);
    const shooter = new Shooter();

    await captureWizard(context, shooter, debate);
    await captureDebate(context, shooter, debate, timeline);
    if (wanted('leaderboard')) await captureLeaderboard(context, shooter);
    if (wanted('frame')) {
      save(join(assets, 'frame.png'), await captureFrame(browser, context, debate, timeline));
    }
  }
  // Composed from the files on disk, so ONLY=hero redraws it without shooting again.
  if (wanted('hero')) await captureHero(browser);
} finally {
  await browser.close();
}
