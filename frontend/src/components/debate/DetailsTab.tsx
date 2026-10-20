import type { Timeline } from '../../api/timeline';
import type { DebateDetail } from '../../api/types';
import { useHydrated } from '../../hooks/useHydrated';
import { formatCost, formatCount, formatDateTime, formatTokens, shortModelName } from '../../lib/format';
import type { SpeakerInfo } from './helpers';
import { SpeakerTile } from './SpeakerTile';

interface Props {
  debate: DebateDetail;
  lineup: SpeakerInfo[];
  timeline: Timeline | null;
}

const LENGTHS: Record<string, string> = { very_short: 'short replies', short: 'medium replies', medium: 'long replies', long: 'very long replies' };
const PROVIDERS: Record<string, string> = { elevenlabs: 'ElevenLabs', edge: 'Edge neural voices' };

/** Details tab: who spoke with which model and voice, and the run's facts. */
export const DetailsTab = ({ debate, lineup, timeline }: Props) => {
  const { settings, totals } = debate;
  // The viewer's local time once hydrated; the server renders UTC.
  const hydrated = useHydrated();
  const provider = timeline?.provider ?? (debate.media_status !== 'none' ? debate.media_plan?.provider : undefined);
  const facts: { k: string; v: string }[] = [
    { k: 'TOKENS', v: `${formatTokens(totals.tokens_in)} in · ${formatTokens(totals.tokens_out)} out` },
    ...(debate.is_owner ? [{ k: 'MODEL COST', v: `${formatCost(totals.cost)}${debate.billing.own_key ? ' · own key' : ''}` }] : []),
    { k: 'CREATED', v: hydrated ? formatDateTime(debate.created_at) : `${formatDateTime(debate.created_at, 'UTC')} UTC` },
    { k: 'STYLE', v: `${settings.output_style === 'spoken' ? 'Spoken' : 'Markdown'} · ${LENGTHS[settings.length_preset] ?? settings.length_preset}` },
    { k: 'FORMAT', v: `${settings.num_rounds} ${settings.num_rounds === 1 ? 'round' : 'rounds'} · ${settings.language}` },
    ...(provider ? [{ k: 'VOICES', v: PROVIDERS[provider] ?? provider }] : []),
    ...(debate.is_public ? [{ k: 'VIEWS', v: formatCount(debate.views) }] : []),
    ...(debate.author_name && !debate.is_owner ? [{ k: 'AUTHOR', v: debate.author_name }] : []),
  ];
  return (
    <div className="mt-[18px] grid gap-3.5">
      <div className="overflow-hidden rounded-card border border-white/6 bg-surface">
        {lineup.map((s) => (
          <div key={s.id} className="grid grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 border-b border-white/5 px-4 py-3.5 last:border-b-0">
            <SpeakerTile model={s.model} color={s.color} size={36} />
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-sm font-bold">
                <span className="truncate">{s.name}</span>
                <span className="font-mono text-[10px] tracking-[0.06em]" style={{ color: s.color }}>
                  {s.tag}
                </span>
              </div>
              <div className="mt-0.5 truncate text-xs text-muted">{[s.model ? shortModelName(s.model) : null, s.voice].filter(Boolean).join(' · ') || '—'}</div>
            </div>
            <div className="font-mono text-[11px] text-muted">{s.tokens > 0 ? `${formatTokens(s.tokens)} tok` : ''}</div>
          </div>
        ))}
      </div>
      <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr))]">
        {facts.map((f) => (
          <div key={f.k} className="rounded-[14px] border border-white/6 bg-surface px-4 py-3.5">
            <div className="font-mono text-[10px] tracking-[0.08em] text-muted">{f.k}</div>
            <div className="mt-1.5 text-sm font-semibold">{f.v}</div>
          </div>
        ))}
      </div>
    </div>
  );
};
