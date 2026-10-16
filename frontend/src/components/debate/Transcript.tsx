import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Timeline } from '../../api/timeline';
import type { Participant, Turn, TurnStartedEvent } from '../../api/types';
import { isErrorTurn, roundHeading, splitEmotionTag, turnErrorMessage } from '../../lib/format';
import { EmptyState, ErrorBox, SpeakerBadge } from '../ui';
import { msLabel, turnColor } from './helpers';
import { VerdictGate } from './VerdictTab';

export interface StreamingTurn extends TurnStartedEvent {
  text: string;
}

interface Props {
  turns: Turn[];
  streaming: StreamingTurn | null;
  participants: Participant[];
  timeline: Timeline | null;
  markdown: boolean;
  isActive: boolean;
  activeSeq?: number | null;
  /** Cover the judge's turn while the audience vote is blind. */
  hideVerdict?: boolean;
  onRevealVerdict?: () => void;
}

interface RowProps {
  turn: Pick<Turn, 'seq_index' | 'round_id' | 'turn_type' | 'speaker_id' | 'speaker_name' | 'text'> & Partial<Pick<Turn, 'error'>>;
  participants: Participant[];
  time: string;
  markdown: boolean;
  streaming?: boolean;
  active?: boolean;
}

const Row = ({ turn, participants, time, markdown, streaming = false, active = false }: RowProps) => {
  const color = turnColor(turn, participants);
  const error = !streaming && isErrorTurn({ error: turn.error ?? null, text: turn.text });
  const { tone, body } = splitEmotionTag(turn.text);
  return (
    <div id={`turn-${turn.seq_index}`} className={`grid grid-cols-[36px_1fr] gap-3 rounded-[14px] p-2 -m-2 transition-colors ${active ? 'bg-surface' : ''}`}>
      <SpeakerBadge name={turn.speaker_name} color={color} size={36} imageUrl={participants.find((p) => p.name === turn.speaker_name)?.avatar} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-bold">
            {turn.speaker_name}
            {tone && <span className="ml-1.5 rounded-[5px] bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] font-medium text-text-3">{tone}</span>}
            {streaming && <span className="ml-1.5 rounded-[5px] bg-danger/20 px-1.5 py-0.5 font-mono text-[10px] font-medium text-[#ff9b9b]">live</span>}
          </span>
          <span className="font-mono text-[11px] text-dim">{time}</span>
        </div>
        {error ? (
          <ErrorBox className="mt-2">{turnErrorMessage({ error: turn.error ?? null, text: turn.text })}</ErrorBox>
        ) : markdown && !streaming ? (
          <div className="prose prose-invert prose-sm mt-1.5 max-w-none text-text-2 prose-p:my-1.5 prose-headings:my-2 prose-strong:text-text">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
          </div>
        ) : (
          <p className="mt-1.5 whitespace-pre-line text-[15px] leading-[1.55] text-text-2 text-pretty">
            {body || (streaming ? <span className="italic text-muted">Thinking…</span> : null)}
            {streaming && body && <span className="ml-1 inline-block h-4 w-2 animate-pulse-dot bg-accent align-middle" />}
          </p>
        )}
      </div>
    </div>
  );
};

/** Transcript tab: turns grouped by round with mono headings. */
export const Transcript = ({ turns, streaming, participants, timeline, markdown, isActive, activeSeq = null, hideVerdict = false, onRevealVerdict }: Props) => {
  if (turns.length === 0 && !streaming) {
    return <EmptyState className="mt-5" title={isActive ? 'Waiting for the first speaker…' : 'No turns were recorded'} />;
  }
  const startMs = new Map<number, number>();
  timeline?.segments.forEach((s) => startMs.set(s.seq_index, s.start_ms));
  const timeFor = (seq: number) => (startMs.has(seq) ? msLabel(startMs.get(seq) ?? 0) : `#${seq + 1}`);

  const rows: React.ReactNode[] = [];
  let lastRound: string | null = null;
  const heading = (roundId: string, turnType: string) => (
    <div key={`h-${roundId}-${turnType}`} className="mt-2 font-mono text-[11px] tracking-[0.12em] text-muted">
      {roundHeading(roundId, turnType)}
    </div>
  );
  for (const turn of turns) {
    if (turn.round_id !== lastRound) {
      rows.push(heading(turn.round_id, turn.turn_type));
      lastRound = turn.round_id;
    }
    if (hideVerdict && turn.turn_type === 'verdict') {
      rows.push(
        <div key={turn.seq_index} id={`turn-${turn.seq_index}`}>
          <VerdictGate onReveal={onRevealVerdict} compact />
        </div>,
      );
      continue;
    }
    rows.push(<Row key={turn.seq_index} turn={turn} participants={participants} time={timeFor(turn.seq_index)} markdown={markdown} active={activeSeq === turn.seq_index} />);
  }
  if (streaming) {
    if (streaming.round_id && streaming.round_id !== lastRound) rows.push(heading(streaming.round_id, streaming.turn_type));
    rows.push(<Row key={`s-${streaming.seq_index}`} turn={{ ...streaming, speaker_id: undefined }} participants={participants} time="now" markdown={false} streaming />);
  }
  return <div className="mt-5 grid gap-4">{rows}</div>;
};
