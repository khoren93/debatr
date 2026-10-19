import type { MouseEvent, ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Timeline } from '../../api/timeline';
import type { Participant, Turn, TurnStartedEvent } from '../../api/types';
import { hideStudioMarkers, isErrorTurn, roundHeading, shortModelName, splitEmotionTag, turnErrorMessage } from '../../lib/format';
import { EmptyState, ErrorBox } from '../ui';
import { msLabel, speakerOfTurn, speakerTitle, turnColor, type SpeakerInfo } from './helpers';
import { disputesByKey, sceneCast } from './sceneBoard';
import { SpeakerTile } from './SpeakerTile';
import { TurnScenes } from './TurnScenes';
import { VerdictGate } from './VerdictTab';

export interface StreamingTurn extends TurnStartedEvent {
  text: string;
}

interface Props {
  turns: Turn[];
  streaming: StreamingTurn | null;
  participants: Participant[];
  lineup: SpeakerInfo[];
  timeline: Timeline | null;
  /** Absolute URL of the media folder ("" before the audio build): pictures in the scenes. */
  mediaBase: string;
  languageCode: string;
  markdown: boolean;
  isActive: boolean;
  /** Turn under the player's playhead ("● NOW"). */
  activeSeq?: number | null;
  /** Jump the player to a turn; rows are clickable only when set. */
  onSeek?: (seq: number) => void;
  /** Cover the judge's turn while the audience vote is blind. */
  hideVerdict?: boolean;
  onRevealVerdict?: () => void;
}

interface RowProps {
  turn: Pick<Turn, 'seq_index' | 'round_id' | 'turn_type' | 'speaker_id' | 'speaker_name' | 'text'> & Partial<Pick<Turn, 'error' | 'model_used'>>;
  participants: Participant[];
  lineup: SpeakerInfo[];
  time: string;
  markdown: boolean;
  streaming?: boolean;
  active?: boolean;
  onSeek?: () => void;
  /** The turn's visual scenes, under the text. */
  board?: ReactNode;
}

