import { Check, ChevronDown, Code, Copy, ShieldAlert, ShieldX } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { getErrorMessage } from '../../api/client';
import { publishDebate, unpublishDebate } from '../../api/debates';
import { GALLERY_CATEGORIES, type DebateDetail } from '../../api/types';
import { Button, Chip, Spinner, useToast } from '../ui';
import { EmbedPanel, type PlayerPosition } from './EmbedPanel';
import { track } from '../../lib/presence';

interface Props {
  debate: DebateDetail;
  onChange: (patch: Partial<DebateDetail>) => void;
  /** The page's player position (the embed may start there). */
  position?: () => PlayerPosition | null;
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Share popover: the public link, the embed code of a voiced public debate and, for the owner,
 *  the gallery switch. Debates flagged by the automatic content check wait for an admin review
 *  instead of going public. */
export const SharePopover = ({ debate, onChange, position }: Props) => {
  const toast = useToast();
  const [category, setCategory] = useState<string | null>(debate.category);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [embedOpen, setEmbedOpen] = useState(false);
  const link = debate.is_public && debate.share_url ? debate.share_url : null;
  // The player plays only with audio: a debate without it has nothing to embed yet.
  const embeddable = Boolean(link && debate.slug) && debate.media_status === 'ready';
  const moderation = debate.moderation;
  const owner = debate.is_owner;

  const publish = async () => {
    setBusy(true);
    try {
      const res = await publishDebate(debate.id, category);
      if (res.moderation_status === 'flagged' && !res.is_public) {
        onChange({ category, moderation: { status: 'flagged', reason: moderation?.reason ?? null, publish_requested: true } });
        toast.info('Sent for review. It goes public once a moderator approves it.');
      } else {
        onChange({ is_public: res.is_public, slug: res.slug, share_url: res.share_url, category });
        toast.success('Listed in the public gallery');
      }
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const unpublish = async () => {
    setBusy(true);
    try {
      const res = await unpublishDebate(debate.id);
      onChange({ is_public: res.is_public, share_url: null, moderation: moderation ? { ...moderation, publish_requested: false } : null });
      toast.info(debate.is_public ? 'The debate is private again' : 'Review request withdrawn');
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      track('copy_link', {}, debate.id);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      toast.error('Could not copy the link');
    }
  };

  const canPublish = debate.status === 'completed';
  let gallery: ReactNode = null;
  if (owner && moderation?.status === 'rejected' && !debate.is_public) {
    gallery = (
      <div className="flex items-start gap-2.5 text-[13px] text-text-3">
        <ShieldX className="mt-0.5 size-4 shrink-0 text-con" />
        <span>A moderator did not approve this debate for the public gallery. It stays private to you.</span>
      </div>
    );
  } else if (owner && moderation?.status === 'flagged' && !debate.is_public) {
    gallery = (
      <div className="grid gap-2.5">
        <div className="flex items-start gap-2.5 text-[13px] text-text-3">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-host" />
          <span>
            <b className="font-semibold text-text">Needs a review before it can go public.</b> {moderation.reason ? `${moderation.reason} ` : ''}
            {moderation.publish_requested ? 'It goes to the gallery as soon as a moderator approves it.' : 'Ask for a review if you want it in the gallery.'}
          </span>
        </div>
        {moderation.publish_requested ? (
          <Button size="sm" variant="secondary" onClick={unpublish} loading={busy} className="justify-self-start">
            Withdraw request
          </Button>
        ) : (
          <Button size="sm" onClick={publish} loading={busy} className="justify-self-start">
            Request review
          </Button>
        )}
      </div>
    );
  } else if (owner) {
    gallery = (
      <>
        <button type="button" role="switch" aria-checked={debate.is_public} disabled={busy || (!debate.is_public && !canPublish)} onClick={debate.is_public ? unpublish : publish} className="flex items-center justify-between gap-3 text-left cursor-pointer disabled:cursor-not-allowed">
          <span>
            <span className="block text-[13px] font-semibold">Listed in public gallery</span>
            <span className="mt-0.5 block text-xs text-muted">{canPublish || debate.is_public ? 'Anyone can find, watch and vote.' : 'Only finished debates can be listed.'}</span>
          </span>
          {busy ? (
            <Spinner className="size-4" />
          ) : (
            <span className={`relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors ${debate.is_public ? 'bg-accent' : 'bg-surface-4'}`}>
              <span className={`absolute top-[3px] left-[3px] size-4 rounded-full transition-transform ${debate.is_public ? 'translate-x-4 bg-ink' : 'bg-muted'}`} />
            </span>
          )}
        </button>
        {!debate.is_public && canPublish && (
          <div className="grid gap-1.5">
            <span className="text-xs text-muted">Gallery category (optional)</span>
            <div className="flex flex-wrap gap-1.5">
              {GALLERY_CATEGORIES.map((c) => (
                <Chip key={c} size="sm" active={category === c} onClick={() => setCategory(category === c ? null : c)}>
                  {capitalise(c)}
                </Chip>
              ))}
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3.5">
      <div className="text-sm font-bold">Share this debate</div>
      <div className="flex items-center gap-2 rounded-xl border border-white/8 bg-ink py-1.5 pr-1.5 pl-3">
        <span className={`min-w-0 flex-1 truncate font-mono text-xs ${link ? 'text-text-3' : 'text-dim'}`}>{link ? link.replace(/^https?:\/\//, '') : 'Private — list it to get a public link'}</span>
        <button type="button" onClick={copy} disabled={!link} className="inline-flex shrink-0 items-center gap-1.5 rounded-[9px] bg-accent px-3 py-2 text-xs font-bold text-ink hover:bg-accent-hover cursor-pointer disabled:cursor-not-allowed disabled:opacity-40">
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      {embeddable && (
        <div className="grid gap-3">
          <button type="button" aria-expanded={embedOpen} onClick={() => setEmbedOpen((v) => !v)} className="flex items-center gap-2 text-left text-[13px] font-semibold text-text-2 hover:text-text cursor-pointer">
            <Code className="size-4 text-muted" />
            <span className="flex-1">Embed on a website</span>
            <ChevronDown className={`size-4 text-muted transition-transform ${embedOpen ? 'rotate-180' : ''}`} />
          </button>
          {embedOpen && <EmbedPanel debate={debate} position={position} />}
        </div>
      )}
      {gallery}
    </div>
  );
};

export default SharePopover;
