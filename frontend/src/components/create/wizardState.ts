import type {
  DebateConfig,
  DebateDetail,
  DebaterSide,
  FormatId,
  FreeDebates,
  ImageSource,
  LengthPreset,
  MediaOutput,
  ModelInfo,
  NewsContext,
  OutputStyle,
  ParticipantRole,
  TTSProviderName,
  VideoQuality,
  VoiceInfo,
} from '../../api/types';
import { STYLE_PRESETS, applyStyle, type PersonaStyle } from '../../data/styles';
import { HOST_COLOR, debaterColor } from '../../lib/format';
import { FLOWS, FORMAT_IDS, FORMATS, flowOf, formatSpec, type FormatSpec } from '../../lib/formats';
import { getLocalKey, setLocalKey } from '../../lib/localKeys';
import { FREE_ROUTER_ID, speakerNames } from '../../lib/modelNames';

export const WIZARD_STORAGE_KEY = 'debatr.wizard.v1';

export type WizardStep = 1 | 2 | 3;
export const STEP_LABELS: readonly string[] = ['Topic', 'Speakers', 'Review'];
export const LAST_STEP: WizardStep = 3;

/** The widest ranges of any format (stored states are clamped to them, then to their format). */
export const MIN_ROUNDS = 1;
export const MAX_ROUNDS = 5;
export const MIN_DEBATERS = 2;
export const MAX_DEBATERS = 4;
export const MIN_TOPIC_LENGTH = 4;
/** The topic is drawn on the video, where 150 characters fit in three lines (mirrors
 *  backend schemas.TOPIC_MAX_LENGTH; older debates may hold longer ones). */
export const TOPIC_MAX_LENGTH = 150;
const clipTopic = (topic: string) => (topic.length > TOPIC_MAX_LENGTH ? topic.slice(0, TOPIC_MAX_LENGTH).trimEnd() : topic);

/** Speakers have no name fields: the host is "The Host" ("The MC"), debaters are named after their models. */
export interface Speaker {
  /** Stable React key (survives reordering / removal). */
  key: string;
  role: ParticipantRole;
  /** Empty string = "use the default free model" (resolved when the catalogue loads). */
  model_id: string;
  prompt: string;
  /** Debaters: for / against the topic or a view of their own (null for the host). */
  side: DebaterSide | null;
}

/** A trending topic's news story; `topic_id` (trending topic) only highlights its card. */
export type NewsPick = NewsContext & { topic_id?: string };

/** The debate this one remixes: sent as `remix_of`, so a translation stays in its topic. */
export interface RemixPick {
  id: string;
  topic: string;
}

export interface WizardState {
  step: WizardStep;
  /** Show format (lib/formats): seats, limits, how it is voiced. */
  format: FormatId;
  topic: string;
  /** The user's angle for the models (optional). */
  description: string;
  /**
   * Story of the picked trending topic, null for an own topic. While set, `topic` is that topic's
   * question unchanged (editing it unlinks the story) and the brief always goes to the models.
   */
  news: NewsPick | null;
  /** English language name ("Russian"), the value the backend expects. */
  language: string;
  num_rounds: number;
  length_preset: LengthPreset;
  output_style: OutputStyle;
  /** Moderator first, then the debaters in order. */
  speakers: Speaker[];
  provider: TTSProviderName;
  /**
   * Explicit voice choices keyed by speaker id (`participant_i` / `judge`).
   * Ids without a choice (or whose voice is not in the current catalogue) fall back to the
   * provider defaults — see {@link resolveVoices}.
   */
  voices: Record<string, string>;
  /** Formats with a generated track (rap battle): flow per debater id, in place of a voice. */
  flows: Record<string, string>;
  outputs: MediaOutput[];
  quality: VideoQuality;
  /** Charts / drawn scenes, designed live after every turn and shown in the video. */
  visuals: boolean;
  /** Pictures among the scenes: free photos or AI images (paid from the balance). */
  images: ImageSource;
  /** Web fact-check of the figures and quotes in the scenes (paid like the debate). */
  fact_check: boolean;
  /** Publish to the gallery once finished and approved by the AI check. */
  auto_publish: boolean;
  /** Set by "Remix"; the topic is a version of this debate's topic while the question (or its
   *  translation) stays the same (backend services/motions). */
  remix: RemixPick | null;
}

