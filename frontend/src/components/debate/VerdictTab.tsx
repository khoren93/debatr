import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Turn, Verdict } from '../../api/types';
import { JUDGE_COLOR, shortModelName } from '../../lib/format';
import { Button, EmptyState } from '../ui';
import type { SpeakerInfo } from './helpers';
import { SpeakerTile } from './SpeakerTile';

interface Props {
  verdict: Verdict | null;
  verdictTurn: Turn | null;
  lineup: SpeakerInfo[];
  isActive: boolean;
  markdown: boolean;
  /** Blind voting: the verdict stays covered until the viewer votes or reveals it. */
  hidden?: boolean;
  onReveal?: () => void;
}

/** Placeholder shown instead of the judge's ruling while the audience vote is still blind. */
export const VerdictGate = ({ onReveal, compact = false }: { onReveal?: () => void; compact?: boolean }) => (
  <div className={`rounded-panel border border-dashed border-accent/30 text-center ${compact ? 'p-4' : 'mt-[18px] p-[clamp(20px,3vw,32px)]'}`}>
    <div className="font-mono text-[11px] tracking-[0.12em] text-accent">JUDGE · VERDICT HIDDEN</div>
    <p className={`mx-auto max-w-[460px] text-text-3 ${compact ? 'mt-1.5 text-[13px]' : 'mt-2.5 text-[15px]'}`}>The judge has ruled. Vote for the debater who argued better first — then see whether you agree.</p>
    {onReveal && (
      <Button variant="ghost" size="sm" onClick={onReveal} className="mt-2.5">
        Reveal the verdict
      </Button>
    )}
  </div>
);

/** Verdict tab: the judge's headline with the winner, feedback per debater, the full ruling. */
export const VerdictTab = ({ verdict, verdictTurn, lineup, isActive, markdown, hidden = false, onReveal }: Props) => {
  if (!verdict && !verdictTurn) {
    return <EmptyState className="mt-5" title={isActive ? 'The judge is still deliberating' : 'No verdict'} text={isActive ? 'The verdict arrives after the last round.' : undefined} />;
  }
  if (hidden) return <VerdictGate onReveal={onReveal} />;
  const winner = verdict?.winner_id ? lineup.find((s) => s.id === verdict.winner_id) : undefined;
  const headline = verdict?.headline || (verdict?.winner_name ? `${verdict.winner_name} wins the debate.` : 'The debate ends in a draw.');
  const judgeModel = verdictTurn?.model_used || lineup.find((s) => s.id === 'judge')?.model;
  const fullText = verdictTurn?.text.trim() ?? '';
  return (
    <div className="mt-[18px] grid gap-5 rounded-panel border border-accent/22 bg-[linear-gradient(150deg,#1a1d16,#12141b_60%)] p-[clamp(20px,3vw,30px)]">
      <div>
        <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-accent">Judge{judgeModel ? ` · ${shortModelName(judgeModel)}` : ''}</div>
        <div className="mt-3 flex flex-wrap items-center gap-3.5">
          {winner ? (
            <SpeakerTile model={winner.model} color={winner.color} size={46} background={`${winner.color}1f`} />
          ) : (
            <span className="grid size-[46px] shrink-0 place-items-center rounded-[13px] font-display text-lg font-extrabold text-ink" style={{ background: JUDGE_COLOR }} aria-hidden="true">
              =
            </span>
          )}
          <div className="min-w-0 flex-1 font-display text-[clamp(26px,3vw,38px)] font-extrabold leading-[1.05] tracking-[-0.03em] text-balance">{headline}</div>
        </div>
      </div>

      {verdict && verdict.feedback.length > 0 && (
        <div className="grid gap-x-6 gap-y-5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))]">
          {verdict.feedback.map((f) => {
            const s = lineup.find((x) => x.id === f.speaker_id);
            const color = s?.color ?? '#8B90A0';
            return (
              <div key={f.speaker_id} className="min-w-0 border-l-2 pl-4" style={{ borderColor: `${color}80` }}>
                <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.06em]" style={{ color }}>
                  {f.name}
                  {s && <span className="opacity-70">· {s.tag}</span>}
                  {verdict.winner_id === f.speaker_id && <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent">winner</span>}
                </div>
                <p className="mt-2 max-w-[62ch] text-[15px] leading-[1.6] text-text-2 text-pretty">{f.text}</p>
              </div>
            );
          })}
        </div>
      )}

      {fullText && (
        <details className="group border-t border-white/8 pt-4">
          <summary className="cursor-pointer text-[13px] font-semibold text-text-3 hover:text-text">
            Full verdict <span className="inline-block transition-transform group-open:rotate-90">›</span>
          </summary>
          {markdown ? (
            <div className="prose prose-invert prose-sm mt-3 max-w-none text-text-2 prose-p:my-1.5 prose-headings:my-2 prose-strong:text-text">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{fullText}</ReactMarkdown>
            </div>
          ) : (
            <p className="mt-3 whitespace-pre-line text-[15px] leading-[1.6] text-text-2">{fullText.replace(/^\s*\[[^\]]{1,30}\]\s*/, '')}</p>
          )}
        </details>
      )}
    </div>
  );
};
