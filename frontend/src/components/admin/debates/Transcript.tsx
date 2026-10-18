import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { AdminTurn } from '../../../api/admin/types';
import { formatTokens, roundHeading } from '../../../lib/format';
import { ModelIcon } from '../../ui';
import { formatSeconds, formatUsd } from '../helpers';

const CHECK_TONES: Record<string, string> = { verified: 'text-ok', disputed: 'text-con', unverified: 'text-muted' };

const TurnMeta = ({ turn }: { turn: AdminTurn }) => {
  const checks = Object.entries(turn.checks);
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted tabular-nums">
      {(turn.tokens_in > 0 || turn.tokens_out > 0) && (
        <span>
          {formatTokens(turn.tokens_in)} in · {formatTokens(turn.tokens_out)} out
        </span>
      )}
      {turn.cost > 0 && <span>{formatUsd(turn.cost)}</span>}
      {turn.duration_ms !== null && (
        <span>
          {formatSeconds(turn.duration_ms)}
          {turn.ttft_ms !== null && `, first word ${formatSeconds(turn.ttft_ms)}`}
        </span>
      )}
      {turn.scenes > 0 && (
        <span>
          {turn.scenes} scene{turn.scenes === 1 ? '' : 's'}
          {checks.map(([verdict, n]) => (
            <span key={verdict} className={CHECK_TONES[verdict] ?? ''}>
              {' '}
              · {n} {verdict}
            </span>
          ))}
        </span>
      )}
      {turn.disputes > 0 && <span className="text-host">disputes {turn.disputes}</span>}
      {turn.visuals_status === 'error' && <span className="text-con">scenes failed</span>}
    </div>
  );
};

/** The debate's turns with their model, usage, scenes and errors; long ones fold. */
export const Transcript = ({ turns, folded = true }: { turns: AdminTurn[]; folded?: boolean }) => {
  const [open, setOpen] = useState<Set<number>>(new Set());
  if (turns.length === 0) return <p className="px-4 py-4 text-sm text-muted">No turns yet.</p>;
  const toggle = (seq: number) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  return (
    <ol className="divide-y divide-line/70">
      {turns.map((turn) => {
        const long = turn.text.length > 600;
        const shut = folded && long && !open.has(turn.seq_index);
        return (
          <li key={turn.seq_index} className="grid gap-1.5 px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <span className="font-mono text-muted">#{turn.seq_index + 1}</span>
              <span className="font-semibold text-text-2">{turn.speaker_name}</span>
              <span className="text-muted">{roundHeading(turn.round_id, turn.turn_type)}</span>
              <span className="ml-auto flex min-w-0 items-center gap-1.5 text-muted" title={turn.model_used}>
                <ModelIcon modelId={turn.model_used} size={13} />
                <span className="truncate font-mono text-[11px]">{turn.model_used}</span>
              </span>
            </div>
            <TurnMeta turn={turn} />
            {turn.error && (
              <div className="rounded-[10px] border border-con/30 bg-con/10 px-3 py-2 text-xs text-con">
                {turn.error_kind && <span className="font-mono">[{turn.error_kind}] </span>}
                {turn.error}
              </div>
            )}
            {turn.text && (
              <div className={`relative whitespace-pre-wrap text-[13px] leading-relaxed text-text-3 ${shut ? 'max-h-36 overflow-hidden' : ''}`}>
                {turn.text}
                {shut && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-surface to-transparent" />}
              </div>
            )}
            {folded && long && (
              <button type="button" onClick={() => toggle(turn.seq_index)} className="flex w-fit cursor-pointer items-center gap-1 text-xs font-semibold text-muted hover:text-text">
                <ChevronDown className={`size-3.5 transition-transform ${shut ? '' : 'rotate-180'}`} />
                {shut ? 'Show all' : 'Fold'}
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
};
