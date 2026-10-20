import { useEffect, useState } from 'react';
import { ImageOff, Sparkles } from 'lucide-react';
import { regenerateDebateCover, selectDebateCover } from '../../../api/admin/debates';
import type { AdminDebateCard } from '../../../api/admin/types';
import { FormField } from '../../account/FormField';
import { Button, useToast } from '../../ui';
import { ActionDialog } from '../ActionDialog';
import { formatTime, formatUsd } from '../helpers';
import { Panel } from '../users/UserSections';

const POLL_MS = 5000;

type Pending = { kind: 'regenerate' } | { kind: 'select'; version: string | null };

/**
 * The debate's AI cover (backend services/media/cover.py): the one shown, the latest build,
 * every version; a new one on the system key (free for the owner) and the version shown,
 * or none (the markup cover, for a picture that should not be in the gallery).
 */
export const CoverPanel = ({ card, permissions, onChanged }: { card: AdminDebateCard; permissions: string[]; onChanged: () => void }) => {
  const toast = useToast();
  const { cover, debate } = card;
  const [pending, setPending] = useState<Pending | null>(null);
  const [hook, setHook] = useState('');
  const drawing = cover.status === 'queued' || cover.status === 'running';
  const canDraw = permissions.includes('debates') && ['completed', 'stopped'].includes(debate.status) && !drawing;
  const canSelect = permissions.includes('moderation');
  const current = cover.versions.find((v) => v.id === cover.current) ?? null;

  // A cover takes about a minute: reload the card until it is done.
  useEffect(() => {
    if (!drawing) return;
    const timer = window.setInterval(onChanged, POLL_MS);
    return () => window.clearInterval(timer);
  }, [drawing, onChanged]);

  if (cover.status === 'none' && !cover.versions.length && !canDraw) return null;

  return (
    <Panel title="AI cover" aside={drawing ? 'drawing…' : cover.status}>
      <div className="grid gap-3 px-4 py-3">
        {current ? (
          <a href={current.full_url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-[10px] border border-line">
            <img src={current.url} alt={current.hook ? `AI cover: ${current.hook}` : 'AI cover'} className="aspect-video w-full object-cover" />
          </a>
        ) : (
          <p className="text-xs text-muted">{cover.versions.length ? 'The markup cover is shown.' : 'No AI cover: the markup cover is shown.'}</p>
        )}
        {current && (
          <div className="text-xs text-text-3">
            “{current.hook}” · {current.source} · {formatTime(current.created_at ?? '')} · {formatUsd(current.cost_usd)}
            {current.tries > 1 && ` · ${current.tries} tries`}
            {current.own_key && ' · own key'}
          </div>
        )}
        {cover.error && <div className="text-xs text-con">{cover.error}</div>}

        {cover.versions.length > 1 && (
          <div className="grid grid-cols-3 gap-2">
            {cover.versions.map((v) => (
              <button
                key={v.id}
                type="button"
                disabled={!canSelect || v.id === cover.current}
                onClick={() => setPending({ kind: 'select', version: v.id })}
                title={v.hook}
                className={`overflow-hidden rounded-md outline-2 outline-offset-2 enabled:cursor-pointer ${v.id === cover.current ? 'outline-accent' : 'outline-transparent enabled:hover:outline-line-3'}`}
              >
                <img src={v.url} alt="" loading="lazy" className="aspect-video w-full object-cover" />
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {canDraw && (
            <Button size="sm" variant="secondary" icon={<Sparkles className="size-4" />} onClick={() => setPending({ kind: 'regenerate' })}>
              {cover.versions.length ? 'New version (free)' : 'Generate (free)'}
            </Button>
          )}
          {canSelect && cover.current && (
            <Button size="sm" variant="secondary" icon={<ImageOff className="size-4" />} onClick={() => setPending({ kind: 'select', version: null })}>
              Show the markup cover
            </Button>
          )}
        </div>
      </div>

      <ActionDialog
        open={pending?.kind === 'regenerate'}
        title="Draw a new cover?"
        body="On the system key, free for the owner; it becomes the cover shown. About a minute."
        confirmLabel="Draw"
        onClose={() => setPending(null)}
        onSubmit={async (reason) => {
          const out = await regenerateDebateCover(debate.id, reason, hook.trim());
          setHook('');
          toast.success(out.message);
          onChanged();
        }}
      >
        <FormField label="Hook" optional value={hook} maxLength={22} placeholder="The art director writes one" onChange={(e) => setHook(e.target.value)} />
      </ActionDialog>

      <ActionDialog
        open={pending?.kind === 'select'}
        title={pending?.kind === 'select' && pending.version === null ? 'Show the markup cover?' : 'Show this version?'}
        body={pending?.kind === 'select' && pending.version === null ? 'The AI cover stays in the versions; the gallery, link previews and the owner see the face-off cover.' : 'It becomes the cover shown everywhere.'}
        confirmLabel="Change"
        autoFocusReason
        onClose={() => setPending(null)}
        onSubmit={async (reason) => {
          if (pending?.kind !== 'select') return;
          const out = await selectDebateCover(debate.id, reason, pending.version);
          toast.success(out.message);
          onChanged();
        }}
      />
    </Panel>
  );
};
