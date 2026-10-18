/**
 * Captures the README images from a running Debatr: phone screenshots of the main screens, a
 * frame of the 16:9 video, and the hero / social preview composed from them.
 *
 *   make screenshots DEBATR_EMAIL=you@example.com DEBATR_PASSWORD=… [DEBATE=<id>]
 *
 * The same variables may sit in scripts/screenshots/.env (git-ignored like every .env); the
 * command line wins. The stack serves the built frontend: after UI changes run
 * `make restart s=frontend` first, or point DEBATR_URL at a Vite dev server.
 *
 * Needs the stack on DEBATR_URL (default http://localhost) with a batch of trending topics, and
 * an account whose newest finished debate has its audio built with scenes (DEBATE=<id> picks
 * another one). Nothing is created or changed on the server: the "live" screen replays that
 * finished debate through intercepted requests. The browser is the installed Google Chrome
 * (SCREENSHOT_CHANNEL=chromium uses Playwright's own build instead).
 *
 * Screens are numbered in the order a debate is made and watched (01_topics … 09_leaderboard).
 * ONLY=live,verdict shoots a subset (names without the number), ONLY=hero only recomposes the hero; OUT=<dir> writes somewhere else than
 * scripts/screenshots/out/ (git-ignored: the images are uploaded to GitHub, not committed).
 */
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { type Browser, type BrowserContext, chromium, type Page } from 'playwright-core';

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

interface Turn {
  seq_index: number;
  round_id: string;
  turn_type: string;
  speaker_role: string;
  speaker_id: string | null;
  speaker_name: string;
  text: string;
  visuals: { scenes?: unknown[] } | null;
}
interface Debate {
  id: string;
  status: string;
  media_status: string;
  turns: Turn[];
  [key: string]: unknown;
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

/** The phone screens in the order a debate is made and watched: `screens/01_topics.webp` … */
const SCREENS = ['topics', 'speakers', 'format', 'live', 'scenes', 'verdict', 'short', 'gallery', 'leaderboard'];
const screenFile = (name: string) => join(screens, `${String(SCREENS.indexOf(name) + 1).padStart(2, '0')}_${name}.webp`);
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

/** PNG → WebP through the browser's own encoder (no native image library needed). */
async function encode(encoder: Page, png: Buffer, type: 'image/webp' | 'image/jpeg', quality: number): Promise<Buffer> {
  const base64 = await encoder.evaluate(
    async ({ data, type, quality }) => {
      const image = new Image();
      image.src = `data:image/png;base64,${data}`;
      await image.decode();
      const canvas = new OffscreenCanvas(image.naturalWidth, image.naturalHeight);
      canvas.getContext('2d')!.drawImage(image, 0, 0);
      const blob = await canvas.convertToBlob({ type, quality });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      return btoa(binary);
    },
    { data: png.toString('base64'), type, quality },
  );
  return Buffer.from(base64, 'base64');
}

function save(path: string, data: Buffer): void {
  writeFileSync(path, data);
  console.log(`+ ${path.replace(`${root}/`, '')} (${Math.round(data.length / 1024)} KB)`);
}

/** Saves the viewport as `screens/<name>.webp`. */
class Shooter {
  readonly encoder: Page;
  constructor(encoder: Page) {
    this.encoder = encoder;
  }