// --- Static option lists -----------------------------------------------------

export const LANGUAGES: { value: string; label: string }[] = [
  { value: 'English', label: 'English' },
  { value: 'Russian', label: 'Русский' },
  { value: 'Spanish', label: 'Español' },
  { value: 'French', label: 'Français' },
  { value: 'German', label: 'Deutsch' },
  { value: 'Italian', label: 'Italiano' },
  { value: 'Portuguese', label: 'Português' },
  { value: 'Chinese', label: '中文' },
  { value: 'Japanese', label: '日本語' },
  { value: 'Korean', label: '한국어' },
  { value: 'Ukrainian', label: 'Українська' },
  { value: 'Armenian', label: 'Հայերեն' },
  { value: 'Polish', label: 'Polski' },
  { value: 'Turkish', label: 'Türkçe' },
  { value: 'Arabic', label: 'العربية' },
  { value: 'Hindi', label: 'हिन्दी' },
  { value: 'Dutch', label: 'Nederlands' },
];

export const languageLabel = (value: string) => LANGUAGES.find((l) => l.value === value)?.label ?? value;

/** Map free-text / legacy values ("english", "ru") onto the canonical English name. */
const normalizeLanguage = (value: string, fallback: string) => {
  const key = value.trim().toLowerCase();
  if (!key) return fallback;
  return LANGUAGES.find((l) => l.value.toLowerCase() === key || l.label.toLowerCase() === key)?.value ?? value.trim();
};

/** Reply length presets; what each one means depends on the format (`FormatSpec.lengthHints`). */
export const LENGTH_OPTIONS: { value: LengthPreset; label: string }[] = [
  { value: 'very_short', label: 'Very short' },
  { value: 'short', label: 'Short' },
  { value: 'medium', label: 'Medium' },
  { value: 'long', label: 'Long' },
];
const LENGTH_VALUES = LENGTH_OPTIONS.map((o) => o.value);

export const lengthOption = (value: LengthPreset) => LENGTH_OPTIONS.find((o) => o.value === value) ?? LENGTH_OPTIONS[2];

/** Limits of debates on free models (accounts without credits or an own key); null: none. */
export type FreeLimits = FreeDebates | null;

export const roundsAllowed = (free: FreeLimits, rounds: number) => !free?.max_rounds || rounds <= free.max_rounds;
export const lengthAllowed = (free: FreeLimits, length: LengthPreset) => !free?.lengths.length || free.lengths.includes(length);
export const maxDebatersFor = (spec: FormatSpec, free: FreeLimits) => (free?.max_debaters ? Math.min(spec.maxDebaters, free.max_debaters) : spec.maxDebaters);

/** Rounds and reply length within the limits: what the wizard shows and sends. The choice
 * stays in the state, so credits or an own key bring it back. */
export const withinFreeLimits = (state: WizardState, free: FreeLimits): WizardState => {
  if (!free) return state;
  const num_rounds = roundsAllowed(free, state.num_rounds) ? state.num_rounds : free.max_rounds;
  const length_preset = lengthAllowed(free, state.length_preset) ? state.length_preset : free.lengths[free.lengths.length - 1];
  return { ...state, num_rounds, length_preset };
};

/** "up to 3 rounds · very short or short replies · 5 a day" */
export const freeLimitsText = (free: FreeDebates) => {
  const lengths = free.lengths.map((l) => lengthOption(l).label.toLowerCase());
  return [
    free.max_rounds ? `up to ${free.max_rounds} ${free.max_rounds === 1 ? 'round' : 'rounds'}` : '',
    lengths.length ? `${lengths.length > 1 ? `${lengths.slice(0, -1).join(', ')} or ${lengths[lengths.length - 1]}` : lengths[0]} replies` : '',
    free.per_day ? `${free.per_day} a day` : '',
  ]
    .filter(Boolean)
    .join(' · ');
};

