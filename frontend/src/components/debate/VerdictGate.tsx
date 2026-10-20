import { Button } from '../ui';

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
