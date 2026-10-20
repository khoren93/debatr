import { ExternalLink, Swords } from 'lucide-react';
import { Suspense, lazy, useEffect, useRef, useState, type RefObject } from 'react';
import type { TurnVisuals } from '../../api/types';
import type { SceneDispute, TimelineVisual } from '../../api/visuals';
import { POSTER_H, POSTER_W } from '../../video/constants';
import type { SceneCast } from '../../video/visuals/SceneStage';
import { Modal, Spinner } from '../ui';
import { CHECK_STYLES, TYPE_LABELS, liveVisual, rebase } from './sceneBoard';

// Remotion draws the stills and replays: browser-only, loaded once a card scrolls into view or opens.
const SceneThumbnail = lazy(() => import('./SceneStill').then((m) => ({ default: m.SceneThumbnail })));
const ScenePlayer = lazy(() => import('./SceneStill').then((m) => ({ default: m.ScenePlayer })));

const useInView = (ref: RefObject<HTMLElement | null>) => {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { rootMargin: '240px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, seen]);
  return seen;
};

const domain = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
};

interface CardProps {
  visual: TimelineVisual;
  cast: SceneCast;
  mediaBase: string;
  checking: boolean;
  onOpen: () => void;
}

const SceneCard = ({ visual, cast, mediaBase, checking, onOpen }: CardProps) => {
  const ref = useRef<HTMLButtonElement>(null);
  const inView = useInView(ref);
  const still: TimelineVisual = { ...visual, check: null, disputes: [] }; // badges are HTML below
  const disputes = visual.disputes ?? [];
  const check = visual.check;
  const chips = Boolean(check) || checking || disputes.length > 0;
  return (
    <div className="w-[78%] min-w-0 shrink-0 snap-start sm:w-auto">
      <button ref={ref} type="button" onClick={onOpen} className="block w-full overflow-hidden rounded-[12px] border border-line-2 bg-ink text-left transition-colors hover:border-line-3 cursor-pointer" style={{ aspectRatio: `${POSTER_W} / ${POSTER_H}` }} aria-label={`${TYPE_LABELS[visual.scene.type] ?? 'Scene'} — open`}>
        {/* The observer starts in an effect: the server and the first render show the empty card. */}
        {inView && (
          <Suspense fallback={null}>
            <SceneThumbnail visual={still} cast={cast} mediaBase={mediaBase} />
          </Suspense>
        )}
      </button>
      {chips && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {check && <span className={`whitespace-nowrap rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${CHECK_STYLES[check.verdict].className}`}>{CHECK_STYLES[check.verdict].label}</span>}
          {!check && checking && (
            <span className="inline-flex items-center gap-1 rounded-md border border-line-3 px-1.5 py-0.5 font-mono text-[10px] text-muted">
              <Spinner className="size-2.5" /> fact-checking
            </span>
          )}
          {disputes.length > 0 && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-host/40 bg-host/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-host">
              <Swords className="size-2.5" /> disputed by {[...new Set(disputes.map((d) => d.by_name))].join(', ')}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

const SceneDetails = ({ visual, cast, mediaBase, onClose }: { visual: TimelineVisual; cast: SceneCast; mediaBase: string; onClose: () => void }) => {
  const speaker = cast.speakers.find((s) => s.id === visual.speaker_id);
  const check = visual.check;
  const scene = visual.scene;
  return (
    <Modal open onClose={onClose} title={`${TYPE_LABELS[scene.type] ?? 'Scene'}${speaker ? ` · ${speaker.name}` : ''}`} width="lg">
      <div className="overflow-hidden rounded-[12px] border border-line-2">
        <Suspense
          fallback={
            <div className="grid place-items-center text-muted" style={{ aspectRatio: `${POSTER_W} / ${POSTER_H}` }}>
              <Spinner />
            </div>
          }
        >
          <ScenePlayer visual={visual} cast={cast} mediaBase={mediaBase} />
        </Suspense>
      </div>
      {check && (
        <div className="mt-4">
          <span className={`rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold ${CHECK_STYLES[check.verdict].className}`}>{CHECK_STYLES[check.verdict].label}</span>
          {check.note && <p className="mt-2 text-sm leading-relaxed text-text-2">{check.note}</p>}
          {check.sources.length > 0 && (
            <ul className="mt-2 grid gap-1">
              {check.sources.map((s) => (
                <li key={s.url}>
                  <a href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-text">
                    <ExternalLink className="size-3 shrink-0" /> {s.title || domain(s.url)}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {(visual.disputes ?? []).length > 0 && (
        <div className="mt-4 grid gap-2">
          {(visual.disputes ?? []).map((d) => (
            <div key={`${d.seq_index}-${d.by_id}`} className="rounded-field border border-host/30 bg-host/10 px-3 py-2 text-sm">
              <span className="font-semibold text-host">{d.by_name} disputed this</span>
              {d.reason && <span className="text-text-2"> — {d.reason}</span>}
            </div>
          ))}
        </div>
      )}
      {scene.type === 'image' && scene.source_url && (
        <a href={scene.source_url} target="_blank" rel="noopener noreferrer nofollow" className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted hover:text-text">
          <ExternalLink className="size-3" /> {scene.credit || 'Source'}
        </a>
      )}
      {scene.type === 'image' && scene.kind === 'ai' && <p className="mt-3 text-xs text-muted">AI-generated image.</p>}
    </Modal>
  );
};

interface Props {
  seq: number;
  speakerId: string;
  visuals: TurnVisuals | null | undefined;
  /** This turn's scenes in the video (after the audio build), preferred over the live ones. */
  timelineVisuals: TimelineVisual[];
  disputes: Map<string, SceneDispute[]>;
  cast: SceneCast;
  mediaBase: string;
}

/** The board of a turn's visual scenes under its text (live while the debate runs). */
export const TurnScenes = ({ seq, speakerId, visuals, timelineVisuals, disputes, cast, mediaBase }: Props) => {
  const [open, setOpen] = useState<string | null>(null);
  const checking = visuals?.status === 'checking';
  const pending = new Set((visuals?.scenes ?? []).filter((s) => s.checkable && !s.check).map((s) => s.key));
  const items: TimelineVisual[] =
    timelineVisuals.length > 0
      ? timelineVisuals.map(rebase)
      : (visuals?.scenes ?? []).filter((s) => s.scene.type !== 'image' || (mediaBase && s.scene.src)).map((s) => liveVisual(seq, speakerId, s.key, s.scene, s.check));
  const withDisputes = items.map((v) => (v.key && disputes.has(v.key) ? { ...v, disputes: disputes.get(v.key) } : v));

  if (visuals?.status === 'designing' && withDisputes.length === 0) {
    return (
      <div className="mt-3 inline-flex items-center gap-2 rounded-field border border-dashed border-line-2 px-3 py-2 text-xs text-muted">
        <Spinner className="size-3" /> Designing scenes…
      </div>
    );
  }
  if (withDisputes.length === 0) return null;
  const opened = withDisputes.find((v) => v.id === open) ?? null;
  return (
    <>
      {/* Phones: a strip of large cards to swipe through, running to the screen edge; wider screens: a grid. */}
      <div className="mt-3 -mr-8 flex snap-x snap-mandatory gap-2 overflow-x-auto pr-8 pb-1 sm:mr-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:pr-0 sm:pb-0">
        {withDisputes.map((v) => (
          <SceneCard key={v.id} visual={v} cast={cast} mediaBase={mediaBase} checking={checking && pending.has(v.key ?? '')} onOpen={() => setOpen(v.id)} />
        ))}
      </div>
      {opened && <SceneDetails visual={opened} cast={cast} mediaBase={mediaBase} onClose={() => setOpen(null)} />}
    </>
  );
};
