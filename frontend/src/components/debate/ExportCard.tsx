import type { RenderMediaOnWebProgress } from '@remotion/web-renderer';
import { Download, RefreshCw, Video } from 'lucide-react';
import { useEffect, useRef, useState, type ComponentType, type MouseEvent } from 'react';
import { reportRender } from '../../api/debates';
import type { Timeline } from '../../api/timeline';
import { formatDuration } from '../../lib/format';
import { FPS, LONG_H, LONG_W, SHORT_H, SHORT_W } from '../../video/constants';
import { DebateLong } from '../../video/DebateLong';
import { DebateShort } from '../../video/DebateShort';
import { SCALE_720P, checkRenderSupport, renderMp4 } from '../../video/render';
import { longDurationInFrames, shortDurationInFrames } from '../../video/utils';
import { preloadSceneAssets } from '../../video/visuals/geoLoader';

type AnyComposition = ComponentType<Record<string, unknown>>;

interface Props {
  kind: 'long' | 'short';
  debateId: string;
  timeline: Timeline | null;
  mediaBase: string;
  highlightIndex: number;
  onHighlightChange?: (index: number) => void;
  /** 2 = 4K (2160p from 1080p), 1 = full resolution, SCALE_720P = 720p. */
  defaultScale: number;
  /** Owners report finished renders for the usage stats. */
  reportRenders: boolean;
  /** This format is the one in the player. */
  selected: boolean;
  onSelect: () => void;
}

const QUALITIES = [
  { scale: SCALE_720P, label: '720p' },
  { scale: 1, label: '1080p' },
  { scale: 2, label: '4K' },
];

const qualityLabel = (scale: number) => QUALITIES.find((q) => q.scale === scale)?.label ?? `${Math.round(1080 * scale)}p`;

