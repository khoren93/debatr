import { Download, ImageIcon, Sparkles, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';
import { getErrorMessage } from '../../api/client';
import { deleteCoverVersion, generateCover, selectCover } from '../../api/debates';
import type { Cover, DebateDetail } from '../../api/types';
import { useLocalKey } from '../../lib/localKeys';
import { accountPath } from '../account/tabs';
import { Button, Progress, useToast } from '../ui';

const HOOK_MAX = 22;

interface Props {
  debate: DebateDetail;
  onChange: (cover: Cover) => void;
}


/**
 * The owner's AI cover (backend services/media/cover.py): the current version, a new one (the
 * art director's hook or the owner's own), the versions to pick from, the markup cover instead,
 * and YouTube's 1280×720 file. The cover shows in the gallery, link previews and the video kit.
 */
export const CoverCard = ({ debate, onChange }: Props) => {
  const toast = useToast();
  const browserKey = useLocalKey('openrouter');
  const [hook, setHook] = useState('');
  const [busy, setBusy] = useState(false);
  const { cover } = debate;
  const drawing = cover.status === 'queued' || cover.status === 'running';
  // No credits, but this browser holds an OpenRouter key: the cover runs on it.
  const onBrowserKey = cover.reason === 'no_balance' && !!browserKey;
  const canGenerate = cover.can_generate || onBrowserKey;

  const run = async (action: () => Promise<Cover>, done?: string) => {
    setBusy(true);
    try {
      onChange(await action());
      if (done) toast.success(done);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const generate = () =>
    run(async () => {
      const out = await generateCover(debate.id, { hook: hook.trim() || undefined, user_provider_key: browserKey || undefined });
      setHook('');
      return out;
    }, 'Drawing the cover — about a minute');

  const price = browserKey ? 'your OpenRouter key' : `$${cover.price_usd.toFixed(2)}`;
  const current = cover.current;

  return (
    <section id="cover-card" className="grid min-w-0 gap-3 rounded-panel border border-white/6 bg-surface p-[18px]">
      <div className="flex items-baseline justify-between gap-2.5">
        <span className="font-mono text-[11px] tracking-[0.08em] text-muted">AI COVER</span>
        <span className="text-xs text-dim">Gallery, link previews, YouTube</span>
      </div>

      <div className="relative aspect-video overflow-hidden rounded-xl bg-ink">
        {current ? (
          <img src={current.small_url} srcSet={`${current.small_url} 768w, ${current.url} 1536w`} sizes="420px" alt={current.hook ? `AI cover: ${current.hook}` : 'AI cover'} className="size-full object-cover" />
        ) : (
          <div className="grid size-full place-items-center px-6 text-center text-[13px] text-text-3">
            <span>
              <ImageIcon className="mx-auto mb-2 size-5 text-dim" />
              {cover.versions.length ? 'The face-off cover is shown.' : 'No AI cover yet: the face-off cover is shown everywhere.'}
            </span>
          </div>
        )}
        {drawing && (
          <div className="absolute inset-x-3 bottom-3 grid gap-1.5 rounded-[10px] bg-ink/85 p-2.5 backdrop-blur-sm">
            <span className="font-mono text-[10px] tracking-[0.08em] text-host">{cover.status === 'queued' ? 'QUEUED' : 'DRAWING THE COVER'}</span>
            <Progress value={cover.status === 'queued' ? 0.08 : 0.5} gradient height={4} />
          </div>
        )}
      </div>

      {cover.status === 'error' && cover.error && <div className="rounded-[10px] border border-con/25 bg-con/8 px-3 py-2 text-xs text-con">{cover.error}</div>}

      {cover.versions.length > 0 && (
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Cover versions">
          {cover.versions.map((v) => (
            <div key={v.id} className="group relative">
              <button
                type="button"
                role="radio"
                aria-checked={current?.id === v.id}
                aria-label={v.hook || 'Cover version'}
                disabled={busy}
                onClick={() => run(() => selectCover(debate.id, v.id))}
                className={`block aspect-video w-full overflow-hidden rounded-lg bg-surface-2 outline-2 outline-offset-2 cursor-pointer ${current?.id === v.id ? 'outline-accent' : 'outline-transparent hover:outline-line-3'}`}
              >
                <img src={v.small_url} alt="" loading="lazy" className="size-full object-cover" />
              </button>
              <button
                type="button"
                aria-label="Delete this version"
                disabled={busy}
                onClick={() => run(() => deleteCoverVersion(debate.id, v.id), 'Version deleted')}
                className="absolute top-1 right-1 grid size-6 place-items-center rounded-md bg-ink/80 text-text-3 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:text-con cursor-pointer"
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          ))}
          <button
            type="button"
            role="radio"
            aria-checked={!current}
            disabled={busy}
            onClick={() => run(() => selectCover(debate.id, null))}
            className={`grid aspect-video place-items-center rounded-lg border border-dashed border-line-2 bg-ink px-1 text-center text-[11px] text-text-3 outline-2 outline-offset-2 cursor-pointer ${!current ? 'outline-accent' : 'outline-transparent hover:outline-line-3'}`}
          >
            Face-off cover
          </button>
        </div>
      )}

      {cover.reason === 'off' ? (
        <div className="text-xs text-muted">AI covers are turned off right now.</div>
      ) : (
        <div className="grid gap-2">
          <label className="grid gap-1.5">
            <span className="text-xs font-semibold text-text-3">Your own hook (optional)</span>
            <input
              value={hook}
              onChange={(e) => setHook(e.target.value.slice(0, HOOK_MAX))}
              maxLength={HOOK_MAX}
              placeholder="The art director writes one"
              className="h-10 rounded-[10px] border border-white/8 bg-ink px-3 text-sm uppercase placeholder:normal-case placeholder:text-dim focus:border-accent/50 focus:outline-none"
            />
            <span className="text-[11px] text-dim">Up to 4 words, {HOOK_MAX} characters, in big letters on the cover.</span>
          </label>
          <div className="flex flex-wrap items-center justify-between gap-2.5">
            {current ? (
              <a href={current.yt_url} download={`debate-${debate.id}-cover.jpg`} className="inline-flex items-center gap-1.5 text-xs font-semibold text-text-3 hover:text-text">
                <Download className="size-3.5" /> 1280×720 for YouTube
              </a>
            ) : (
              <span />
            )}
            <Button size="sm" onClick={generate} loading={busy && !drawing} disabled={!canGenerate || busy || drawing} icon={<Sparkles className="size-3.5" />}>
              {cover.versions.length ? 'New version' : 'Generate cover'} · {price}
            </Button>
          </div>
          {cover.reason === 'no_balance' && !browserKey && (
            <div className="text-xs text-muted">
              A cover needs credits or your own OpenRouter key: <Link to={accountPath('billing')} className="text-accent hover:text-accent-hover">top up</Link> or{' '}
              <Link to={accountPath('keys')} target="_blank" className="text-accent hover:text-accent-hover">
                add a key
              </Link>
              .
            </div>
          )}
          {cover.reason === 'not_finished' && <div className="text-xs text-muted">A cover can be drawn once the debate has finished.</div>}
        </div>
      )}
    </section>
  );
};
