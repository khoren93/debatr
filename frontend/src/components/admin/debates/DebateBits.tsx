import { AudioLines, KeyRound, Terminal } from 'lucide-react';
import type { AdminDebateRow } from '../../../api/admin/types';
import type { DebateStatus } from '../../../api/types';
import { STATUS_COLORS, STATUS_LABELS } from '../../../lib/format';

/** "Completed", "Error"… in the status colour. */
export const DebateStatusText = ({ status }: { status: string }) => (
  <span style={{ color: STATUS_COLORS[status as DebateStatus] }}>{STATUS_LABELS[status as DebateStatus] ?? status}</span>
);

const MODERATION: Record<string, { label: string; tone: string }> = {
  flagged: { label: 'flagged', tone: 'text-host' },
  rejected: { label: 'rejected', tone: 'text-con' },
  approved: { label: 'approved', tone: 'text-text-3' },
  none: { label: 'not checked', tone: 'text-dim' },
};

export const ModerationText = ({ status }: { status: string }) => {
  const look = MODERATION[status] ?? { label: status, tone: 'text-muted' };
  return <span className={look.tone}>{look.label}</span>;
};

const AUDIO_TONES: Record<string, string> = { ready: 'text-text-3', error: 'text-con', running: 'text-host', queued: 'text-host' };

/** Own key, API token and audio marks of a debate row. */
export const DebateFlags = ({ debate }: { debate: Pick<AdminDebateRow, 'own_key' | 'via_token' | 'media_status'> }) => (
  <span className="flex items-center justify-end gap-2 text-muted">
    {debate.own_key && <KeyRound className="size-3.5" aria-label="Owner's OpenRouter key" />}
    {debate.via_token && <Terminal className="size-3.5" aria-label="Started with an API token" />}
    {debate.media_status !== 'none' && (
      <span title={`Audio ${debate.media_status}`} className={AUDIO_TONES[debate.media_status] ?? ''}>
        <AudioLines className="size-3.5" aria-label={`Audio ${debate.media_status}`} />
      </span>
    )}
  </span>
);