export const OUTPUT_OPTIONS: { value: MediaOutput; label: string; text: string; icon: { w: number; h: number; color: string } }[] = [
  { value: 'audio', label: 'Audio', text: 'MP3 · mixed track', icon: { w: 20, h: 20, color: '#FFC46B' } },
  { value: 'video', label: 'YouTube video', text: '16:9 · captions', icon: { w: 24, h: 14, color: '#D9FF3D' } },
  { value: 'short', label: 'Short', text: '9:16 · hook + captions', icon: { w: 12, h: 22, color: '#6C9CFF' } },
];
const OUTPUT_VALUES = OUTPUT_OPTIONS.map((o) => o.value);

export const QUALITY_OPTIONS: { value: VideoQuality; label: string }[] = [
  { value: '720p', label: '720p' },
  { value: '1080p', label: '1080p' },
  { value: '4k', label: '4K' },
];

// --- Defaults ----------------------------------------------------------------

let keySeq = 0;
export const speakerKey = () => `s${Date.now().toString(36)}${(keySeq++).toString(36)}`;

/** First for, second against, the rest a view of their own. The side goes to the models on its
 *  own line (backend prompt_builder), not in the persona. */
export const defaultSide = (debaterIndex: number): DebaterSide => (debaterIndex === 0 ? 'for' : debaterIndex === 1 ? 'against' : 'own');

export const SIDE_OPTIONS: { value: DebaterSide; label: string; hint: string; tag: string }[] = [
  { value: 'for', label: 'For', hint: 'Argues for the topic', tag: 'PRO' },
  { value: 'against', label: 'Against', hint: 'Argues against it', tag: 'CON' },
  { value: 'own', label: 'Own view', hint: 'A position of its own', tag: 'OWN VIEW' },
];

// Before sides, the stance was a sentence of the persona (the old wizard, the CLI's defaults).
const STANCE_SENTENCES: [RegExp, DebaterSide][] = [
  [/\s*Argue in favou?r of the topic\./i, 'for'],
  [/\s*Argue against the topic\./i, 'against'],
  [/\s*Provide a unique perspective \(Position \d+\)\./i, 'own'],
];

/** A persona from before sides: the default stance sentence becomes the side (custom stances
 *  stay in the text and the side stays unset, so the models get exactly what was written). */
export const sideFromPersona = (prompt: string): { prompt: string; side: DebaterSide | null } => {
  for (const [re, side] of STANCE_SENTENCES) {
    if (re.test(prompt)) return { prompt: prompt.replace(re, '').trim(), side };
  }
  return { prompt, side: null };
};

const styleById = (id: string): PersonaStyle => STYLE_PRESETS.find((s) => s.id === id) ?? STYLE_PRESETS[0];

export const defaultModerator = (format: FormatId = 'debate'): Speaker => ({
  key: speakerKey(),
  role: 'moderator',
  model_id: '',
  prompt: FORMATS[format].hostPrompt,
  side: null,
});

export const defaultDebater = (debaterIndex: number, format: FormatId = 'debate'): Speaker => ({
  key: speakerKey(),
  role: 'debater',
  model_id: '',
  prompt: applyStyle(FORMATS[format].debaterPrompt, styleById(debaterIndex === 1 ? 'aggressive' : 'neutral')),
  side: defaultSide(debaterIndex),
});

export const initialState = (): WizardState => ({
  step: 1,
  format: 'debate',
  topic: '',
  description: '',
  news: null,
  language: 'English',
  num_rounds: 2,
  length_preset: 'short',
  output_style: 'spoken',
  speakers: [defaultModerator(), defaultDebater(0), defaultDebater(1)],
  provider: 'edge',
  voices: {},
  flows: {},
  outputs: ['audio', 'video', 'short'],
  quality: '1080p',
  visuals: true,
  images: 'off',
  fact_check: false,
  auto_publish: true,
  remix: null,
});

// --- Speaker helpers ---------------------------------------------------------

/** Speaker id used by the media pipeline: the position in the participant list. */
export const speakerId = (index: number) => `participant_${index}`;

export const countDebaters = (speakers: Speaker[]) => speakers.filter((s) => s.role === 'debater').length;

const debaterIndexOf = (speakers: Speaker[], index: number) => countDebaters(speakers.slice(0, index));

