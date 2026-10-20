import type { Turn, Verdict } from '../../api/types';
import { JUDGE_COLOR, shortModelName, splitEmotionTag } from '../../lib/format';
import { markdownHtml } from '../../lib/markdown';
import { EmptyState } from '../ui';
import type { SpeakerInfo } from './helpers';
import { SpeakerTile } from './SpeakerTile';
import { VerdictGate } from './VerdictGate';

interface Props {
  verdict: Verdict | null;
  verdictTurn: Turn | null;
  lineup: SpeakerInfo[];
  isActive: boolean;
  markdown: boolean;
  /** Blind voting: the verdict stays covered until the viewer votes or reveals it. */
  hidden?: boolean;
  /** The show in a sentence ("debate", "battle"). */
  show?: string;
  onReveal?: () => void;
}

/** The judge's scores round by round (rap battles), the totals last; the round's better score bright. */
const ScoreSheet = ({ rounds, lineup, winnerId }: { rounds: NonNullable<Verdict['rounds']>; lineup: SpeakerInfo[]; winnerId: string | null }) => {
  const debaters = lineup.filter((s) => rounds.some((r) => s.id in r.scores));
  const total = (id: string) => rounds.reduce((sum, r) => sum + (r.scores[id] ?? 0), 0);
  const cols = { gridTemplateColumns: `minmax(90px,1fr) repeat(${debaters.length}, minmax(64px,120px))` };
  return (
    <div className="overflow-x-auto rounded-[14px] border border-white/8 bg-ink/60" role="table" aria-label="The judge's scores">
      <div className="grid items-center gap-x-3 border-b border-white/8 px-4 py-2.5" style={cols} role="row">
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted" role="columnheader">
          Scores
        </span>
        {debaters.map((d) => (
          <span key={d.id} className="truncate text-center text-[13px] font-bold" style={{ color: d.color }} role="columnheader">
            {d.name}
          </span>
        ))}
      </div>
      {rounds.map((r) => {
        const best = Math.max(...debaters.map((d) => r.scores[d.id] ?? 0));
        return (
          <div key={r.round} className="grid items-center gap-x-3 border-b border-white/6 px-4 py-2" style={cols} role="row">
            <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-text-3">Round {r.round}</span>
            {debaters.map((d) => (
              <span key={d.id} className={`text-center font-display text-lg font-bold ${r.scores[d.id] === best ? 'text-text' : 'text-dim'}`}>
                {r.scores[d.id] ?? '—'}
              </span>
            ))}
          </div>
        );
      })}
      <div className="grid items-center gap-x-3 px-4 py-2.5" style={cols} role="row">
        <span className="font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-text">Total</span>
        {debaters.map((d) => (
          <span key={d.id} className="text-center font-display text-xl font-extrabold" style={{ color: d.id === winnerId ? d.color : undefined }}>
            {total(d.id)}
          </span>
        ))}
      </div>
    </div>
  );
};

/** Verdict tab: the judge's headline with the winner, the round scores (battles), feedback per
 *  debater, the full ruling. */
export const VerdictTab = ({ verdict, verdictTurn, lineup, isActive, markdown, hidden = false, onReveal, show = 'debate' }: Props) => {
  if (!verdict && !verdictTurn) {
    return <EmptyState className="mt-5" title={isActive ? 'The judge is still deliberating' : 'No verdict'} text={isActive ? 'The verdict arrives after the last round.' : undefined} />;
  }
  if (hidden) return <VerdictGate onReveal={onReveal} />;
  const winner = verdict?.winner_id ? lineup.find((s) => s.id === verdict.winner_id) : undefined;
  const headline = verdict?.headline || (verdict?.winner_name ? `${verdict.winner_name} wins the ${show}.` : `The ${show} ends in a draw.`);
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

      {verdict?.rounds && verdict.rounds.length > 0 && <ScoreSheet rounds={verdict.rounds} lineup={lineup} winnerId={verdict.winner_id} />}

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
            <div className="prose prose-invert prose-sm mt-3 max-w-none text-text-2 prose-p:my-1.5 prose-headings:my-2 prose-strong:text-text" dangerouslySetInnerHTML={{ __html: markdownHtml(fullText) }} />
          ) : (
            <p className="mt-3 whitespace-pre-line text-[15px] leading-[1.6] text-text-2">{splitEmotionTag(fullText).body}</p>
          )}
        </details>
      )}
    </div>
  );
};

export default VerdictTab;
