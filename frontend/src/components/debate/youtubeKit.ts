import type { Timeline } from '../../api/timeline';
import type { DebateDetail } from '../../api/types';
import { APP_NAME } from '../../lib/brand';
import { formatDuration, shortModelName } from '../../lib/format';
import { modelAuthor } from '../../lib/modelIcons';
import { videoChapters, youtubeChapters, type SpeakerInfo } from './helpers';

const TITLE_MAX = 100; // YouTube's limit
const ROUTERS = new Set(['openrouter']); // "openrouter/free" is not a model worth a tag

const truncate = (text: string, max: number) => (text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`);

const hashtag = (text: string) =>
  `#${text
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join('')}`;

const versus = (debaters: SpeakerInfo[]) => debaters.map((d) => d.name).join(' vs ');

export const youtubeTitle = (topic: string, debaters: SpeakerInfo[]) => {
  const head = debaters.length > 1 ? `${versus(debaters)}: ` : '';
  const full = `${head}${topic} | AI Debate`;
  if (full.length <= TITLE_MAX) return full;
  return truncate(`${head}${topic}`, TITLE_MAX);
};

export const youtubeDescription = (debate: DebateDetail, lineup: SpeakerInfo[], timeline: Timeline | null) => {
  const topic = debate.settings.topic || debate.title || 'AI debate';
  const debaters = lineup.filter((s) => s.tag !== 'HOST' && s.tag !== 'JUDGE');
  const host = lineup.find((s) => s.tag === 'HOST');
  const parts: string[] = [];
  if (debate.settings.description?.trim()) parts.push(debate.settings.description.trim());
  parts.push(
    `${debaters.length > 1 ? `${versus(debaters)} — AI models with opposing briefs — debate` : 'AI models debate'} “${topic}”. ${host ? `${host.name} moderates and an` : 'An'} AI judge weighs the arguments and gives the verdict. Who argued better?`,
  );
  parts.push(['Debaters', ...debaters.map((d) => `• ${d.name} (${d.tag}) — ${shortModelName(d.model)}`)].join('\n'));
  if (timeline) {
    const { chapters, totalMs } = videoChapters(timeline, 'long', 0);
    const lines = youtubeChapters(chapters, totalMs);
    if (lines.length > 0) parts.push(['Chapters', ...lines].join('\n'));
  }
  if (debate.is_public && debate.share_url) parts.push(`Watch the transcript and vote: ${debate.share_url}`);
  parts.push(`Made with ${APP_NAME} · ${window.location.host}`);
  return parts.join('\n\n');
};

export const youtubeTags = (debate: DebateDetail, lineup: SpeakerInfo[]) => {
  const tags = ['#AIDebate'];
  if (debate.category) tags.push(hashtag(debate.category));
  for (const s of lineup) {
    if (!s.model || ROUTERS.has(modelAuthor(s.model))) continue;
    tags.push(hashtag(shortModelName(s.model)));
  }
  tags.push(hashtag(APP_NAME));
  return [...new Set(tags)].slice(0, 15);
};

// --- Thumbnails --------------------------------------------------------------------

export interface ThumbVariant {
  id: string;
  /** Background: a CSS colour or a painter for gradients. */
  paint: (ctx: CanvasRenderingContext2D, w: number, h: number) => void;
  color: string;
  tagColor: string;
  text: string;
  tag: string;
}

export const THUMB_W = 1280;
export const THUMB_H = 720;

export const thumbnailVariants = (topic: string, debaters: SpeakerInfo[], timeline: Timeline | null, durationMs: number | null): ThumbVariant[] => {
  const names = versus(debaters.slice(0, 2)) || 'AI vs AI';
  const hook = timeline?.highlights[0]?.hook?.trim();
  return [
    {
      id: 'accent',
      paint: (ctx, w, h) => {
        ctx.fillStyle = '#D9FF3D';
        ctx.fillRect(0, 0, w, h);
      },
      color: '#0A0B0F',
      tagColor: '#3A4410',
      text: topic,
      tag: `${names} · AI debate`,
    },
    {
      id: 'split',
      paint: (ctx, w, h) => {
        // A 100° split like the mockup: blue on the left, red on the right.
        const skew = h * Math.tan((10 * Math.PI) / 180);
        ctx.fillStyle = '#B23A2C';
        ctx.fillRect(0, 0, w, h);
        ctx.fillStyle = '#2B4AA8';
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(w / 2 + skew / 2, 0);
        ctx.lineTo(w / 2 - skew / 2, h);
        ctx.lineTo(0, h);
        ctx.closePath();
        ctx.fill();
      },
      color: '#FFFFFF',
      tagColor: 'rgba(255,255,255,0.75)',
      text: names,
      tag: hook && hook.length <= 60 ? hook : topic,
    },
    {
      id: 'glow',
      paint: (ctx, w, h) => {
        ctx.fillStyle = '#0A0B0F';
        ctx.fillRect(0, 0, w, h);
        const g = ctx.createRadialGradient(w * 0.85, h * 0.1, 0, w * 0.85, h * 0.1, w * 0.75);
        g.addColorStop(0, '#4a3410');
        g.addColorStop(1, 'rgba(10,11,15,0)');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      },
      color: '#FFC46B',
      tagColor: '#8B90A0',
      text: hook || topic,
      tag: `AI debate${durationMs ? ` · ${formatDuration(durationMs)}` : ''}`,
    },
  ];
};

const DISPLAY = '"Bricolage Grotesque", "DM Sans", system-ui, sans-serif';
const MONO = '"JetBrains Mono", ui-monospace, monospace';

const wrap = (ctx: CanvasRenderingContext2D, text: string, maxWidth: number) => {
  const lines: string[] = [];
  let line = '';
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(next).width > maxWidth) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
};

const setSpacing = (ctx: CanvasRenderingContext2D, value: string) => {
  if ('letterSpacing' in ctx) ctx.letterSpacing = value;
};

/** Draws a 1280×720 thumbnail: a mono tag line over a big uppercase headline, bottom-left. */
export const renderThumbnail = async (v: ThumbVariant): Promise<Blob> => {
  await Promise.all([document.fonts.load(`800 100px ${DISPLAY}`), document.fonts.load(`500 30px ${MONO}`)]).catch(() => undefined);
  const canvas = document.createElement('canvas');
  canvas.width = THUMB_W;
  canvas.height = THUMB_H;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas is not available');
  v.paint(ctx, THUMB_W, THUMB_H);

  const padX = 64;
  const padBottom = 60;
  const maxWidth = THUMB_W * 0.8;
  const text = v.text.toUpperCase();
  let size = 132;
  let lines: string[] = [];
  for (; size >= 52; size -= 4) {
    ctx.font = `800 ${size}px ${DISPLAY}`;
    setSpacing(ctx, `${-0.035 * size}px`);
    lines = wrap(ctx, text, maxWidth);
    const widest = Math.max(...lines.map((l) => ctx.measureText(l).width));
    if (lines.length <= 4 && lines.length * size * 0.95 <= THUMB_H * 0.62 && widest <= THUMB_W - 2 * padX) break;
  }
  if (lines.length > 4) lines = [...lines.slice(0, 3), `${lines[3]}…`];

  ctx.fillStyle = v.color;
  ctx.textBaseline = 'alphabetic';
  const lineHeight = size * 0.95;
  const lastBaseline = THUMB_H - padBottom;
  lines.forEach((line, i) => ctx.fillText(line, padX, lastBaseline - (lines.length - 1 - i) * lineHeight));

  const tagSize = 30;
  ctx.font = `500 ${tagSize}px ${MONO}`;
  setSpacing(ctx, `${0.1 * tagSize}px`);
  ctx.fillStyle = v.tagColor;
  let tag = v.tag.toUpperCase();
  while (tag.length > 4 && ctx.measureText(tag).width > THUMB_W - 2 * padX) tag = `${tag.slice(0, -2).trimEnd()}…`;
  ctx.fillText(tag, padX, lastBaseline - (lines.length - 1) * lineHeight - size * 0.82 - 24);

  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not draw the thumbnail'))), 'image/png'));
};