export const speakerColorOf = (speakers: Speaker[], index: number) =>
  speakers[index].role === 'moderator' ? HOST_COLOR : debaterColor(debaterIndexOf(speakers, index));

/** The format's seat of the n-th debater (the last seat repeats). */
export const seatOf = (spec: FormatSpec, debaterIndex: number) => spec.seats[Math.min(debaterIndex, spec.seats.length - 1)];

/** Side fixed by the format's seat (rap battle: FOR / AGAINST), null where debaters pick. */
export const fixedSideOf = (speakers: Speaker[], index: number, spec: FormatSpec) =>
  speakers[index].role === 'debater' ? seatOf(spec, debaterIndexOf(speakers, index)).side : null;

/** HOST / MC, PRO / CON / OWN VIEW by side (positional for a debater without one), FOR / AGAINST
 *  on fixed seats. */
export const speakerTagOf = (speakers: Speaker[], index: number, spec: FormatSpec = FORMATS.debate) => {
  if (speakers[index].role === 'moderator') return spec.hostLabel.toUpperCase();
  const fixed = fixedSideOf(speakers, index, spec);
  if (fixed) return fixed === 'for' ? 'FOR' : 'AGAINST';
  const side = SIDE_OPTIONS.find((o) => o.value === speakers[index].side);
  if (side) return side.tag;
  const i = debaterIndexOf(speakers, index);
  if (i === 0) return 'PRO';
  if (i === 1) return 'CON';
  return `SIDE ${i + 1}`;
};

/** Index of each debater among the debaters (rapper one, two…) by speaker index. */
const rapperIndexes = (speakers: Speaker[]) => speakers.flatMap((s, i) => (s.role === 'debater' ? [i] : []));

/** The flow of every debater of a format with a generated track, by speaker id. */
export const flowsOf = (state: WizardState) =>
  Object.fromEntries(rapperIndexes(state.speakers).map((index, k) => [speakerId(index), flowOf(state.flows, speakerId(index), k).id]));

// --- Formats -----------------------------------------------------------------

/** A default prompt of another format becomes this format's (its style line stays); a prompt of
 *  the user's own stays as it is. */
const promptFor = (prompt: string, role: ParticipantRole, spec: FormatSpec) => {
  const target = role === 'moderator' ? spec.hostPrompt : spec.debaterPrompt;
  for (const other of Object.values(FORMATS)) {
    const base = role === 'moderator' ? other.hostPrompt : other.debaterPrompt;
    if (prompt.startsWith(base)) return target + prompt.slice(base.length);
  }
  return prompt;
};

/** Speakers, rounds and outputs within the format: extra debaters go, missing ones come, the
 *  rounds are clamped, and a format voiced with premium voices only always gets its audio. */
export const fitFormat = (state: WizardState): WizardState => {
  const spec = formatSpec(state.format);
  let kept = 0;
  const speakers = state.speakers.filter((s) => s.role !== 'debater' || kept++ < spec.maxDebaters);
  while (countDebaters(speakers) < spec.minDebaters) speakers.push(defaultDebater(countDebaters(speakers), spec.id));
  const outputs = spec.premiumOnly && !state.outputs.includes('audio') ? OUTPUT_VALUES.filter((o) => o === 'audio' || state.outputs.includes(o)) : state.outputs;
  return { ...state, format: spec.id, speakers, num_rounds: clamp(state.num_rounds, spec.minRounds, spec.maxRounds), outputs };
};

/** Switch the format: default prompts follow it; models, styles and the topic stay. */
export const applyFormat = (state: WizardState, format: FormatId): WizardState => {
  if (format === state.format) return state;
  const spec = FORMATS[format];
  return fitFormat({ ...state, format, speakers: state.speakers.map((s) => ({ ...s, prompt: promptFor(s.prompt, s.role, spec) })) });
};

/** On-stage name of every speaker (see lib/modelNames.speakerNames). */
export const speakerNamesOf = (speakers: Speaker[], models: ModelInfo[], defaultModelId: string, format: FormatId = 'debate') =>
  speakerNames(
    speakers.map((s) => ({ role: s.role, modelId: s.model_id || defaultModelId })),
    models,
    FORMATS[format].hostName,
  );

