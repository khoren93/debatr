import { Download, Sparkles, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Timeline } from '../../api/timeline';
import type { Cover, DebateDetail, DebateMedia } from '../../api/types';
import { formatDuration } from '../../lib/format';
import { SCALE_720P } from '../../video/render';
import { Button, Progress } from '../ui';
import { CoverCard } from './CoverCard';
import { ExportCard } from './ExportCard';
import type { SpeakerInfo, VideoFormat } from './helpers';
import { PublishKit } from './PublishKit';
import { track } from '../../lib/presence';

interface Props {
  open: boolean;
  onClose: () => void;
  debate: DebateDetail;
  lineup: SpeakerInfo[];
  media: DebateMedia | null;
  timeline: Timeline | null;
  mediaBase: string;
  format: VideoFormat;
  onFormat: (f: VideoFormat) => void;
  highlightIndex: number;
  onHighlightChange: (i: number) => void;
  onGenerate: () => void;
  onCover: (cover: Cover) => void;
  /** Opened from "Generate AI cover": scroll to the cover card. */
  focusCover: boolean;
}

/** Slide-over "Export & publish" panel: browser renders, the audio track and the YouTube kit.
 *  The page mounts it on the first open (its chunk is not part of the page's first JavaScript); it
 *  stays mounted while hidden so a render keeps running when the panel is closed. */
export const ExportRail = ({ open, onClose, debate, lineup, media, timeline, mediaBase, format, onFormat, highlightIndex, onHighlightChange, onGenerate, onCover, focusCover }: Props) => {
  const closeRef = useRef<HTMLButtonElement>(null);
  // Mounted already open: drawn closed for a frame first, so it slides in as on later opens.
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => setEntered(true));
    });
    return () => cancelAnimationFrame(frame);
  }, []);
  const shown = open && entered;

  useEffect(() => {
    if (!shown) return;
    closeRef.current?.focus();
    if (focusCover) document.getElementById('cover-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [shown, focusCover]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const defaultScale = debate.media_plan?.quality === '4k' ? 2 : debate.media_plan?.quality === '720p' ? SCALE_720P : 1;
  const status = media?.media_status ?? 'none';
  const building = status === 'queued' || status === 'running';
  const progress = media?.progress;

  return (
    <>
      <div onClick={onClose} className={`fixed inset-0 z-[55] bg-[rgba(5,6,9,0.55)] backdrop-blur-[3px] transition-opacity duration-300 ${shown ? 'opacity-100' : 'pointer-events-none opacity-0'}`} aria-hidden="true" />
      {/* Visible at once when opening (the close button takes the focus), hidden only after
          sliding out. */}
      <aside
        inert={!shown}
        aria-label="Export and publish"
        className={`fixed top-3 right-3 bottom-3 z-[58] grid w-[min(440px,calc(100vw-24px))] content-start gap-3.5 overflow-y-auto overscroll-contain rounded-[22px] border border-white/9 bg-ink-2 px-4 pt-[18px] pb-7 shadow-[-30px_0_80px_-20px_rgba(0,0,0,0.85)] duration-[420ms] ease-[cubic-bezier(.22,1,.36,1)] ${shown ? 'visible translate-x-0 opacity-100 transition-[translate,opacity]' : 'invisible translate-x-[calc(100%+24px)] opacity-0 transition-[translate,opacity,visibility]'}`}
      >
        <div className="flex items-center justify-between gap-2.5">
          <h2 className="font-display text-lg font-bold tracking-[-0.02em]">Export &amp; publish</h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Hide panel" className="grid size-[34px] place-items-center rounded-[10px] border border-white/8 bg-surface text-text-3 hover:bg-surface-2 hover:text-text cursor-pointer">
            <X className="size-4" />
          </button>
        </div>

        <section className="grid min-w-0 gap-2.5 rounded-panel border border-white/6 bg-surface p-[18px]">
          <div className="flex items-baseline justify-between gap-2.5">
            <span className="font-mono text-[11px] tracking-[0.08em] text-muted">EXPORTS</span>
            <span className="text-xs text-dim">Rendered in your browser</span>
          </div>

          {!timeline &&
            (building ? (
              <div className="grid gap-2 rounded-[14px] border border-white/6 bg-ink p-3.5">
                <div className="font-mono text-[10px] tracking-[0.08em] text-host">VOICING THE DEBATE</div>
                <div className="text-[13px] text-text-2">{progress?.message || 'Queued'}</div>
                <Progress value={progress && progress.total > 0 ? progress.current / progress.total : 0} gradient height={5} />
              </div>
            ) : (
              <div className="flex items-center justify-between gap-3 rounded-[14px] border border-dashed border-line-2 bg-ink p-3.5">
                <div className="text-[13px] text-text-3">{debate.is_owner ? 'Voice the debate first — the video is drawn from the audio track.' : 'The owner has not voiced this debate yet.'}</div>
                {debate.is_owner && (
                  <Button size="sm" onClick={onGenerate} icon={<Sparkles className="size-3.5" />}>
                    Generate audio
                  </Button>
                )}
              </div>
            ))}

          <ExportCard kind="long" debateId={debate.id} timeline={timeline} mediaBase={mediaBase} highlightIndex={0} defaultScale={defaultScale} reportRenders={debate.is_owner} selected={format === 'long'} onSelect={() => onFormat('long')} />
          <ExportCard kind="short" debateId={debate.id} timeline={timeline} mediaBase={mediaBase} highlightIndex={highlightIndex} onHighlightChange={onHighlightChange} defaultScale={defaultScale} reportRenders={debate.is_owner} selected={format === 'short'} onSelect={() => onFormat('short')} />

          <div className="flex items-center justify-between gap-3 rounded-[14px] border border-white/6 bg-ink px-3.5 py-3">
            <div className="flex items-center gap-3">
              <span className="flex size-8 items-center justify-center gap-0.5 rounded-[9px] bg-surface-2" aria-hidden="true">
                <span className="h-2 w-[3px] rounded-sm bg-host" />
                <span className="h-3.5 w-[3px] rounded-sm bg-host" />
                <span className="h-2.5 w-[3px] rounded-sm bg-host" />
              </span>
              <div>
                <div className="text-sm font-bold">Audio track</div>
                <div className="mt-0.5 text-xs text-muted">{timeline ? `MP3 · mixed · ${formatDuration(timeline.total_ms)}` : 'MP3 · not built yet'}</div>
              </div>
            </div>
            {timeline && media?.urls ? (
              <a href={media.urls.full_mp3} download={`debate-${debate.id}.mp3`} onClick={() => track('download_mp3', {}, debate.id)} className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-white/8 bg-surface-2 px-3 text-xs font-semibold hover:bg-surface-3">
                <Download className="size-3.5" /> MP3
              </a>
            ) : (
              <span className="font-mono text-[10px] tracking-[0.06em] text-muted">NO AUDIO</span>
            )}
          </div>
        </section>

        {debate.is_owner && <CoverCard debate={debate} onChange={onCover} />}
        {debate.is_owner && <PublishKit debate={debate} lineup={lineup} timeline={timeline} active={open} />}
      </aside>
    </>
  );
};

export default ExportRail;
