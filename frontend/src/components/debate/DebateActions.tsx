import { Captions, Copy, Ellipsis, FileText, ImagePlus, PanelRight, RectangleHorizontal, RectangleVertical, Repeat2, Share, Sparkles, Square, Trash2 } from 'lucide-react';
import { Suspense, lazy, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import type { Timeline } from '../../api/timeline';
import type { DebateDetail } from '../../api/types';
import { formatCost, formatTokens } from '../../lib/format';
import { useToast } from '../ui';
import { debateMarkdown, downloadText, timelineSrt, transcriptText, type VideoFormat } from './helpers';
import { LikeButton } from './LikeButton';
import type { PlayerPosition } from './EmbedPanel';
import { ICON_ON_PHONES, TOOL_BUTTON } from './toolButton';

// Opens on a click: not part of the page's first JavaScript.
const SharePopover = lazy(() => import('./SharePopover'));

interface Props {
  debate: DebateDetail;
  timeline: Timeline | null;
  isActive: boolean;
  completed: boolean;
  /** The media build is queued or running. */
  voicing: boolean;
  railOpen: boolean;
  /** Export panel has something to show (renders or the owner's tools). */
  canExport: boolean;
  onToggleRail: () => void;
  /** Player format switch (16:9 episode / 9:16 Short), shown while a video plays. */
  format?: VideoFormat;
  onFormat?: (format: VideoFormat) => void;
  onLikes: (likes: number, liked: boolean) => void;
  onPatch: (patch: Partial<DebateDetail>) => void;
  onGenerate: () => void;
  /** Open the export panel at the AI cover card. */
  onCover: () => void;
  /** Where the page's player is (the embed code may start there). */
  playerPosition?: () => PlayerPosition | null;
  onStop: () => void;
  onDelete: () => void;
}

const POPOVER = 'absolute right-0 top-12 z-40 rounded-2xl border border-white/10 bg-surface-2 shadow-[0_30px_60px_-20px_rgba(0,0,0,0.8)] animate-[rise_.2s_ease_both]';

const MenuItem = ({ icon, children, onClick, danger = false }: { icon: ReactNode; children: ReactNode; onClick: () => void; danger?: boolean }) => (
  <button type="button" role="menuitem" onClick={onClick} className={`flex w-full items-center gap-2.5 rounded-[9px] px-3 py-2.5 text-left text-[13px] font-medium cursor-pointer ${danger ? 'text-con hover:bg-con/10' : 'text-text-2 hover:bg-surface-3'}`}>
    {icon}
    {children}
  </button>
);

const FORMATS = [
  { value: 'long', label: 'YouTube 16:9', Icon: RectangleHorizontal },
  { value: 'short', label: 'Short 9:16', Icon: RectangleVertical },
] as const;

/** Toolbar over the player: video format, like, share, remix, export panel and the "more" menu. */
export const DebateActions = ({ debate, timeline, isActive, completed, voicing, railOpen, canExport, onToggleRail, format, onFormat, onLikes, onPatch, onGenerate, onCover, playerPosition, onStop, onDelete }: Props) => {
  const toast = useToast();
  const [open, setOpen] = useState<'share' | 'menu' | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const owner = debate.is_owner;

  // Close the popover on a click outside the toolbar or on Escape.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(null);
    };
    document.addEventListener('pointerdown', onPointer);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggle = (which: 'share' | 'menu') => setOpen((cur) => (cur === which ? null : which));
  const run = (action: () => void) => () => {
    setOpen(null);
    action();
  };

  const title = debate.settings.topic || debate.title || 'Debate';
  const exportMarkdown = () => downloadText(debateMarkdown(title, debate.created_at, debate.status, debate.participants, debate.turns), `debate-${debate.id}.md`);
  const exportSrt = () => timeline && downloadText(timelineSrt(timeline), `debate-${debate.id}.srt`, 'application/x-subrip');
  const copyTranscript = async () => {
    try {
      await navigator.clipboard.writeText(transcriptText(title, debate.turns));
      toast.success('Transcript copied');
    } catch {
      toast.error('Could not copy the transcript');
    }
  };

  const totals = debate.totals;
  const usage = [totals.tokens_in + totals.tokens_out > 0 ? `${formatTokens(totals.tokens_in)} in · ${formatTokens(totals.tokens_out)} out tokens` : null, owner ? formatCost(totals.cost) : null].filter(Boolean).join(' · ');
  const canShare = owner ? completed : debate.is_public;

  return (
    <div ref={rootRef} className="relative flex flex-wrap gap-2">
      {format && onFormat && (
        <div role="group" aria-label="Video format" className="inline-flex h-10 shrink-0 items-center gap-0.5 rounded-[11px] border border-white/10 bg-surface p-[3px]">
          {FORMATS.map(({ value, label, Icon }) => (
            <button
              key={value}
              type="button"
              onClick={() => onFormat(value)}
              aria-pressed={format === value}
              aria-label={label}
              title={label}
              className={`grid h-full w-[34px] place-items-center rounded-[8px] transition-colors cursor-pointer ${format === value ? 'bg-surface-3 text-accent' : 'text-muted hover:text-text'}`}
            >
              <Icon className="size-4" />
            </button>
          ))}
        </div>
      )}
      {/* Owners cannot like their own debate; its count is in the page's meta line. */}
      {debate.is_public && !owner && <LikeButton debate={debate} onChange={onLikes} />}
      {owner && isActive && (
        <button type="button" onClick={onStop} className={`${TOOL_BUTTON} text-con`}>
          <Square className="size-3.5 fill-current" /> Stop
        </button>
      )}
      {canShare && (
        <button type="button" onClick={() => toggle('share')} aria-expanded={open === 'share'} aria-haspopup="dialog" aria-label="Share" title="Share" className={`${TOOL_BUTTON} ${ICON_ON_PHONES}`}>
          <Share className="size-4" /> <span className="max-sm:hidden">Share</span>
        </button>
      )}
      {completed && (owner || debate.is_public) && (
        <Link to={`/create?remix=${debate.id}`} aria-label="Remix" title="Remix: a new debate with this setup" className={`${TOOL_BUTTON} ${ICON_ON_PHONES}`}>
          <Repeat2 className="size-4" /> <span className="max-sm:hidden">Remix</span>
        </Link>
      )}
      {canExport && (
        <button type="button" onClick={onToggleRail} aria-expanded={railOpen} aria-label="Export" title="Show or hide the export panel" className={`${TOOL_BUTTON} ${ICON_ON_PHONES} ${railOpen ? '!border-accent/50 !bg-accent/8 text-accent' : ''}`}>
          <PanelRight className="size-4" /> <span className="max-sm:hidden">Export</span>
        </button>
      )}
      <button type="button" onClick={() => toggle('menu')} aria-expanded={open === 'menu'} aria-haspopup="menu" aria-label="More" title="More" className={`${TOOL_BUTTON} !w-10 !px-0`}>
        <Ellipsis className="size-[18px]" />
      </button>

      {open === 'share' && (
        <div className={`${POPOVER} w-[min(360px,calc(100vw-32px))] p-4`} role="dialog" aria-label="Share this debate">
          <Suspense fallback={<div className="h-24" />}>
            <SharePopover debate={debate} onChange={onPatch} position={playerPosition} />
          </Suspense>
        </div>
      )}
      {open === 'menu' && (
        <div className={`${POPOVER} grid w-[250px] gap-0.5 p-1.5`} role="menu">
          <MenuItem icon={<FileText className="size-4" />} onClick={run(exportMarkdown)}>
            Export Markdown
          </MenuItem>
          {timeline && (
            <MenuItem icon={<Captions className="size-4" />} onClick={run(exportSrt)}>
              Download subtitles (.srt)
            </MenuItem>
          )}
          <MenuItem icon={<Copy className="size-4" />} onClick={run(() => void copyTranscript())}>
            Copy transcript
          </MenuItem>
          {owner && completed && !voicing && (
            <MenuItem icon={<Sparkles className="size-4" />} onClick={run(onGenerate)}>
              {timeline ? 'Regenerate audio' : 'Generate audio'}
            </MenuItem>
          )}
          {owner && completed && debate.cover.reason !== 'off' && (
            <MenuItem icon={<ImagePlus className="size-4" />} onClick={run(onCover)}>
              {debate.cover.current ? 'New AI cover' : 'Generate AI cover'}
            </MenuItem>
          )}
          {(usage || owner) && <div className="mx-1.5 my-1 h-px bg-white/8" />}
          {usage && <div className="px-3 pt-1.5 pb-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-dim">{usage}</div>}
          {owner && (
            <MenuItem danger icon={<Trash2 className="size-4" />} onClick={run(onDelete)}>
              Delete debate
            </MenuItem>
          )}
        </div>
      )}
    </div>
  );
};
