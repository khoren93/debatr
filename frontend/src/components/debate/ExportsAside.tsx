import { Download, Sparkles } from 'lucide-react';
import type { Timeline } from '../../api/timeline';
import type { DebateDetail, DebateMedia } from '../../api/types';
import { formatDuration } from '../../lib/format';
import { SCALE_720P } from '../../video/render';
import { Button, Card, SectionLabel } from '../ui';
import { ExportCard } from './ExportCard';
import { Lineup } from './Lineup';
import { prettyVoice } from './helpers';

interface Props {
  debate: DebateDetail;
  media: DebateMedia | null;
  timeline: Timeline | null;
  mediaBase: string;
  highlightIndex: number;
  onHighlightChange: (i: number) => void;
  onGenerate: () => void;
}

/** Right column: EXPORTS (video, short, audio track) and LINEUP. */
export const ExportsAside = ({ debate, media, timeline, mediaBase, highlightIndex, onHighlightChange, onGenerate }: Props) => {
  const completed = debate.status === 'completed' || debate.status === 'stopped';
  const defaultScale = debate.media_plan?.quality === '4k' ? 2 : debate.media_plan?.quality === '720p' ? SCALE_720P : 1;
  const judgeVoice = prettyVoice(timeline?.speakers.find((s) => s.role === 'judge')?.voice_id);
  return (
    <aside className="grid gap-3.5 xl:sticky xl:top-6">
      {completed && (
        <Card padding="sm" className="!p-5">
          <div className="flex items-center justify-between">
            <SectionLabel>Exports</SectionLabel>
            {debate.is_owner && !timeline && media?.media_status !== 'queued' && media?.media_status !== 'running' && (
              <Button size="sm" variant="secondary" onClick={onGenerate} icon={<Sparkles className="size-3.5" />}>
                Generate audio
              </Button>
            )}
          </div>
          <div className="mt-3.5 grid gap-2.5">
            <ExportCard kind="long" debateId={debate.id} timeline={timeline} mediaBase={mediaBase} highlightIndex={0} defaultScale={defaultScale} reportRenders={debate.is_owner} />
            <ExportCard kind="short" debateId={debate.id} timeline={timeline} mediaBase={mediaBase} highlightIndex={highlightIndex} onHighlightChange={onHighlightChange} defaultScale={defaultScale} reportRenders={debate.is_owner} />
            <div className="flex items-center justify-between gap-3 rounded-[14px] border border-line bg-ink p-3.5">
              <div>
                <div className="text-sm font-bold">Audio track</div>
                <div className="mt-1 text-xs text-muted">{timeline ? `MP3 · mixed · ${formatDuration(timeline.total_ms)}` : 'MP3 · not built yet'}</div>
              </div>
              {timeline && media?.urls ? (
                <a href={media.urls.full_mp3} download={`debate-${debate.id}.mp3`} className="inline-flex items-center gap-1.5 rounded-[10px] bg-surface-2 px-3.5 py-2 text-[13px] font-semibold hover:bg-surface-3">
                  <Download className="size-3.5" /> Download
                </a>
              ) : (
                <span className="font-mono text-[11px] text-muted">NO AUDIO</span>
              )}
            </div>
          </div>
        </Card>
      )}
      <Lineup participants={debate.participants} judgeVoice={judgeVoice} />
    </aside>
  );
};