/** Shift `participant_i` keys down after removing the speaker at `removed`. */
export const reindexVoices = (voices: Record<string, string>, removed: number) => {
  const out: Record<string, string> = {};
  for (const [id, voice] of Object.entries(voices)) {
    const match = id.match(/^participant_(\d+)$/);
    if (!match) {
      out[id] = voice;
      continue;
    }
    const index = Number(match[1]);
    if (index === removed) continue;
    out[index > removed ? speakerId(index - 1) : id] = voice;
  }
  return out;
};

// --- Models & voices ---------------------------------------------------------

/** The free router, else the first free "xiaomi/mimo" model, else the first free model. */
export const pickDefaultModel = (models: ModelInfo[]) => {
  const free = models.filter((m) => m.is_free);
  return (free.find((m) => m.id === FREE_ROUTER_ID) ?? free.find((m) => m.id.includes('xiaomi/mimo')) ?? free[0])?.id ?? '';
};

/** Effective voice for every speaker id (+ judge): explicit choice if still valid, else the default. */
export const resolveVoices = (state: WizardState, catalogue: VoiceInfo[], defaults: Record<string, string>) => {
  const known = new Set(catalogue.map((v) => v.id));
  const ids = [...state.speakers.map((_, i) => speakerId(i)), 'judge'];
  const out: Record<string, string> = {};
  for (const id of ids) {
    const chosen = state.voices[id];
    // With an empty catalogue (still loading) keep whatever was chosen rather than dropping it.
    const voice = chosen && (known.size === 0 || known.has(chosen)) ? chosen : defaults[id];
    if (voice) out[id] = voice;
  }
  return out;
};

// --- Config <-> state --------------------------------------------------------

export interface BuildOptions {
  defaultModelId: string;
  /** Catalogue for the speaker names (lib/modelNames). */
  models: ModelInfo[];
  voices: Record<string, string>;
  provider: TTSProviderName;
  /** Browser-only keys (see lib/localKeys); sent with the request, never persisted. */
  openrouterKey?: string;
  elevenlabsKey?: string;
}

/** The linked story (`topic_id` is a wizard detail and stays in the browser). */
const newsOf = (state: WizardState): NewsContext | undefined => {
  if (!state.news?.brief.trim()) return undefined;
  const { brief, outlet, title, url, published_at } = state.news;
  return { brief: brief.trim(), outlet, title, url, published_at };
};

export const buildConfig = (state: WizardState, opts: BuildOptions): DebateConfig => {
  const spec = formatSpec(state.format);
  const names = speakerNamesOf(state.speakers, opts.models, opts.defaultModelId, spec.id);
  // A generated track carries the debaters of a music format: only the host and the judge get voices.
  const voiced = (index: number) => !spec.music || state.speakers[index]?.role !== 'debater';
  const voices = Object.fromEntries(
    Object.entries(opts.voices).filter(([id]) => {
      const match = id.match(/^participant_(\d+)$/);
      return !match || voiced(Number(match[1]));
    }),
  );
  const visuals = spec.visuals && state.visuals;
  return {
    format: spec.id,
    topic: state.topic.trim(),
    description: state.description.trim() || undefined,
    news: newsOf(state),
    language: state.language,
    num_rounds: state.num_rounds,
    length_preset: state.length_preset,
    output_style: spec.outputStyle ?? state.output_style,
    debate_preset_id: 'custom',
    participants: state.speakers.map((s, i) => ({
      role: s.role,
      model_id: s.model_id || opts.defaultModelId,
      display_name: names[i],
      persona_custom: s.prompt.trim() || undefined,
      voice_name: voiced(i) ? opts.voices[speakerId(i)] : undefined,
      side: s.role === 'debater' && spec.sides ? (s.side ?? undefined) : undefined,
    })),
    media_plan: {
      provider: opts.provider,
      model_id: 'eleven_v3',
      voices,
      outputs: state.outputs,
      quality: state.quality,
      visuals,
      images: visuals && state.outputs.includes('audio') ? state.images : 'off',
      ...(spec.music ? { flows: flowsOf(state) } : {}),
    },
    fact_check: visuals && state.fact_check,
    auto_publish: state.auto_publish,
    remix_of: state.remix?.id,
    user_provider_key: opts.openrouterKey?.trim() || undefined,
    user_tts_key: (opts.provider === 'elevenlabs' && state.outputs.includes('audio') && opts.elevenlabsKey?.trim()) || undefined,
  };
};

