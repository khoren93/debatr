import { Play, Square } from 'lucide-react';

interface VoicePreviewButtonProps {
  url: string | null;
  playing: boolean;
  onToggle: () => void;
  /** `sm`: voice list rows; `md`: the speaker row's action buttons. */
  size?: 'sm' | 'md';
  /** Colour of the icon while playing (speaker colour). */
  color?: string;
}

/** Play / stop a voice sample; disabled for voices without one (Edge). */
export const VoicePreviewButton = ({ url, playing, onToggle, size = 'md', color }: VoicePreviewButtonProps) => (
  <button
    type="button"
    onClick={(e) => {
      e.stopPropagation();
      onToggle();
    }}
    disabled={!url}
    title={url ? (playing ? 'Stop preview' : 'Preview voice') : 'No preview for this voice'}
    aria-label={playing ? 'Stop preview' : 'Preview voice'}
    className={`grid shrink-0 place-items-center border transition-colors ${
      size === 'sm' ? 'size-7 rounded-lg border-line-2 bg-surface-2' : 'size-[38px] rounded-[11px] border-white/8 bg-ink hover:bg-surface-2'
    } ${url ? 'cursor-pointer text-text-3' : 'cursor-not-allowed text-dim'} ${playing && size === 'sm' ? 'border-accent text-accent' : ''}`}
    style={playing && size === 'md' ? { color: color ?? undefined } : undefined}
  >
    {playing ? <Square className={size === 'sm' ? 'size-2.5' : 'size-3.5'} fill="currentColor" /> : <Play className={size === 'sm' ? 'size-2.5' : 'size-3.5'} fill="currentColor" />}
  </button>
);
