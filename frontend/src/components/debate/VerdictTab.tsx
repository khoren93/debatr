import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Participant, Turn, Verdict } from '../../api/types';
import { speakerColor } from '../../lib/format';
import { Button, EmptyState } from '../ui';

interface Props {
  verdict: Verdict | null;
  verdictTurn: Turn | null;
  participants: Participant[];
  judgeVoice: string | null;
  isActive: boolean;
  markdown: boolean;
  /** Blind voting: the verdict stays covered until the viewer votes or reveals it. */
  hidden?: boolean;
  onReveal?: () => void;
}

/** Placeholder shown instead of the judge's ruling while the audience vote is still blind. */
export const VerdictGate = ({ onReveal, compact = false }: { onReveal?: () => void; compact?: boolean }) => (
  <div className={`rounded-panel border border-dashed border-host/35 text-center ${compact ? 'p-4' : 'mt-5 p-[clamp(20px,3vw,32px)]'}`}>
    <div className="font-mono text-[11px] tracking-[0.12em] text-host">JUDGE · VERDICT HIDDEN</div>
    <p className={`mx-auto max-w-[460px] text-text-3 ${compact ? 'mt-1.5 text-[13px]' : 'mt-2.5 text-[15px]'}`}>The judge has ruled. Vote for the debater who argued better first — then see whether you agree.</p>
    {onReveal && (
      <Button variant="ghost" size="sm" onClick={onReveal} className="mt-2.5">
        Reveal the verdict
      </Button>
    )}
  </div>
);

/** Verdict tab: headline, per-debater feedback, full judge text. */
export const VerdictTab = ({ verdict, verdictTurn, participants, judgeVoice, isActive, markdown, hidden = false, onReveal }: Props) => {
  if (!verdict && !verdictTurn) {
    return <EmptyState className="mt-5" title={isActive ? 'The judge is still deliberating' : 'No verdict'} text={isActive ? 'The verdict arrives after the last round.' : undefined} />;
  }
  if (hidden) return <VerdictGate onReveal={onReveal} />;
  const headline = verdict?.headline || (verdict?.winner_name ? `${verdict.winner_name} wins the debate.` : 'The debate ends in a draw.');
  const debaters = participants.filter((p) => p.role !== 'moderator');
  return (
    <div className="mt-5 rounded-panel border border-host/30 p-[clamp(20px,3vw,32px)]" style={{ background: 'linear-gradient(140deg,#181B24,#12141B)' }}>
      <div className="font-mono text-[11px] tracking-[0.12em] text-host">JUDGE{judgeVoice ? ` · ${judgeVoice.toUpperCase()}` : ''}</div>
      <div className="mt-2.5 font-display text-[clamp(26px,3vw,40px)] font-extrabold leading-tight tracking-[-0.03em] text-balance">{headline}</div>
      {verdict && verdict.feedback.length > 0 && (
        <div className="mt-4.5 grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))]">
          {verdict.feedback.map((f) => {
            const color = speakerColor(f.speaker_id, participants);
            const idx = debaters.findIndex((p, i) => (p.id ?? `participant_${participants.indexOf(p)}`) === f.speaker_id || i === -1);
            const tag = idx === 0 ? 'Pro' : idx === 1 ? 'Con' : `Side ${idx + 1}`;
            return (
              <div key={f.speaker_id} className="rounded-[14px] border p-4" style={{ background: `${color}14`, borderColor: `${color}40` }}>
                <div className="font-bold" style={{ color }}>
                  {f.name} · {tag}
                </div>
                <p className="mt-2 text-sm leading-[1.55] text-text-2">{f.text}</p>
              </div>
            );
          })}
        </div>
      )}
      {verdictTurn && verdictTurn.text.trim() && (
        <details className="mt-5">
          <summary className="cursor-pointer text-[13px] font-semibold text-text-3 hover:text-text">Full verdict ›</summary>
          {markdown ? (
            <div className="prose prose-invert prose-sm mt-3 max-w-none text-text-2 prose-p:my-1.5 prose-headings:my-2 prose-strong:text-text">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{verdictTurn.text}</ReactMarkdown>
            </div>
          ) : (
            <p className="mt-3 whitespace-pre-line text-[15px] leading-[1.55] text-text-2">{verdictTurn.text.replace(/^\s*\[[^\]]{1,30}\]\s*/, '')}</p>
          )}
        </details>
      )}
    </div>
  );
};