const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));

/** Re-open a saved configuration (draft) in the wizard. */
export const stateFromConfig = (config: DebateConfig, base: WizardState): WizardState => {
  const spec = formatSpec(config.format);
  const plan = config.media_plan ?? null;
  const entries = config.participants.map((p, index) => ({ p, index }));
  const moderator = entries.find((e) => e.p.role === 'moderator');
  const debaters = entries.filter((e) => e.p.role === 'debater').slice(0, spec.maxDebaters);
  const speakers: Speaker[] = moderator ? [] : [defaultModerator(spec.id)];
  const voices: Record<string, string> = {};
  const flows: Record<string, string> = {};
  for (const entry of [...(moderator ? [moderator] : []), ...debaters]) {
    const debater = entry.p.role === 'debater';
    const persona = entry.p.persona_custom;
    const fallbackPrompt = debater ? spec.debaterPrompt : spec.hostPrompt;
    // Configs from before sides: the default stance sentence of the persona becomes the side; a
    // stance of one's own stays in the text, without a side. No persona (a remix of someone
    // else's debate) or a format that seats the sides itself: the default side (for a switch to
    // a debate).
    const legacy = sideFromPersona(persona ?? fallbackPrompt);
    const seated = !spec.sides || persona === undefined;
    const side = (spec.sides ? entry.p.side : undefined) ?? (seated ? defaultSide(countDebaters(speakers)) : legacy.side);
    speakers.push({
      key: speakerKey(),
      role: entry.p.role,
      model_id: entry.p.model_id,
      prompt: entry.p.side || !spec.sides ? (persona ?? fallbackPrompt) : legacy.prompt,
      side: debater ? side : null,
    });
    // Voices and flows in the stored plan are keyed by the *original* participant index.
    const voice = entry.p.voice_name || plan?.voices[speakerId(entry.index)];
    if (voice) voices[speakerId(speakers.length - 1)] = voice;
    const flow = plan?.flows?.[speakerId(entry.index)];
    if (flow && FLOWS.some((f) => f.id === flow)) flows[speakerId(speakers.length - 1)] = flow;
  }
  while (countDebaters(speakers) < spec.minDebaters) speakers.push(defaultDebater(countDebaters(speakers), spec.id));
  if (plan?.voices.judge) voices.judge = plan.voices.judge;
  return fitFormat({
    ...base,
    step: 1,
    format: spec.id,
    topic: clipTopic(config.topic),
    description: config.description ?? '',
    news: config.news?.brief ? { ...config.news } : null,
    language: normalizeLanguage(config.language, base.language),
    num_rounds: clamp(config.num_rounds, MIN_ROUNDS, MAX_ROUNDS),
    length_preset: LENGTH_VALUES.includes(config.length_preset) ? config.length_preset : base.length_preset,
    // A format that writes in its own style says nothing about the wizard's choice.
    output_style: spec.outputStyle ? base.output_style : (config.output_style ?? 'spoken'),
    speakers,
    // The format picks the engine of a premium-only show: keep the wizard's for a switch back.
    provider: spec.premiumOnly ? base.provider : (plan?.provider ?? 'edge'),
    voices,
    flows,
    outputs: plan?.outputs ?? base.outputs,
    quality: plan?.quality ?? base.quality,
    // Formats without scenes store them off: keep the default for a switch to a debate.
    visuals: spec.visuals ? (plan?.visuals ?? base.visuals) : base.visuals,
    images: spec.visuals ? (plan?.images ?? base.images) : base.images,
    fact_check: spec.visuals ? (config.fact_check ?? base.fact_check) : base.fact_check,
    auto_publish: config.auto_publish ?? base.auto_publish,
  });
};

const isRole = (role: string): role is ParticipantRole => role === 'moderator' || role === 'debater';

/**
 * Configuration to start a "remix" of an existing debate from: the owner gets their full stored
 * config; everyone else gets the public settings and lineup (custom personas stay private).
 */
