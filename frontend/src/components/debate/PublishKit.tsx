import { Check, Copy, Download } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import type { Timeline } from '../../api/timeline';
import type { DebateDetail } from '../../api/types';
import { useToast } from '../ui';
import { downloadBlob, type SpeakerInfo } from './helpers';
import { renderThumbnail, thumbnailVariants, youtubeDescription, youtubeTags, youtubeTitle } from './youtubeKit';

interface Props {
  debate: DebateDetail;
  lineup: SpeakerInfo[];
  timeline: Timeline | null;
  /** Draw the thumbnails only once the panel is open. */
  active: boolean;
}

const CopyButton = ({ text, label }: { text: string; label: string }) => {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      toast.error('Could not copy to the clipboard');
    }
  };
  return (
    <button type="button" onClick={copy} aria-label={`Copy ${label}`} className={`inline-flex items-center gap-1.5 text-xs font-semibold cursor-pointer ${copied ? 'text-ok' : 'text-text-3 hover:text-text'}`}>
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
};

const Field = ({ label, action, children }: { label: string; action: ReactNode; children: ReactNode }) => (
  <div className="grid gap-2">
    <div className="flex items-center justify-between">
      <span className="text-xs font-semibold text-text-3">{label}</span>
      {action}
    </div>
    {children}
  </div>
);

/** PUBLISH KIT: thumbnail, title, description with chapters and tags for YouTube Studio. */
export const PublishKit = ({ debate, lineup, timeline, active }: Props) => {
  const toast = useToast();
  const [pick, setPick] = useState(0);
  const [thumbs, setThumbs] = useState<{ key: string; urls: string[]; blobs: Blob[] } | null>(null);
  const topic = debate.settings.topic || debate.title || 'AI debate';
  const debaters = lineup.filter((s) => s.tag !== 'HOST' && s.tag !== 'JUDGE');
  const title = youtubeTitle(topic, debaters, debate.settings.format);
  const description = youtubeDescription(debate, lineup, timeline);
  const tags = youtubeTags(debate, lineup);
  const variants = thumbnailVariants(topic, debaters, timeline, timeline?.total_ms ?? debate.duration_ms);
  const thumbKey = variants.map((v) => `${v.id}:${v.text}:${v.tag}`).join('|');

  const drawnKey = thumbs?.key;
  useEffect(() => {
    if (!active || drawnKey === thumbKey) return;
    let cancelled = false;
    Promise.all(thumbnailVariants(topic, debaters, timeline, timeline?.total_ms ?? debate.duration_ms).map(renderThumbnail))
      .then((blobs) => {
        if (!cancelled) setThumbs({ key: thumbKey, urls: blobs.map((b) => URL.createObjectURL(b)), blobs });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // The key covers every input of the drawings.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, thumbKey, drawnKey]);

  // Free the previous drawings when new ones arrive, and the last ones on unmount.
  useEffect(() => () => thumbs?.urls.forEach((u) => URL.revokeObjectURL(u)), [thumbs]);

  const current = thumbs?.key === thumbKey ? thumbs : null;
  const saveThumbnail = () => {
    const blob = current?.blobs[pick];
    if (!blob) {
      toast.info('The thumbnail is still being drawn');
      return;
    }
    downloadBlob(blob, `debate-${debate.id}-thumbnail.png`);
  };

  return (
    <section className="grid min-w-0 gap-[18px] rounded-panel border border-white/6 bg-surface p-[18px]">
      <div>
        <div className="font-mono text-[11px] tracking-[0.08em] text-muted">PUBLISH KIT</div>
        <div className="mt-1.5 text-[13px] text-text-3">Title, description with chapters, tags and a thumbnail — ready to paste into YouTube Studio.</div>
      </div>

      <Field
        label="Thumbnail"
        action={
          <button type="button" onClick={saveThumbnail} className="inline-flex items-center gap-1.5 text-xs font-semibold text-text-3 hover:text-text cursor-pointer">
            <Download className="size-3.5" /> PNG
          </button>
        }
      >
        <div className="aspect-video overflow-hidden rounded-xl bg-surface-2">{current && <img src={current.urls[pick]} alt="Thumbnail preview" className="size-full object-cover" />}</div>
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Thumbnail style">
          {variants.map((v, i) => (
            <button
              key={v.id}
              type="button"
              role="radio"
              aria-checked={pick === i}
              onClick={() => setPick(i)}
              className={`aspect-video overflow-hidden rounded-lg bg-surface-2 outline-2 outline-offset-2 cursor-pointer ${pick === i ? 'outline-accent' : 'outline-transparent hover:outline-line-3'}`}
            >
              {current && <img src={current.urls[i]} alt="" className="size-full object-cover" />}
            </button>
          ))}
        </div>
      </Field>

      <Field label="Title" action={<CopyButton text={title} label="title" />}>
        <div className="rounded-xl border border-white/6 bg-ink px-3.5 py-3 text-sm font-semibold leading-snug">{title}</div>
      </Field>

      <Field label="Description" action={<CopyButton text={description} label="description" />}>
        <div className="max-h-[180px] overflow-auto whitespace-pre-wrap rounded-xl border border-white/6 bg-ink px-3.5 py-3 text-[13px] leading-relaxed text-text-3">{description}</div>
      </Field>

      <Field label="Tags" action={<CopyButton text={tags.join(' ')} label="tags" />}>
        <div className="flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <span key={t} className="rounded-full border border-white/8 bg-surface-2 px-2.5 py-1 text-xs text-text-2">
              {t}
            </span>
          ))}
        </div>
      </Field>
    </section>
  );
};
