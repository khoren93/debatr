import { Square } from 'lucide-react';
import { Bars, Button } from '../ui';

interface Props {
  status: 'queued' | 'running';
  roundLabel: string | null;
  speakerName: string | null;
  speakerColor: string;
  canStop: boolean;
  stopping: boolean;
  onStop: () => void;
  /** Between turns: the studio designs the last turn's scenes or fact-checks them. */
  studio?: 'designing' | 'checking' | null;
}

/** Player placeholder while the debate is being generated. */
export const LiveCard = ({ status, roundLabel, speakerName, speakerColor, canStop, stopping, onStop, studio = null }: Props) => (
  <div className="relative overflow-hidden rounded-panel border border-line-2 bg-ink-2" style={{ aspectRatio: '16/9', background: 'linear-gradient(90deg,#16224a 0 50%,#3d1a16 50% 100%)' }}>
    <div className="absolute inset-y-0 left-1/2 w-px bg-white/15" />
    <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4 font-mono text-[10px] tracking-[0.1em]">
      <span className="text-host">{roundLabel ?? (status === 'queued' ? 'WAITING FOR A WORKER' : 'WARMING UP')}</span>
      <span className="flex items-center gap-1.5 text-text">
        <span className="size-[7px] rounded-full bg-danger animate-pulse-dot" /> LIVE
      </span>
    </div>
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 p-6 text-center">
      <Bars color={speakerColor} height={34} />
      <div>
        <div className="font-mono text-[10px] tracking-[0.1em] text-muted">{!speakerName && studio ? 'THE STUDIO' : 'NOW SPEAKING'}</div>
        <div className="mt-1 font-display text-[clamp(20px,3vw,32px)] font-extrabold tracking-tight" style={{ color: speakerName || !studio ? speakerColor : '#D9FF3D' }}>
          {speakerName ?? (studio === 'designing' ? 'Drawing the scenes…' : studio === 'checking' ? 'Fact-checking the figures…' : status === 'queued' ? 'Queued…' : 'Thinking…')}
        </div>
      </div>
      {canStop && (
        <Button variant="danger" size="sm" onClick={onStop} loading={stopping} icon={<Square className="size-3 fill-current" />}>
          Stop debate
        </Button>
      )}
    </div>
    <div className="absolute inset-x-0 bottom-0 p-4 text-center font-mono text-[11px] text-text-3" style={{ background: 'linear-gradient(transparent,rgba(10,11,15,.9))' }}>
      Audio and video are produced automatically when the debate ends
    </div>
  </div>
);