  async shoot(page: Page, name: string): Promise<void> {
    await settle(page);
    const png = await page.screenshot({ type: 'png' });
    save(screenFile(name), await encode(this.encoder, png, 'image/webp', 0.9));
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
  if (wanted('speakers') || wanted('format')) {
    // A remix of the shown debate fills the wizard with its lineup.
    await page.goto(`${BASE}/create?remix=${debate.id}`);
    await page.waitForURL(`${BASE}/create`);
    await page.getByRole('button', { name: /^Continue/ }).last().click();
    await page.waitForTimeout(600);
    if (wanted('speakers')) await shooter.shoot(page, 'speakers');
    await page.getByRole('button', { name: /^Continue/ }).last().click();
    await page.waitForTimeout(1500);
    if (wanted('format')) await shooter.shoot(page, 'format');
    await page.evaluate((key) => localStorage.removeItem(key), WIZARD_KEY);
  }
  await page.close();
}

/** Replays the debate as if it were running: the turns before `seq` done, `seq` half-written. */
async function captureLive(context: BrowserContext, shooter: Shooter, debate: Debate): Promise<void> {
  const debaters = debate.turns.filter((t) => t.speaker_role === 'debater' && t.round_id !== 'round_1');
  const live = debaters.at(-1) ?? debate.turns.at(-2)!;
  const words = live.text.split(/(\s+)/);
  const partial = words.slice(0, Math.round(words.length * 0.55)).join('');
  // A running debate is not in the gallery yet: no likes, votes or share link.
  const running = {
    ...debate,
    status: 'running',
    media_status: 'none',
    ended_at: null,
    verdict: null,
    is_public: false,
    slug: null,
    share_url: null,
    published_at: null,
    turns: debate.turns.filter((t) => t.seq_index < live.seq_index),
  };
  const event = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
  const stream =
    'retry: 86400000\n\n' +
    event('turn_started', {
      seq_index: live.seq_index,
      speaker_name: live.speaker_name,
      speaker_role: live.speaker_role,
      turn_type: live.turn_type,
      round_id: live.round_id,
    }) +
    event('turn_delta', { seq_index: live.seq_index, delta: partial, speaker_name: live.speaker_name });

  const page = await context.newPage();
  await page.route(`**/api/debates/${debate.id}`, (route) => route.fulfill({ json: running }));
  await page.route(`**/api/debates/${debate.id}/stream`, (route) =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' }, body: stream }),
  );
  await page.route(`**/api/debates/${debate.id}/media`, (route) =>
    route.fulfill({ json: { debate_id: debate.id, media_status: 'none', progress: null, options: null, urls: null, stats: null, started_at: null, finished_at: null } }),
  );
  await page.goto(`${BASE}/debate/${debate.id}`);
  await page.getByText('Live', { exact: true }).first().waitFor();
  await page.waitForTimeout(1500);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await shooter.shoot(page, 'live');
  await page.close();
}

async function captureDebate(context: BrowserContext, shooter: Shooter, debate: Debate, timeline: Timeline): Promise<void> {
  const page = await context.newPage();
  await page.goto(`${BASE}/debate/${debate.id}`);
  await page.getByRole('slider').first().waitFor();
  await hidePausedOverlay(page);

  if (wanted('scenes')) {
    // The first debater turn with a fact-checked scene, else with the most scenes.
    const turns = debate.turns.filter((t) => t.speaker_role === 'debater' && t.visuals?.scenes?.length);
    const turn = turns.find((t) => JSON.stringify(t.visuals).includes('"verified"')) ?? turns[0];
    if (turn) {
      // The end of the turn: its last words and the scene board above the bottom tabs.
      await page.locator(`#turn-${turn.seq_index}`).evaluate((el) => {
        const bottom = el.getBoundingClientRect().bottom + window.scrollY;
        window.scrollTo({ top: bottom - window.innerHeight + 96, behavior: 'instant' });
        // Phones show the scenes as a strip: swipe to the first one with a fact-check or dispute badge.
        const badge = [...el.querySelectorAll('span')].find((s) => /^(Fact-checked|disputed by)/i.test(s.textContent?.trim() ?? ''));
        const card = badge?.closest<HTMLElement>('.snap-start');
        const strip = card?.parentElement;
        if (card && strip) strip.scrollTo({ left: card.offsetLeft - strip.offsetLeft, behavior: 'instant' });
      });
      await shooter.shoot(page, 'scenes');
    }
  }
  if (wanted('verdict')) {
    const tab = page.getByRole('tab', { name: 'Verdict' });
    await tab.click();
    await page.waitForTimeout(600);
    await tab.evaluate((el, offset) => {
      window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - offset, behavior: 'instant' });
    }, TOP_BAR + 8);
    await shooter.shoot(page, 'verdict');
    await page.getByRole('tab', { name: 'Transcript' }).click();
  }
  if (wanted('short')) {
    await page.getByRole('tab', { name: 'Short 9:16' }).click();
    await seek(page, shortSceneTime(timeline));
    await scrollTo(page, '.__remotion-player', TOP_BAR);
    await shooter.shoot(page, 'short');
  }
  await page.close();
}