export const configFromDebate = (debate: DebateDetail): DebateConfig => {
  if (debate.config) return debate.config;
  const { settings } = debate;
  return {
    format: formatSpec(settings.format).id,
    topic: settings.topic || debate.title || '',
    description: settings.description ?? undefined,
    news: settings.news ?? undefined,
    language: settings.language,
    num_rounds: settings.num_rounds,
    length_preset: LENGTH_VALUES.includes(settings.length_preset as LengthPreset) ? (settings.length_preset as LengthPreset) : 'medium',
    intensity: settings.intensity,
    output_style: settings.output_style,
    participants: debate.participants
      .filter((p) => isRole(p.role))
      .map((p) => ({
        role: p.role as ParticipantRole,
        model_id: p.router || p.model, // a remix asks the Free Router again
        display_name: p.name?.trim() || (p.role === 'moderator' ? 'The Host' : 'Debater'),
        voice_name: p.voice_name ?? undefined,
        side: p.role === 'debater' ? (p.side ?? undefined) : undefined,
      })),
    media_plan: debate.media_plan ?? undefined,
  };
};

// --- Validation --------------------------------------------------------------

export interface ValidationContext {
  defaultModelId: string;
  /** While the catalogue loads, an unset model is not an error yet. */
  modelsLoading: boolean;
}

export const topicValid = (state: WizardState) => state.topic.trim().length >= MIN_TOPIC_LENGTH;

export const speakerModelOk = (speaker: Speaker, ctx: ValidationContext) =>
  Boolean(speaker.model_id || ctx.defaultModelId) || ctx.modelsLoading;

export const speakersValid = (state: WizardState, ctx: ValidationContext) => state.speakers.every((s) => speakerModelOk(s, ctx));

export const stepValid = (state: WizardState, step: WizardStep, ctx: ValidationContext) => {
  if (step === 1) return topicValid(state);
  if (step === 2) return speakersValid(state, ctx);
  return true;
};

/** Highest step the user may jump to: every step before it must be valid. */
export const maxReachableStep = (state: WizardState, ctx: ValidationContext): WizardStep => {
  if (!topicValid(state)) return 1;
  if (!speakersValid(state, ctx)) return 2;
  return 3;
};

// --- Persistence -------------------------------------------------------------

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;
const str = (v: unknown, fallback = '') => (typeof v === 'string' ? v : fallback);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[], fallback: T): T =>
  typeof v === 'string' && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;

const sanitizeSpeakers = (raw: unknown, format: FormatId): Speaker[] => {
  const list = Array.isArray(raw) ? raw.filter(isRecord) : [];
  const toSpeaker = (s: Record<string, unknown>, role: ParticipantRole): Speaker => {
    const base = { key: str(s.key) || speakerKey(), role, model_id: str(s.model_id) };
    if (role !== 'debater') return { ...base, prompt: str(s.prompt), side: null };
    if (typeof s.side === 'string') return { ...base, prompt: str(s.prompt), side: oneOf(s.side, ['for', 'against', 'own'] as const, 'own') };
    // Stored before sides (or a stance of one's own): the default stance sentence becomes the side.
    const legacy = sideFromPersona(str(s.prompt));
    return { ...base, prompt: legacy.prompt, side: legacy.side };
  };
  const moderator = list.find((s) => s.role === 'moderator');
  const debaters = list.filter((s) => s.role === 'debater').slice(0, MAX_DEBATERS);
  const out = [moderator ? toSpeaker(moderator, 'moderator') : defaultModerator(format), ...debaters.map((d) => toSpeaker(d, 'debater'))];
  while (countDebaters(out) < MIN_DEBATERS) out.push(defaultDebater(countDebaters(out), format));
  return out;
};

const sanitizeFlows = (raw: unknown): Record<string, string> => {
  if (!isRecord(raw)) return {};
  return Object.fromEntries(Object.entries(raw).filter((e): e is [string, string] => typeof e[1] === 'string' && FLOWS.some((f) => f.id === e[1])));
};

