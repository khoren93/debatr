import { Check, Copy, Globe, Link2Off, ShieldAlert, ShieldX } from 'lucide-react';
import { useState } from 'react';
import { getErrorMessage } from '../../api/client';
import { publishDebate, unpublishDebate } from '../../api/debates';
import { GALLERY_CATEGORIES, type DebateDetail } from '../../api/types';
import { Button, Chip, useToast } from '../ui';

interface Props {
  debate: DebateDetail;
  onChange: (patch: Partial<DebateDetail>) => void;
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Share strip under the header: publish to the gallery, copy the link, unpublish. Debates flagged
 * by the automatic content check wait for an admin review instead of going public. */
export const SharePanel = ({ debate, onChange }: Props) => {
  const toast = useToast();
  const [category, setCategory] = useState<string | null>(debate.category);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const publish = async () => {
    setBusy(true);
    try {
      const res = await publishDebate(debate.id, category);
      if (res.moderation_status === 'flagged' && !res.is_public) {
        onChange({ category, moderation: { status: 'flagged', reason: debate.moderation?.reason ?? null, publish_requested: true } });
        toast.info('Sent for review. It goes public once a moderator approves it.');
      } else {
        onChange({ is_public: res.is_public, slug: res.slug, share_url: res.share_url, category });
        toast.success('Published to the gallery');
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
      const moderation = debate.moderation ? { ...debate.moderation, publish_requested: false } : null;
      onChange({ is_public: res.is_public, share_url: null, moderation });
      toast.info(debate.is_public ? 'The debate is private again' : 'Review request withdrawn');
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!debate.share_url) return;
    try {
      await navigator.clipboard.writeText(debate.share_url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
      toast.success('Link copied');
    } catch {
      toast.error('Could not copy the link');
    }
  };

  if (debate.is_public && debate.share_url) {
    return (
      <div className="mt-3.5 flex flex-wrap items-center gap-2 rounded-field border border-accent/40 bg-surface py-2.5 pl-4 pr-2.5 font-mono text-[13px] animate-rise">
        <Globe className="size-4 text-accent" />
        <span className="min-w-[200px] flex-1 truncate text-text-3">{debate.share_url.replace(/^https?:\/\//, '')}</span>
        <Button size="sm" onClick={copy} icon={copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}>
          {copied ? 'Copied' : 'Copy link'}
        </Button>
        <Button size="sm" variant="secondary" onClick={unpublish} loading={busy} icon={<Link2Off className="size-3.5" />}>
          Unpublish
        </Button>
      </div>
    );
  }

  const moderation = debate.moderation;
  if (moderation?.status === 'rejected') {
    return (
      <div className="mt-3.5 flex items-start gap-2.5 rounded-field border border-con/40 bg-surface px-4 py-3 text-[13px] text-text-3 animate-rise">
        <ShieldX className="mt-0.5 size-4 shrink-0 text-con" />
        <span>A moderator did not approve this debate for the public gallery. It stays private to you.</span>
      </div>
    );
  }

  if (moderation?.status === 'flagged') {
    return (
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5 rounded-field border border-host/40 bg-surface py-2.5 pl-4 pr-2.5 text-[13px] text-text-3 animate-rise">
        <ShieldAlert className="size-4 shrink-0 text-host" />
        <span className="min-w-[200px] flex-1">
          <b className="font-semibold text-text">Needs a review before it can go public.</b>{' '}
          {moderation.reason ? `${moderation.reason} ` : ''}
          {moderation.publish_requested ? 'It goes to the gallery as soon as a moderator approves it.' : 'Ask for a review if you want it in the gallery.'}
        </span>
        {moderation.publish_requested ? (
          <Button size="sm" variant="secondary" onClick={unpublish} loading={busy}>
            Withdraw request
          </Button>
        ) : (
          <Button size="sm" onClick={publish} loading={busy} icon={<Globe className="size-3.5" />}>
            Request review
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="mt-3.5 flex flex-wrap items-center gap-2 rounded-field border border-line-2 bg-surface p-2.5 pl-4 animate-rise">
      <span className="text-[13px] text-text-3">Category</span>
      <div className="flex flex-wrap gap-1.5">
        {GALLERY_CATEGORIES.map((c) => (
          <Chip key={c} size="sm" active={category === c} onClick={() => setCategory(category === c ? null : c)}>
            {capitalise(c)}
          </Chip>
        ))}
      </div>
      <Button size="sm" className="ml-auto" onClick={publish} loading={busy} disabled={debate.status !== 'completed'} icon={<Globe className="size-3.5" />}>
        Publish to gallery
      </Button>
    </div>
  );
};