const formatBytes = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1e3)} KB`);

const stop = (e: MouseEvent) => e.stopPropagation();

/** Option chips (quality, Short moment). */
const Chips = <T extends string | number>({ label, options, value, onChange, disabled }: { label: string; options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; disabled: boolean }) => (
  <div className="grid gap-1.5">
    <div className="text-xs text-muted">{label}</div>
    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={label}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={(e) => {
              stop(e);
              onChange(o.value);
            }}
            className={`max-w-full truncate rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors cursor-pointer disabled:cursor-default disabled:opacity-60 ${active ? 'border-text bg-text text-ink' : 'border-white/8 bg-surface-2 text-text-2 hover:border-line-3'}`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  </div>
);

/** One deliverable in the export panel: status, spec, options, render and download. */
export const ExportCard = ({ kind, debateId, timeline, mediaBase, highlightIndex, onHighlightChange, defaultScale, reportRenders, selected, onSelect }: Props) => {
  const [support, setSupport] = useState<{ canRender: boolean; issues: string[] } | null>(null);
  const [scale, setScale] = useState(QUALITIES.some((q) => q.scale === defaultScale) ? defaultScale : 1);
  const [progress, setProgress] = useState<RenderMediaOnWebProgress | null>(null);
  const [result, setResult] = useState<{ url: string; size: number; ms: number; scale: number; highlight: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const isLong = kind === 'long';
  const width = isLong ? LONG_W : SHORT_W;
  const height = isLong ? LONG_H : SHORT_H;
  const frames = timeline ? (isLong ? longDurationInFrames(timeline) : shortDurationInFrames(timeline, highlightIndex)) : 0;
  const ms = Math.round((frames / FPS) * 1000);

  useEffect(() => {
    if (!timeline) return;
    let cancelled = false;
    checkRenderSupport(width, height, false)
      .then((r) => {
        if (!cancelled) setSupport({ canRender: r.canRender, issues: r.issues.map((i) => `${i.severity}: ${i.message}`) });
      })
      .catch((e: Error) => {
        if (!cancelled) setSupport({ canRender: false, issues: [e.message] });
      });
    return () => {
      cancelled = true;
    };
  }, [width, height, timeline]);

  // Abort a running render when the card unmounts.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const run = async () => {
    if (!timeline) return;
    setBusy(true);
    setError(null);
    setProgress(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const composition = (isLong ? DebateLong : DebateShort) as unknown as AnyComposition;
      const inputProps: Record<string, unknown> = isLong ? { timeline, mediaBase } : { timeline, mediaBase, highlightIndex };
      await preloadSceneAssets(timeline);
      const { blob, ms: took } = await renderMp4({
        id: isLong ? 'DebateLong' : `DebateShort${highlightIndex}`,
        component: composition,
        inputProps,
        width,
        height,
        durationInFrames: frames,
        muted: false,
        scale,
        onProgress: setProgress,
        signal: ctrl.signal,
      });
      if (result) URL.revokeObjectURL(result.url);
      setResult({ url: URL.createObjectURL(blob), size: blob.size, ms: took, scale, highlight: highlightIndex });
      if (reportRenders) reportRender(debateId, kind).catch(() => undefined);
    } catch (e) {
      const message = (e as Error).message;
      setError(/abort/i.test(message) ? 'Render cancelled' : message);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  const ready = result !== null && result.scale === scale && (isLong || result.highlight === highlightIndex);
  const unsupported = support?.canRender === false;
  const pct = progress ? Math.round(progress.progress * 100) : 0;
  const status = !timeline
    ? { label: 'NO AUDIO', color: '#8B90A0' }
    : busy
      ? { label: `RENDERING ${pct}%`, color: '#FFC46B' }
      : ready
        ? { label: 'READY', color: '#52D889' }
        : unsupported
          ? { label: 'UNSUPPORTED', color: '#FF7A66' }
          : error
            ? { label: 'FAILED', color: '#FF7A66' }
            : { label: 'NOT RENDERED', color: '#8B90A0' };
  const quality = qualityLabel(scale);
  const size = isLong ? quality : `${Math.round(SHORT_W * scale)}×${Math.round(SHORT_H * scale)}`;
  const spec = `${isLong ? '16:9' : '9:16'} · ${size}${timeline ? ` · ${formatDuration(ms)}` : ''}${isLong ? '' : ' · hook + captions + end card'}`;
  const fileName = (r: { scale: number; highlight: number }) => (isLong ? `debate-${debateId}-${qualityLabel(r.scale)}.mp4` : `debate-${debateId}-short-${r.highlight + 1}.mp4`);
  const moments = timeline?.highlights ?? [];
  const primary = selected ? 'bg-accent text-ink hover:bg-accent-hover' : 'bg-surface-3 text-text hover:bg-surface-4';
  const etaSec = progress && progress.renderEstimatedTime > 0 ? Math.ceil(progress.renderEstimatedTime / 1000) : null;

  return (
    <div
      onClick={onSelect}
      className={`grid cursor-pointer gap-3 rounded-[14px] border bg-ink p-3.5 transition-colors ${selected ? 'border-accent/45' : 'border-white/6 hover:border-line-2'}`}
    >
      <div className="flex items-start justify-between gap-2.5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-8 shrink-0 place-items-center rounded-[9px] bg-surface-2">
            {isLong ? <span className="h-3 w-5 rounded-[3px] bg-accent" /> : <span className="h-[17px] w-2.5 rounded-[3px] bg-pro" />}
          </span>
          <div className="min-w-0">
            <div className="text-sm font-bold">{isLong ? 'YouTube video' : 'Short'}</div>
            <div className="mt-0.5 text-xs text-muted">{spec}</div>
          </div>
        </div>
        <span className="shrink-0 pt-[3px] font-mono text-[10px] tracking-[0.06em]" style={{ color: status.color }}>
          {status.label}
        </span>
      </div>

      {timeline && !isLong && moments.length > 1 && (
        <Chips
          label="Moment"
          options={moments.map((h) => ({ value: h.index, label: `${h.title} · ${Math.round((h.end_ms - h.start_ms) / 1000)}s` }))}
          value={highlightIndex}
          onChange={(v) => onHighlightChange?.(v)}
          disabled={busy}
        />
      )}
      {timeline && <Chips label="Quality" options={QUALITIES.map((q) => ({ value: q.scale, label: q.label }))} value={scale} onChange={setScale} disabled={busy} />}

      {unsupported && timeline && <div className="rounded-[10px] border border-con/30 bg-con/10 px-3 py-2 text-xs leading-relaxed text-[#ffb3a7]">This browser cannot render video ({support.issues.join('; ')}). Use Chrome or Edge.</div>}
      {error && !busy && <div className="rounded-[10px] border border-con/30 bg-con/10 px-3 py-2 text-xs leading-relaxed text-[#ffb3a7]">{error}</div>}

      {timeline &&
        (busy ? (
          <div className="grid gap-1.5">
            <div className="h-1.5 overflow-hidden rounded-md bg-surface-3">
              <div className="h-full bg-[linear-gradient(90deg,#6C9CFF,#D9FF3D)] transition-[width] duration-100" style={{ width: `${pct}%` }} />
            </div>
            <div className="flex items-center justify-between gap-2 font-mono text-[11px] text-muted">
              <span>Rendering… keep this tab open{etaSec ? ` · ~${etaSec}s left` : ''}</span>
              <button
                type="button"
                onClick={(e) => {
                  stop(e);
                  abortRef.current?.abort();
                }}
                className="font-sans text-xs font-semibold text-text-3 hover:text-text cursor-pointer"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex gap-2">
              {ready ? (
                <a href={result.url} download={fileName(result)} onClick={stop} className={`flex h-[42px] flex-1 items-center justify-center gap-2 rounded-[11px] text-[13px] font-bold transition-colors ${primary}`}>
                  <Download className="size-4" /> {isLong ? 'Download MP4' : 'Download Short'}
                </a>
              ) : (
                <button
                  type="button"
                  onClick={(e) => {
                    stop(e);
                    onSelect();
                    void run();
                  }}
                  disabled={unsupported || frames === 0}
                  className={`flex h-[42px] flex-1 items-center justify-center gap-2 rounded-[11px] text-[13px] font-bold transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 ${primary}`}
                >
                  <Video className="size-4" /> {isLong ? `Render ${quality}` : 'Render Short'}
                </button>
              )}
              {ready && (
                <button
                  type="button"
                  onClick={(e) => {
                    stop(e);
                    void run();
                  }}
                  title={`Re-render · last took ${(result.ms / 1000).toFixed(1)}s, ${formatBytes(result.size)}`}
                  aria-label="Re-render"
                  className="grid size-[42px] shrink-0 place-items-center rounded-[11px] border border-white/8 bg-surface-2 text-text-3 hover:text-text cursor-pointer"
                >
                  <RefreshCw className="size-4" />
                </button>
              )}
            </div>
            {result && !ready && (
              <div className="-mt-1 text-[11px] text-dim">
                Last render: {isLong ? qualityLabel(result.scale) : `moment ${result.highlight + 1}, ${qualityLabel(result.scale)}`} ·{' '}
                <a href={result.url} download={fileName(result)} onClick={stop} className="text-text-3 underline-offset-2 hover:text-text hover:underline">
                  download
                </a>
              </div>
            )}
          </>
        ))}
    </div>
  );
};