const sanitizeVoices = (raw: unknown): Record<string, string> => {
  if (!isRecord(raw)) return {};
  const out: Record<string, string> = {};
  for (const [id, voice] of Object.entries(raw)) if (typeof voice === 'string' && voice) out[id] = voice;
  return out;
};

const sanitizeNews = (raw: unknown): NewsPick | null => {
  if (!isRecord(raw) || !str(raw.brief).trim()) return null;
  const url = str(raw.url);
  return {
    brief: str(raw.brief),
    outlet: str(raw.outlet),
    title: str(raw.title),
    url: /^https?:\/\//i.test(url) ? url : '',
    published_at: str(raw.published_at) || null,
    topic_id: str(raw.topic_id) || undefined,
  };
};

const sanitizeRemix = (raw: unknown): RemixPick | null => (isRecord(raw) && str(raw.id) ? { id: str(raw.id), topic: str(raw.topic) } : null);

const sanitizeOutputs = (raw: unknown, fallback: MediaOutput[]): MediaOutput[] => {
  if (!Array.isArray(raw)) return fallback;
  return OUTPUT_VALUES.filter((o) => raw.includes(o));
};

/** Defensive parse of a stored wizard state (older versions, hand-edited storage…). */
export const sanitizeState = (raw: unknown): WizardState => {
  const base = initialState();
  if (!isRecord(raw)) return base;
  const step = Number(raw.step);
  const rounds = Number(raw.num_rounds);
  const format = oneOf(raw.format, FORMAT_IDS, base.format);
  return fitFormat({
    // Older four-step states: "Format" and "Review" are now one step.
    step: step >= 1 ? (Math.min(LAST_STEP, Math.floor(step)) as WizardStep) : 1,
    format,
    topic: clipTopic(str(raw.topic)),
    description: str(raw.description),
    // Older states could switch the story off ("ground"): a linked topic now always sends it.
    news: raw.ground === false ? null : sanitizeNews(raw.news),
    language: normalizeLanguage(str(raw.language), base.language),
    num_rounds: Number.isFinite(rounds) ? clamp(Math.round(rounds), MIN_ROUNDS, MAX_ROUNDS) : base.num_rounds,
    length_preset: oneOf(raw.length_preset, LENGTH_VALUES, base.length_preset),
    output_style: oneOf(raw.output_style, ['spoken', 'markdown'] as const, base.output_style),
    speakers: sanitizeSpeakers(raw.speakers, format),
    provider: oneOf(raw.provider, ['edge', 'elevenlabs'] as const, base.provider),
    voices: sanitizeVoices(raw.voices),
    flows: sanitizeFlows(raw.flows),
    outputs: sanitizeOutputs(raw.outputs, base.outputs),
    quality: oneOf(raw.quality, ['720p', '1080p', '4k'] as const, base.quality),
    visuals: typeof raw.visuals === 'boolean' ? raw.visuals : base.visuals,
    images: oneOf(raw.images, ['off', 'stock', 'ai'] as const, base.images),
    fact_check: typeof raw.fact_check === 'boolean' ? raw.fact_check : base.fact_check,
    auto_publish: typeof raw.auto_publish === 'boolean' ? raw.auto_publish : base.auto_publish,
    remix: sanitizeRemix(raw.remix),
  });
};

export const loadWizardState = (): WizardState => {
  let state = initialState();
  try {
    const raw = localStorage.getItem(WIZARD_STORAGE_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      state = sanitizeState(parsed);
      // Older wizard states carried the OpenRouter key inline; move it to the key store.
      const legacyKey = parsed && typeof parsed === 'object' ? str((parsed as Record<string, unknown>).openrouterKey) : '';
      if (legacyKey.trim() && !getLocalKey('openrouter')) setLocalKey('openrouter', legacyKey);
    }
  } catch {
    /* corrupted or unavailable storage: start fresh */
  }
  if (!topicValid(state)) state = { ...state, step: 1 };
  return state;
};

export const saveWizardState = (state: WizardState) => {
  try {
    localStorage.setItem(WIZARD_STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* storage full or unavailable */
  }
};

export const clearWizardState = () => {
  try {
    localStorage.removeItem(WIZARD_STORAGE_KEY);
  } catch {
    /* storage unavailable */
  }
};