async function capturePublic(context: BrowserContext, shooter: Shooter): Promise<void> {
  const page = await context.newPage();
  if (wanted('gallery')) {
    await page.goto(`${BASE}/gallery`);
    await page.getByRole('heading', { name: 'Gallery' }).waitFor();
    await page.waitForTimeout(800);
    await shooter.shoot(page, 'gallery');
  }
  if (wanted('leaderboard')) {
    await page.goto(`${BASE}/leaderboard`);
    await page.getByRole('heading', { name: 'Model ranking' }).waitFor();
    await page.waitForTimeout(800);
    await shooter.shoot(page, 'leaderboard');
  }
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

/** Phones on the hero, left and right of the video frame. */
const HERO_PHONES = ['verdict', 'short'] as const;

const inline = (path: string) => `data:image/webp;base64,${readFileSync(path).toString('base64')}`;

/** The README hero (1280×640): the pitch on the left, the video and two phones on the right. */
function heroHtml(): string {
  const phone = (name: string, style: string) =>
    `<img class="phone" src="${inline(screenFile(name))}" alt="" style="${style}">`;
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
    .frame{position:absolute;left:668px;top:58px;width:560px;border-radius:18px;border:1px solid rgba(255,255,255,.12);box-shadow:0 40px 90px rgba(0,0,0,.6)}
    .phone{position:absolute;width:206px;border-radius:32px;border:5px solid #1E212B;box-shadow:0 30px 70px rgba(0,0,0,.65)}
  </style></head><body><div class="hero">
    <div class="glow" style="left:760px;top:120px;width:420px;height:300px;background:#6C9CFF;opacity:.18"></div>
    <div class="glow" style="left:980px;top:300px;width:360px;height:300px;background:#FF7A66;opacity:.14"></div>
    <div class="glow" style="left:-120px;top:380px;width:420px;height:320px;background:#D9FF3D;opacity:.08"></div>
    <div style="position:absolute;left:72px;top:0;height:640px;width:560px;display:flex;flex-direction:column;justify-content:center;gap:24px">
      <div style="display:flex;align-items:center;gap:14px">${MARK}<span class="disp" style="font-size:31px;font-weight:700;letter-spacing:-0.025em">Debatr</span></div>
      <h1 class="disp" style="margin:0;font-size:60px;line-height:1">Two AIs. One topic.<br><span style="color:#D9FF3D">A video in minutes.</span></h1>
      <p style="margin:0;font-size:19px;line-height:1.5;color:#B4B8C6;max-width:520px">Cast any models on OpenRouter, watch them argue live with charts and fact-checks on screen, get the judge's verdict, and export a 16:9 episode plus a 9:16 Short right in your browser.</p>
      <div style="display:flex;flex-wrap:wrap;gap:10px">${pill('#6C9CFF', 'Hundreds of models')}${pill('#FF7A66', 'Live visual scenes')}${pill('#52D889', 'Fact-checked')}</div>
      <div style="display:flex;gap:24px;font-family:'JetBrains Mono',monospace;font-size:13px;color:#8B90A0;letter-spacing:.08em">
        <span>OPEN SOURCE</span><span>SELF-HOST</span><span>CLI + MCP</span><span>MIT</span></div>
    </div>
    <img class="frame" src="${inline(join(assets, 'frame.webp'))}" alt="">
    ${phone(HERO_PHONES[0], 'left:636px;top:262px')}
    ${phone(HERO_PHONES[1], 'left:1040px;top:226px')}
  </div></body></html>`;
}

async function captureHero(browser: Browser, encoder: Page): Promise<void> {
  const html = heroHtml();
  for (const scale of [2, 1]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 640 }, deviceScaleFactor: scale });
    await page.setContent(html, { waitUntil: 'networkidle' });
    await settle(page, 300);
    if (scale === 2) {
      const png = await page.screenshot({ type: 'png' });
      save(join(assets, 'hero.webp'), await encode(encoder, png, 'image/webp', 0.92));
    } else {
      // GitHub's social preview and the site's og:image: JPEG, 1280×640, under 1 MB.
      save(join(assets, 'social-preview.jpg'), await page.screenshot({ type: 'jpeg', quality: 90 }));
    }
    await page.close();
  }
}

// --- Main --------------------------------------------------------------------------------

// A full run starts from an empty folder, so no stale screens stay behind.
if (ONLY.length === 0) rmSync(screens, { recursive: true, force: true });
mkdirSync(screens, { recursive: true });
const channel = process.env.SCREENSHOT_CHANNEL ?? 'chrome';
const browser = await chromium.launch(channel === 'chromium' ? {} : { channel });
try {
  const encoder = await browser.newPage();
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
    const { debate, timeline } = await pickDebate(context);
    const shooter = new Shooter(encoder);

    await captureWizard(context, shooter, debate);
    if (wanted('live')) await captureLive(context, shooter, debate);
    await captureDebate(context, shooter, debate, timeline);
    await capturePublic(context, shooter);
    if (wanted('frame')) {
      const frame = await captureFrame(browser, context, debate, timeline);
      save(join(assets, 'frame.webp'), await encode(encoder, frame, 'image/webp', 0.9));
    }
  }
  // Composed from the files on disk, so ONLY=hero redraws it without shooting again.
  if (wanted('hero')) await captureHero(browser, encoder);
} finally {
  await browser.close();
}
