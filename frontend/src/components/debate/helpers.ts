import type { Timeline } from '../../api/timeline';
import type { DebateDetail, Participant, Turn } from '../../api/types';
import { FREE_ROUTER_ID } from '../../lib/modelNames';
import { JUDGE_COLOR, TURN_TYPE_LABELS, isErrorTurn, roleTag, roundLabel, speakerColor, speakerColorByName, splitEmotionTag } from '../../lib/format';
import { INTRO_MS, SHORT_HOOK_MS } from '../../video/constants';
import { frameToMs, highlightRange, longDurationInFrames, shortDurationInFrames } from '../../video/utils';

export type VideoFormat = 'long' | 'short';

const MIN_PIN_WORDS = 20; // mirror backend services/free_router.py
const NON_CHAT_MARKERS = ['guard', 'safety', 'moderation'];

/**
 * A live turn of a Free Router participant pins the free model it was routed to (the worker does
 * the same, backend services/free_router.py), so the cast shows it before the page reloads.
 * Classifiers and stub answers do not pin (the router may pick a content-safety model).
 */
export const pinRoutedModel = (participants: Participant[], turn: Turn): Participant[] => {
  const used = turn.model_used;
  if (turn.error || !used || used === FREE_ROUTER_ID || !used.endsWith(':free')) return participants;
  if (turn.text.split(/\s+/).filter(Boolean).length < MIN_PIN_WORDS || NON_CHAT_MARKERS.some((m) => used.toLowerCase().includes(m))) return participants;
  const index = isJudgeTurn(turn) ? participants.findIndex((p) => p.role === 'moderator') : participants.findIndex((p, i) => (p.id ?? `participant_${i}`) === turn.speaker_id);
  if (index < 0 || participants[index].model !== FREE_ROUTER_ID) return participants;
  return participants.map((p, i) => (i === index ? { ...p, model: used, router: FREE_ROUTER_ID } : p));
};

/** Colour for a turn: by speaker id when present, otherwise by name (older debates). */
export const turnColor = (turn: Pick<Turn, 'speaker_id' | 'speaker_name' | 'turn_type'>, participants: Participant[]) => {
  if (turn.turn_type === 'verdict' || turn.speaker_id === 'judge') return JUDGE_COLOR;
  if (turn.speaker_id) return speakerColor(turn.speaker_id, participants);
  return speakerColorByName(turn.speaker_name, participants);
};

export const isJudgeTurn = (turn: Pick<Turn, 'speaker_id' | 'turn_type'>) => turn.turn_type === 'verdict' || turn.speaker_id === 'judge';

/** Name shown for a turn's speaker ("⚖️ Verdict" turns read as the judge). */
export const speakerTitle = (turn: Pick<Turn, 'speaker_id' | 'turn_type' | 'speaker_name'>) => (isJudgeTurn(turn) ? 'The Judge' : turn.speaker_name);

export const turnTypeLabel = (turnType: string, roundId: string) => TURN_TYPE_LABELS[turnType] ?? roundLabel(roundId);

