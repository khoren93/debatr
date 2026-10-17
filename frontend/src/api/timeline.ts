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
}

export interface TimelineSegment {
  seq_index: number;
  speaker_id: string;
  speaker_name: string;
  round_id: string;
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

export interface TimelineVerdict {
  seq_index: number;
  winner_id: string | null;
  winner_name: string | null;
}

export interface Timeline {
  version: 1;
  debate_id: string;
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
}
