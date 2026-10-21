import { Check, Copy } from 'lucide-react';
import { useState } from 'react';
import type { DebateDetail } from '../../api/types';
import { EMBED_ALLOW, embedCode, embedPath, embedTitle, type EmbedFormat } from '../../lib/embed';
import { Segmented, SwitchTrack, useToast } from '../ui';
import { msLabel, type VideoFormat } from './helpers';
import { track } from '../../lib/presence';

/** Where the page's player is: the embed may start there (the same video, the same clock). */
export interface PlayerPosition {
  format: VideoFormat;
  ms: number;
}

interface Props {
  debate: DebateDetail;
  /** Read when the panel opens; null without a loaded player. */
  position?: () => PlayerPosition | null;
}

const FORMATS = [
  { value: 'long' as const, label: '16:9 video' },
  { value: 'short' as const, label: '9:16 Short' },
];

/** The Share popover's embed code: 16:9 or the Short, optionally from the player's moment, with a
 *  live preview (the player as another site shows it) and a copy button. */
export const EmbedPanel = ({ debate, position }: Props) => {
  const toast = useToast();
  const [format, setFormat] = useState<EmbedFormat>('long');
  const [fromNow, setFromNow] = useState(false);
  const [copied, setCopied] = useState(false);
  // The moment when the panel opened (the video may go on playing behind it).
  const [at] = useState(() => position?.() ?? null);
  const nowS = at && at.format === format && at.ms >= 1000 ? Math.floor(at.ms / 1000) : 0;
  const start = fromNow ? nowS : 0;
  const path = embedPath(debate.slug ?? '', { format, start });
  const origin = debate.share_url ? new URL(debate.share_url).origin : '';
  const title = embedTitle(debate.settings.topic || debate.title || '', debate.participants);
  const code = embedCode(`${origin}${path}`, title, format);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      track('copy_embed', { format, start }, debate.id);
      setCopied(true);
      toast.success('Embed code copied');
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      toast.error('Could not copy the code');
    }
  };

  return (
    <div className="grid gap-3">
      <Segmented size="sm" grow options={FORMATS} value={format} onChange={setFormat} />
      <button type="button" role="switch" aria-checked={fromNow && nowS > 0} disabled={nowS === 0} onClick={() => setFromNow((v) => !v)} className="flex items-center justify-between gap-3 text-left cursor-pointer disabled:cursor-not-allowed disabled:opacity-50">
        <span className="text-[13px] font-semibold">
          Start at {nowS > 0 ? msLabel(nowS * 1000) : 'the current moment'}
          {nowS === 0 && <span className="mt-0.5 block text-xs font-normal text-muted">Play the {format === 'short' ? 'Short' : 'video'} on this page to pick a moment.</span>}
        </span>
        <SwitchTrack on={fromNow && nowS > 0} size="sm" />
      </button>
      <div className="grid place-items-center overflow-hidden rounded-xl border border-white/8 bg-black">
        <iframe key={path} src={path} title={`Preview: ${title}`} allow={EMBED_ALLOW} allowFullScreen loading="lazy" className={`block border-0 ${format === 'short' ? 'h-[260px] w-[146px]' : 'aspect-video w-full'}`} />
      </div>
      <div className="relative">
        <textarea readOnly value={code} rows={4} onFocus={(e) => e.currentTarget.select()} aria-label="Embed code" className="block w-full resize-none rounded-xl border border-white/8 bg-ink px-3 py-2.5 pr-12 font-mono text-[11px] leading-relaxed text-text-3 outline-none focus:border-accent/50" />
        <button type="button" onClick={() => void copy()} aria-label="Copy the embed code" title="Copy" className="absolute top-2 right-2 grid size-8 place-items-center rounded-[9px] bg-accent text-ink hover:bg-accent-hover cursor-pointer">
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </button>
      </div>
      <p className="text-xs text-muted">Paste it into any page. Links to this debate also turn into the player in apps that read oEmbed.</p>
    </div>
  );
};
