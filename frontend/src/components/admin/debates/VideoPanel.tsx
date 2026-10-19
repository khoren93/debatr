import type { PlayerRef } from '@remotion/player';
import { useEffect, useRef, useState } from 'react';
import { debateFilesBase, getDebateTimeline } from '../../../api/admin/debates';
import { getErrorMessage } from '../../../api/client';
import type { Timeline } from '../../../api/timeline';
import { DebatePlayer } from '../../debate/DebatePlayer';
import { ErrorBox, Segmented, Spinner } from '../../ui';
import { Panel } from '../users/UserSections';

/** The long video, or the Short of one highlight. */
type View = 'long' | `short-${number}`;

const viewOptions = (timeline: Timeline): { value: View; label: string }[] => {
  const moments = timeline.highlights ?? [];
  const shorts: { value: View; label: string }[] =
    moments.length <= 1 ? [{ value: 'short-0', label: '9:16' }] : moments.map((_, i) => ({ value: `short-${i}`, label: `9:16 · ${i + 1}` }));
  return [{ value: 'long', label: '16:9' }, ...shorts];
};

/** The debate's video with the public page's player, its files read through the console.
 *  Loaded lazily: Remotion stays out of the console until a card has audio. */
const VideoPanel = ({ debateId, builtAt }: { debateId: string; builtAt: string | null }) => {
  const playerRef = useRef<PlayerRef | null>(null);
  const [result, setResult] = useState<{ key: string; timeline: Timeline } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>('long');
  const key = `${debateId}:${builtAt ?? ''}`;

  useEffect(() => {
    let cancelled = false;
    getDebateTimeline(debateId)
      .then((timeline) => {
        if (!cancelled) {
          setResult({ key: `${debateId}:${builtAt ?? ''}`, timeline });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [debateId, builtAt]);

  const timeline = result?.key === key ? result.timeline : null;
  const options = timeline ? viewOptions(timeline) : [];
  const current = options.some((o) => o.value === view) ? view : 'long';

  return (
    <Panel title="Video" aside={timeline && <Segmented options={options} value={current} onChange={setView} size="sm" />}>
      <div className="p-3">
        {error && <ErrorBox>{error}</ErrorBox>}
        {!timeline && !error && <Spinner className="mx-auto my-10 size-6" />}
        {timeline && (
          <DebatePlayer
            timeline={timeline}
            mediaBase={debateFilesBase(debateId)}
            format={current === 'long' ? 'long' : 'short'}
            highlightIndex={current === 'long' ? 0 : Number(current.slice('short-'.length))}
            startSeq={null}
            playerRef={playerRef}
          />
        )}
      </div>
    </Panel>
  );
};

export default VideoPanel;
