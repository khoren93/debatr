import { STEP_LABELS, type WizardStep } from './wizardState';

interface WizardProgressProps {
  step: WizardStep;
  /** Highest step that can be jumped to (all previous steps are valid). */
  maxStep: WizardStep;
  onSelect: (step: WizardStep) => void;
}

/** Three thin bars with mono numbers: "01 Topic · 02 Speakers · 03 Review". */
export const WizardProgress = ({ step, maxStep, onSelect }: WizardProgressProps) => (
  <div className="mt-[22px] grid grid-cols-3 gap-2" role="list" aria-label="Wizard steps">
    {STEP_LABELS.map((label, i) => {
      const n = (i + 1) as WizardStep;
      const reachable = n <= maxStep;
      const current = n === step;
      return (
        <button
          key={label}
          type="button"
          role="listitem"
          aria-current={current ? 'step' : undefined}
          disabled={!reachable}
          onClick={() => onSelect(n)}
          className={`min-w-0 text-left ${reachable ? 'cursor-pointer' : 'cursor-default'}`}
        >
          <div className={`h-[3px] rounded-[3px] transition-colors ${n <= step ? 'bg-accent' : 'bg-surface-3'}`} />
          <div className={`mt-2.5 truncate text-xs font-semibold ${current ? 'text-text' : 'text-muted'}`}>
            <span className="mr-1.5 font-mono text-muted">0{n}</span>
            {label}
          </div>
        </button>
      );
    })}
  </div>
);
