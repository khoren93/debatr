import type { DebaterSide, FormatId, LengthPreset, OutputStyle } from '../api/types';

/**
 * Show formats as the wizard runs them. Mirrors backend `services/formats` (seats, limits, what a
 * format decides itself) and `media/music.FLOWS`; `GET /api/formats` lists the same for the CLI
 * and agents. Rounds and debaters are the wizard's own ranges (the API allows longer debates).
 */
export interface FormatSpec {
  id: FormatId;
  name: string;
  /** The show in a sentence: "Start the battle", "Your battle". */
  show: string;
  /** Badge on cards and in the video ("AI DEBATE", "RAP BATTLE"). */
  label: string;
  tagline: string;
  /** "Host", "MC". */
  hostLabel: string;
  /** The host's on-stage name (debaters are named after their models). */
  hostName: string;
  /** Debater seats in speaking order (the last one repeats); a fixed side or null (picked). */
  seats: { label: string; side: DebaterSide | null }[];
  minDebaters: number;
  maxDebaters: number;
  minRounds: number;
  maxRounds: number;
  /** Debaters pick their own side. */
  sides: boolean;
  /** Charts and sketches may accompany the speeches (and the fact-check with them). */
  visuals: boolean;
  /** Audio only with premium voices; the wizard always builds it. */
  premiumOnly: boolean;
  /** One generated track carries the debaters: each takes a flow instead of a voice. */
  music: boolean;
  /** The video plays crowd / studio reactions by default (backend Format.crowd_sounds). */
  crowdSounds: boolean;
  /** The texts are written for this style whatever the wizard says (null: the wizard's). */
  outputStyle: OutputStyle | null;
  /** "Reply length" field: its label and what each preset means here. */
  lengthLabel: string;
  lengthHints: Record<LengthPreset, string>;
  roundsHint: (rounds: number) => string;
  /** Default system prompts (the backend's fallbacks for the battle). */
  hostPrompt: string;
  debaterPrompt: string;
  /** Whose list of news topics it shows (backend `formats.topic_list_of`: its own when it writes topics its own way). */
  topicList: FormatId;
  /** Heading of the wizard's news topics and the topic field's example. */
  trendingTitle: string;
  topicPlaceholder: string;
}

export const FORMATS: Record<FormatId, FormatSpec> = {
  debate: {
    id: 'debate',
    name: 'Debate',
    show: 'debate',
    label: 'AI DEBATE',
    tagline: 'Models argue a topic for and against; the judge picks a winner.',
    hostLabel: 'Host',
    hostName: 'The Host',
    seats: [{ label: 'Debater', side: null }],
    minDebaters: 2,
    maxDebaters: 4,
    minRounds: 1,
    maxRounds: 5,
    sides: true,
    visuals: true,
    premiumOnly: false,
    music: false,
    crowdSounds: false,
    outputStyle: null,
    lengthLabel: 'Reply length',
    lengthHints: { very_short: '~50 words · best for Shorts', short: '~100 words · snappy', medium: '~250 words · in depth', long: '~250 words · in depth' },
    // What the rounds consist of (backend scheduler.build_schedule).
    roundsHint: (rounds) =>
      rounds === 1 ? 'one argument each' : `opening · ${rounds > 2 ? `${rounds > 3 ? `${rounds - 2}× ` : ''}rebuttal · ` : ''}closing`,
    hostPrompt: 'You are an impartial debate moderator. Introduce the topic, keep speakers on time, summarize each round.',
    debaterPrompt: 'You are a skilled debater.',
    topicList: 'debate',
    trendingTitle: 'Trending topics',
    topicPlaceholder: 'Are cryptocurrencies the future of finance or a bubble?',
  },
  rap_battle: {
    id: 'rap_battle',
    name: 'Rap battle',
    show: 'battle',
    label: 'RAP BATTLE',
    tagline: 'Two models trade verses over one beat; the judge scores every round.',
    hostLabel: 'MC',
    hostName: 'The MC',
    seats: [
      { label: 'Rapper One', side: 'for' },
      { label: 'Rapper Two', side: 'against' },
    ],
    minDebaters: 2,
    maxDebaters: 2,
    minRounds: 1,
    maxRounds: 3,
    sides: false,
    visuals: false,
    premiumOnly: true,
    music: true,
    crowdSounds: true,
    outputStyle: 'spoken',
    lengthLabel: 'Verse length',
    // One line per bar of the beat (backend formats/rap_battle.VERSE_LINES).
    lengthHints: { very_short: '4 lines a verse', short: '8 lines a verse', medium: '12 lines a verse', long: '12 lines a verse' },
    roundsHint: (rounds) => (rounds === 1 ? 'one verse each' : `${rounds} verses each · the second rapper opens round 2`),
    hostPrompt: 'You are a high-energy battle rap MC.',
    debaterPrompt: 'You are a sharp, witty battle rapper.',
    // Rivalries ("A or B?"): backend formats/rap_battle.topic_style.
    topicList: 'rap_battle',
    trendingTitle: 'Trending battles',
    topicPlaceholder: 'Streaming or cinema?',
  },
};

export const FORMAT_IDS = Object.keys(FORMATS) as FormatId[];

/** Unknown or missing ids run as a debate, like the backend's `format_of`. */
export const formatSpec = (id: string | null | undefined): FormatSpec => FORMATS[(id ?? '') as FormatId] ?? FORMATS.debate;

/** The format of a timeline; battles built before timelines carried it are told by their verses. */
export const timelineFormat = (timeline: { format?: string; segments: { turn_type: string }[] }): FormatSpec =>
  formatSpec(timeline.format ?? (timeline.segments.some((s) => s.turn_type === 'verse') ? 'rap_battle' : 'debate'));

/** How a rapper sounds in the generated track (backend media/music.FLOWS). */
export interface Flow {
  id: string;
  label: string;
  hint: string;
  voice: 'male' | 'female';
}

export const FLOWS: Flow[] = [
  { id: 'gritty', label: 'Gritty baritone', hint: 'Deep, slow, menacing', voice: 'male' },
  { id: 'sharp', label: 'Sharp double-time', hint: 'Bright, fast, aggressive', voice: 'female' },
  { id: 'smooth', label: 'Smooth and laid-back', hint: 'Warm, relaxed, cool', voice: 'male' },
  { id: 'fierce', label: 'Fierce and raspy', hint: 'Raspy, loud, in your face', voice: 'female' },
  { id: 'hype', label: 'High-energy hype', hint: 'High-pitched, choppy, wild', voice: 'male' },
  { id: 'cold', label: 'Cold and precise', hint: 'Calm, clipped, deadly', voice: 'female' },
];

/** Rapper One and Two: a male and a female voice (two male rappers tend to sound like one). */
export const DEFAULT_FLOWS = ['gritty', 'sharp'] as const;

export const flowById = (id: string | undefined) => FLOWS.find((f) => f.id === id);

/** The chosen flow of the rapper in seat `rapperIndex`, else its seat's default. */
export const flowOf = (flows: Record<string, string>, speakerId: string, rapperIndex: number): Flow =>
  flowById(flows[speakerId]) ?? (flowById(DEFAULT_FLOWS[rapperIndex % DEFAULT_FLOWS.length]) as Flow);