const Row = ({ turn, participants, lineup, time, markdown, streaming = false, active = false, onSeek, board }: RowProps) => {
  const speaker = speakerOfTurn(lineup, turn);
  const color = speaker?.color ?? turnColor(turn, participants);
  const model = turn.model_used || speaker?.model || '';
  const error = !streaming && isErrorTurn({ error: turn.error ?? null, text: turn.text });
  const { tone, body } = splitEmotionTag(streaming ? hideStudioMarkers(turn.text) : turn.text);
  const highlighted = active || streaming;
  const seek = (e: MouseEvent) => {
    // Selecting text or using the scene board must not move the player.
    if (!onSeek || window.getSelection()?.toString()) return;
    if ((e.target as HTMLElement).closest('button, a, [data-no-seek]')) return;
    onSeek();
  };
  return (
    <div
      id={`turn-${turn.seq_index}`}
      onClick={seek}
      className={`grid scroll-mt-24 grid-cols-[36px_minmax(0,1fr)] gap-3 rounded-[14px] border p-3.5 transition-colors ${highlighted ? 'border-white/10 bg-surface' : 'border-transparent'} ${onSeek ? 'cursor-pointer hover:bg-surface' : ''}`}
    >
      <SpeakerTile model={model} color={color} size={36} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-sm font-bold">
            {speakerTitle(turn)}
            {model && <span className="font-mono text-[11px] font-normal text-muted">{shortModelName(model)}</span>}
            {tone && <span className="rounded-[5px] bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] font-medium text-text-3">{tone}</span>}
            {streaming && <span className="rounded-[5px] bg-danger/20 px-1.5 py-0.5 font-mono text-[10px] font-medium text-[#ff9b9b]">live</span>}
          </span>
          <span className="flex items-center gap-2 font-mono text-[11px] text-dim">
            {active && <span className="tracking-[0.08em] text-accent">● NOW</span>}
            {onSeek ? (
              <button type="button" onClick={onSeek} className="hover:text-text cursor-pointer" aria-label={`Play from ${time}`}>
                {time}
              </button>
            ) : (
              time
            )}
          </span>
        </div>
        {error ? (
          <ErrorBox className="mt-2">{turnErrorMessage({ error: turn.error ?? null, text: turn.text })}</ErrorBox>
        ) : markdown && !streaming ? (
          <div className={`prose prose-invert prose-sm mt-1.5 max-w-none prose-p:my-1.5 prose-headings:my-2 prose-strong:text-text ${highlighted ? 'text-text' : 'text-text-3'}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
          </div>
        ) : (
          <p className={`mt-1.5 whitespace-pre-line text-[15px] leading-[1.6] text-pretty ${highlighted ? 'text-text' : 'text-text-3'}`}>
            {body || (streaming ? <span className="italic text-muted">Thinking…</span> : null)}
            {streaming && body && <span className="ml-1 inline-block h-4 w-2 animate-pulse-dot bg-accent align-middle" />}
          </p>
        )}
      </div>
      {/* Phones: the scenes take the full row width instead of the column next to the avatar. */}
      {!error && board && (
        <div data-no-seek className="col-span-full -mt-3 min-w-0 sm:col-start-2">
          {board}
        </div>
      )}
    </div>
  );
};

/** Transcript tab: turns grouped by round with mono headings. */
export const Transcript = ({ turns, streaming, participants, lineup, timeline, mediaBase, languageCode, markdown, isActive, activeSeq = null, onSeek, hideVerdict = false, onRevealVerdict }: Props) => {
  if (turns.length === 0 && !streaming) {
    return <EmptyState className="mt-5" title={isActive ? 'Waiting for the first speaker…' : 'No turns were recorded'} />;
  }
  const startMs = new Map<number, number>();
  timeline?.segments.forEach((s) => startMs.set(s.seq_index, s.start_ms));
  const timeFor = (seq: number) => (startMs.has(seq) ? msLabel(startMs.get(seq) ?? 0) : `#${seq + 1}`);

  const cast = sceneCast(participants, timeline, languageCode);
  const disputes = disputesByKey(turns);
  const board = (turn: Turn) => {
    const fromVideo = timeline?.visuals?.filter((v) => v.seq_index === turn.seq_index) ?? [];
    if (!turn.visuals && fromVideo.length === 0) return null;
    return <TurnScenes seq={turn.seq_index} speakerId={turn.speaker_id ?? ''} visuals={turn.visuals} timelineVisuals={fromVideo} disputes={disputes} cast={cast} mediaBase={mediaBase} />;
  };
  const rows: ReactNode[] = [];
  let lastRound: string | null = null;
  const heading = (roundId: string, turnType: string, label?: string) => (
    <div key={`h-${roundId}-${turnType}`} className="px-3.5 pt-3.5 pb-1.5 font-mono text-[11px] tracking-[0.12em] text-dim">
      {roundHeading(roundId, turnType, label)}
    </div>
  );
  for (const turn of turns) {
    if (turn.round_id !== lastRound) {
      rows.push(heading(turn.round_id, turn.turn_type, turn.round_label));
      lastRound = turn.round_id;
    }
    if (hideVerdict && turn.turn_type === 'verdict') {
      rows.push(
        <div key={turn.seq_index} id={`turn-${turn.seq_index}`} className="p-3.5">
          <VerdictGate onReveal={onRevealVerdict} compact />
        </div>,
      );
      continue;
    }
    const seekable = onSeek && startMs.has(turn.seq_index) ? () => onSeek(turn.seq_index) : undefined;
    rows.push(<Row key={turn.seq_index} turn={turn} participants={participants} lineup={lineup} time={timeFor(turn.seq_index)} markdown={markdown} active={activeSeq === turn.seq_index} onSeek={seekable} board={board(turn)} />);
  }
  if (streaming) {
    if (streaming.round_id && streaming.round_id !== lastRound) rows.push(heading(streaming.round_id, streaming.turn_type, streaming.round_label));
    rows.push(<Row key={`s-${streaming.seq_index}`} turn={{ ...streaming, speaker_id: undefined }} participants={participants} lineup={lineup} time="now" markdown={false} streaming />);
  }
  return <div className="mt-3.5 grid gap-1">{rows}</div>;
};