export const msLabel = (ms: number) => {
  const s = Math.floor(Math.max(0, ms) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

/** "en-GB-SoniaNeural" -> "Sonia"; opaque provider ids are hidden. */
export const prettyVoice = (voiceId: string | null | undefined): string | null => {
  if (!voiceId) return null;
  const edge = voiceId.match(/^[a-z]{2,3}-[A-Za-z]{2,4}-([A-Za-z]+?)(?:Multilingual)?Neural$/);
  if (edge) return edge[1];
  if (/^[A-Za-z0-9]{16,}$/.test(voiceId)) return null;
  return voiceId;
};

/** "en-US-JennyNeural" -> "Jenny · en-US" (Edge voices carry their locale). */
export const voiceLabel = (voiceId: string | null | undefined): string | null => {
  const name = prettyVoice(voiceId);
  const locale = voiceId?.match(/^([a-z]{2,3}-[A-Za-z]{2,4})-/)?.[1];
  return name && locale ? `${name} · ${locale}` : name;
};

// --- Speakers ------------------------------------------------------------------

export interface SpeakerInfo {
  id: string;
  name: string;
  color: string;
  model: string;
  /** HOST / PRO / CON / SIDE 3 / JUDGE */
  tag: string;
  voice: string | null;
  tokens: number;
}

/** Everyone who speaks in the debate, the judge last. */
export const speakerLineup = (debate: Pick<DebateDetail, 'participants' | 'turns' | 'media_plan'>, timeline: Timeline | null): SpeakerInfo[] => {
  const { participants, turns } = debate;
  const tokens = new Map<string, number>();
  for (const t of turns) {
    const id = isJudgeTurn(t) ? 'judge' : (t.speaker_id ?? t.speaker_name);
    tokens.set(id, (tokens.get(id) ?? 0) + (t.usage?.total_tokens ?? 0));
  }
  const voiceOf = (id: string, fallback: string | null) => voiceLabel(timeline?.speakers.find((s) => s.id === id)?.voice_id ?? debate.media_plan?.voices[id] ?? fallback);
  const people = participants.map((p, i): SpeakerInfo => {
    const id = p.id ?? `participant_${i}`;
    return {
      id,
      name: p.name ?? 'Speaker',
      color: speakerColor(id, participants),
      model: p.model,
      tag: roleTag(p, participants),
      voice: voiceOf(id, p.voice_name),
      tokens: tokens.get(id) ?? tokens.get(p.name ?? '') ?? 0,
    };
  });
  const verdictTurn = turns.find(isJudgeTurn);
  const hasJudge = Boolean(verdictTurn) || Boolean(timeline?.speakers.some((s) => s.role === 'judge')) || Boolean(debate.media_plan?.voices.judge);
  if (!hasJudge) return people;
  const moderator = participants.find((p) => p.role === 'moderator');
  return [
    ...people,
    {
      id: 'judge',
      name: 'The Judge',
      color: JUDGE_COLOR,
      model: verdictTurn?.model_used || moderator?.model || '',
      tag: 'JUDGE',
      voice: voiceOf('judge', null),
      tokens: tokens.get('judge') ?? 0,
    },
  ];
};

/** Speaker of a turn in the lineup (by id, then by name for older debates). */
export const speakerOfTurn = (lineup: SpeakerInfo[], turn: Pick<Turn, 'speaker_id' | 'speaker_name' | 'turn_type'>) =>
  isJudgeTurn(turn) ? lineup.find((s) => s.id === 'judge') : (lineup.find((s) => s.id === turn.speaker_id) ?? lineup.find((s) => s.name === turn.speaker_name));

// --- Video chapters ------------------------------------------------------------

export interface Chapter {
  seq: number;
  /** On the video's own clock (the intro / hook is folded into the first turn, the outro into the last). */
  startMs: number;
  endMs: number;
  color: string;
  speaker: string;
  label: string;
}

/** The turns of the long video or of a Short as chapters, plus the video's length. */
export const videoChapters = (timeline: Timeline, format: VideoFormat, highlightIndex: number): { chapters: Chapter[]; totalMs: number } => {
  const colorOf = (id: string) => timeline.speakers.find((s) => s.id === id)?.color ?? '#8B90A0';
  const isLong = format === 'long';
  const range = isLong ? { start_ms: 0, end_ms: timeline.total_ms } : highlightRange(timeline, highlightIndex);
  const offset = isLong ? INTRO_MS : SHORT_HOOK_MS - range.start_ms;
  const totalMs = frameToMs(isLong ? longDurationInFrames(timeline) : shortDurationInFrames(timeline, highlightIndex));
  const segments = timeline.segments.filter((s) => s.end_ms > range.start_ms && s.start_ms < range.end_ms);
  const chapters = segments.map((seg, i): Chapter => {
    const next = segments[i + 1];
    return {
      seq: seg.seq_index,
      startMs: i === 0 ? 0 : offset + seg.start_ms,
      endMs: next ? offset + next.start_ms : totalMs,
      color: colorOf(seg.speaker_id),
      speaker: seg.speaker_id === 'judge' ? 'The Judge' : seg.speaker_name,
      label: turnTypeLabel(seg.turn_type, seg.round_id),
    };
  });
  return { chapters, totalMs };
};

export const chapterAt = (chapters: Chapter[], ms: number) => {
  for (let i = chapters.length - 1; i >= 0; i--) if (ms >= chapters[i].startMs) return i;
  return 0;
};

/** YouTube chapters: the first at 0:00, each at least 10 s long (shorter turns merge into the one before). */
export const youtubeChapters = (chapters: Chapter[], totalMs: number) => {
  const kept: Chapter[] = [];
  for (const ch of chapters) {
    const last = kept.at(-1);
    if (!last || ch.startMs - last.startMs >= 10_000) kept.push(ch);
  }
  while (kept.length > 1 && totalMs - (kept.at(-1)?.startMs ?? 0) < 10_000) kept.pop();
  return kept.length >= 3 ? kept.map((ch) => `${msLabel(ch.startMs)} ${ch.speaker} — ${ch.label}`) : [];
};

// --- Text exports --------------------------------------------------------------

const srtTime = (ms: number) => {
  const t = Math.max(0, Math.round(ms));
  const h = Math.floor(t / 3_600_000);
  const m = Math.floor((t % 3_600_000) / 60_000);
  const s = Math.floor((t % 60_000) / 1000);
  const pad = (n: number, w = 2) => String(n).padStart(w, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad(t % 1000, 3)}`;
};

const bare = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');

/** Timed words with the punctuation of the segment text (TTS timings often drop it). */
const punctuatedWords = (seg: Timeline['segments'][number]) => {
  const tokens = seg.text.split(/\s+/).filter(Boolean);
  let j = 0;
  return seg.words.map((word) => {
    const key = bare(word.w);
    for (let k = j; k < Math.min(tokens.length, j + 4); k++) {
      if (key && bare(tokens[k]) === key) {
        j = k + 1;
        return { ...word, w: tokens[k] };
      }
    }
    return word;
  });
};

/** Subtitles for the long video (word timings shifted by the intro card). */
export const timelineSrt = (timeline: Timeline) => {
  const cues: string[] = [];
  for (const seg of timeline.segments) {
    let line: typeof seg.words = [];
    const flush = () => {
      if (line.length === 0) return;
      const start = INTRO_MS + seg.start_ms + line[0].s;
      const end = Math.max(INTRO_MS + seg.start_ms + (line.at(-1)?.e ?? 0), start + 400);
      cues.push(`${cues.length + 1}\n${srtTime(start)} --> ${srtTime(end)}\n${line.map((w) => w.w).join(' ')}\n`);
      line = [];
    };
    for (const word of punctuatedWords(seg)) {
      const text = [...line, word].map((w) => w.w).join(' ');
      // A sentence's last word may stretch the line a little instead of standing alone.
      const ends = /[.!?…]$/.test(word.w) && text.length <= 52;
      if (line.length > 0 && !ends && (line.length >= 8 || text.length > 42)) flush();
      line.push(word);
      if (/[.!?…]$/.test(word.w)) flush();
    }
    flush();
  }
  return cues.join('\n');
};

/** Plain-text transcript: "Speaker: text" per turn. */
export const transcriptText = (title: string, turns: Turn[]) =>
  [
    title,
    '',
    ...turns.filter((t) => !isErrorTurn(t)).map((t) => `${speakerTitle(t)}: ${splitEmotionTag(t.text).body.trim()}`),
  ].join('\n\n');

/** Markdown export of a debate. */
export const debateMarkdown = (title: string, createdAt: string, status: string, participants: Participant[], turns: Turn[]) => {
  const lines: string[] = [
    `# ${title}`,
    `Date: ${new Date(createdAt).toLocaleString()}`,
    `Status: ${status}`,
    '',
    '## Participants',
    ...participants.map((p) => `- ${p.role}: ${p.name} (${p.model})`),
    '',
    '---',
    '',
  ];
  for (const turn of turns) {
    lines.push(`### ${turn.speaker_name}`, '', turn.error ? `_Error: ${turn.error}_` : turn.text, '');
  }
  return lines.join('\n');
};

export const downloadText = (text: string, fileName: string, type = 'text/markdown') => downloadBlob(new Blob([text], { type }), fileName);

export const downloadBlob = (blob: Blob, fileName: string) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};
