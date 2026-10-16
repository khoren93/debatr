import type { RenderMediaOnWebProgress } from '@remotion/web-renderer';
import { Download, RefreshCw, Square, Video } from 'lucide-react';
import { useEffect, useRef, useState, type ComponentType } from 'react';
import { reportRender } from '../../api/debates';
import type { Timeline } from '../../api/timeline';
import { formatDuration } from '../../lib/format';
import { FPS, LONG_H, LONG_W, SHORT_H, SHORT_W } from '../../video/constants';
import { DebateLong } from '../../video/DebateLong';
import { DebateShort } from '../../video/DebateShort';
import { SCALE_720P, checkRenderSupport, renderMp4 } from '../../video/render';
import { longDurationInFrames, shortDurationInFrames } from '../../video/utils';
import { preloadSceneAssets } from '../../video/visuals/geoLoader';
import { Button, Progress, Select } from '../ui';

type AnyComposition = ComponentType<Record<string, unknown>>;

interface Props {
  kind: 'long' | 'short';
  debateId: string;
  timeline: Timeline | null;
  mediaBase: string;
  highlightIndex: number;
  onHighlightChange?: (index: number) => void;
  /** 2 = 4K (2160p from 1080p), 1 = full resolution, SCALE_720P = 720p, 0.5 = draft. */
  defaultScale: number;
  /** Owners report finished renders for the usage stats. */
  reportRenders: boolean;
  className?: string;
}

const formatBytes = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1e3)} KB`);

/** One deliverable in the EXPORTS panel: status, meta, quality, render button, download. */
export const ExportCard = ({ kind, debateId, timeline, mediaBase, highlightIndex, onHighlightChange, defaultScale, reportRenders, className = '' }: Props) => {
  const [support, setSupport] = useState<{ canRender: boolean; issues: string[] } | null>(null);
  const [scale, setScale] = useState(defaultScale);
  const [progress, setProgress] = useState<RenderMediaOnWebProgress | null>(null);
  const [result, setResult] = useState<{ url: string; size: number; ms: number } | null>(null);
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
    if (result) URL.revokeObjectURL(result.url);
    setResult(null);
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
      setResult({ url: URL.createObjectURL(blob), size: blob.size, ms: took });
      if (reportRenders) reportRender(debateId, kind).catch(() => undefined);
    } catch (e) {
      const message = (e as Error).message;
      setError(/abort/i.test(message) ? 'Render cancelled' : message);
    } finally {
      setBusy(false);
    }
  };

  const pct = progress ? Math.round(progress.progress * 100) : 0;
  const status = !timeline
    ? { label: 'NO AUDIO', color: '#8B90A0' }
    : busy
      ? { label: `RENDERING ${pct}%`, color: '#FFC46B' }
      : result
        ? { label: 'DONE', color: '#52D889' }
        : error
          ? { label: 'FAILED', color: '#FF7A66' }
          : support?.canRender === false
            ? { label: 'UNSUPPORTED', color: '#FF7A66' }
            : { label: 'READY', color: '#52D889' };
  const qualityLabel = `${Math.round(height * scale)}p`;
  const fileName = isLong ? `debate-${debateId}.mp4` : `debate-${debateId}-short-${highlightIndex + 1}.mp4`;

  return (
    <div className={`rounded-[14px] border border-line bg-ink p-3.5 ${className}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          {isLong ? <span className="h-[13px] w-[22px] rounded-[3px] bg-accent" /> : <span className="h-4 w-[9px] rounded-[2px] bg-pro" />}
          <span className="text-sm font-bold">{isLong ? 'YouTube video' : 'Short'}</span>
        </div>
        <span className="font-mono text-[11px]" style={{ color: status.color }}>
          {status.label}
        </span>
      </div>
      <div className="mt-1.5 text-xs text-muted">
        {isLong ? '16:9' : '9:16'} · {qualityLabel}
        {timeline && (
          <>
            {' '}
            · {formatDuration(ms)} · {frames.toLocaleString()} frames
          </>
        )}
        {!isLong && ' · hook + captions + end card'}
      </div>

      {!isLong && timeline && timeline.highlights.length > 0 && (
        <label className="mt-2.5 block">
          <span className="text-xs text-text-3">Moment</span>
          <Select
            value={highlightIndex}
            onChange={(e) => {
              onHighlightChange?.(Number(e.target.value));
              if (result) {
                URL.revokeObjectURL(result.url);
                setResult(null);
              }
            }}
            disabled={busy}
            className="mt-1.5 !bg-surface !py-2 text-[13px]"
          >
            {timeline.highlights.map((h) => (
              <option key={h.index} value={h.index}>
                {h.title} ({Math.round((h.end_ms - h.start_ms) / 1000)}s)
              </option>
            ))}
          </Select>
        </label>
      )}

      {timeline && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-xs text-text-3">Quality</span>
          <Select value={scale} onChange={(e) => setScale(Number(e.target.value))} disabled={busy} className="!w-auto !bg-surface !py-1.5 text-xs">
            <option value={2}>{height * 2}p · 4K, slow</option>
            <option value={1}>{height}p</option>
            <option value={SCALE_720P}>{Math.round(height * SCALE_720P)}p · faster</option>
            <option value={0.5}>{Math.round(height * 0.5)}p · draft</option>
          </Select>
        </div>
      )}

      {(busy || progress) && timeline && (
        <div className="mt-3">
          <Progress value={progress?.progress ?? 0} gradient height={5} />
          <div className="mt-1.5 flex justify-between font-mono text-[11px] text-muted">
            <span>
              {(progress?.encodedFrames ?? 0).toLocaleString()} / {frames.toLocaleString()} frames
            </span>
            <span>{busy && progress && progress.renderEstimatedTime > 0 ? `~${Math.ceil(progress.renderEstimatedTime / 1000)}s left` : busy ? 'starting…' : ''}</span>
          </div>
        </div>
      )}

      {support && !support.canRender && timeline && (
        <div className="mt-3 rounded-[10px] border border-con/30 bg-con/10 px-3 py-2 text-xs text-[#ffb3a7] leading-relaxed">
          This browser cannot render video ({support.issues.join('; ')}). Use Chrome or Edge.
        </div>
      )}
      {error && !busy && <div className="mt-3 rounded-[10px] border border-con/30 bg-con/10 px-3 py-2 text-xs text-[#ffb3a7] leading-relaxed">{error}</div>}

      {timeline && (
        <div className="mt-3 flex gap-2">
          {result ? (
            <>
              <a
                href={result.url}
                download={fileName}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-[10px] bg-accent px-3 py-2.5 text-[13px] font-bold text-ink hover:bg-accent-hover"
              >
                <Download className="size-3.5" /> Download MP4
              </a>
              <Button variant="secondary" size="sm" onClick={run} icon={<RefreshCw className="size-3.5" />} title={`Rendered in ${(result.ms / 1000).toFixed(1)}s · ${formatBytes(result.size)}`}>
                Re-render
              </Button>
            </>
          ) : busy ? (
            <Button variant="secondary" size="sm" className="flex-1" onClick={() => abortRef.current?.abort()} icon={<Square className="size-3 fill-current" />}>
              Cancel
            </Button>
          ) : (
            <Button size="sm" className="flex-1" onClick={run} disabled={support?.canRender === false || frames === 0} icon={<Video className="size-3.5" />}>
              Render MP4
            </Button>
          )}
        </div>
      )}
    </div>
  );
};
