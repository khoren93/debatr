// Mirrors backend/app/schemas/timeline.py (serialized as media/{debate_id}/timeline.json).

import type { TimelineVisual } from './visuals';

export type SpeakerRole = 'moderator' | 'debater' | 'judge';
export type Mascot = 'orb' | 'bolt' | 'cube';

export interface TimelineWord {
  w: string;
  s: number; // ms relative to the segment audio
  e: number;
}

export interface TimelineSpeaker {
  id: string;
  name: string;
  role: SpeakerRole;
  model: string;
  color: string;
  mascot: Mascot;
  avatar_url: string | null;
  voice_id: string | null;
  /** Full OpenRouter id ("openai/gpt-4o-mini") for the provider logo; missing in older timelines. */
  model_id?: string;
}

export interface TimelineSegment {
  seq_index: number;
  speaker_id: string;
  speaker_name: string;
  round_id: string;
  /** The format's name for this part of the show; absent in timelines built before formats. */
  round_label?: string | null;
  turn_type: string;
  start_ms: number; // absolute on the full track
  end_ms: number;
  audio: string;
  text: string;
  words: TimelineWord[];
  levels: number[];
  levels_hz: number;
  note: string | null;
}

export interface TimelineHighlight {
  index: number;
  title: string;
  hook: string;
  start_ms: number;
  end_ms: number;
  seq_indexes: number[];
}

/** A line that lands (a battle's punchline, a debate's zinger): the video hits it as its last
 *  word is said. Times are absolute on the full track. */
export interface TimelineMoment {
  seq_index: number;
  speaker_id: string;
  kind: 'punchline' | 'zinger';
  quote: string;
  start_ms: number;
  end_ms: number;
  big: boolean;
  funny: boolean;
}

export interface TimelineVerdict {
  seq_index: number;
  winner_id: string | null;
  winner_name: string | null;
}

/** The beat grid of a generated soundtrack (rap battle): beat k at offset_ms + k * 60000 / bpm. */
export interface TimelineBeat {
  bpm: number;
  offset_ms: number;
  /** Beats k with k % 2 === accent carry the kick (the stronger ones). */
  accent: number;
}

export interface Timeline {
  version: 1;
  debate_id: string;
  /** Show format (lib/formats); missing in timelines built before formats reached the video. */
  format?: string;
  title: string;
  topic: string;
  language: string;
  language_code: string;
  created_at: string;
  provider: string;
  model_id: string;
  speakers: TimelineSpeaker[];
  segments: TimelineSegment[];
  gap_ms: number;
  total_ms: number;
  full_audio_wav: string;
  full_audio_mp3: string;
  verdict: TimelineVerdict | null;
  highlights: TimelineHighlight[];
  /** Charts / drawn scenes synced with the speech; missing in timelines built before them. */
  visuals?: TimelineVisual[];
  stats: { chars: number; tts_ms: number; estimated_usd: number | null; cached_turns: number; visuals_usd?: number | null; images_usd?: number | null };
  /** Only a battle's generated track has one (older battle timelines too: not). */
  beat?: TimelineBeat | null;
  /** The lines the video hits, in track order; missing in timelines built before them. */
  moments?: TimelineMoment[];
  /** Crowd / studio reactions play (video/sfx.ts); missing in older timelines: the format says. */
  sfx?: boolean | null;
}
