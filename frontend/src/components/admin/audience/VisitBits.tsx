import { Monitor, Smartphone, Tablet } from 'lucide-react';
import type { VisitRow, VisitVerdict } from '../../../api/admin/types';
import { Pill } from '../../ui';
import { SOURCE_COLORS } from '../charts/palette';
import { VERDICT_COLORS, VERDICT_HINTS, VERDICT_LABELS, flagOf, placeText, sourceLabel } from './format';

export const DeviceIcon = ({ device }: { device: string }) => {
  const Icon = device === 'mobile' ? Smartphone : device === 'tablet' ? Tablet : Monitor;
  return <Icon className="size-3.5 shrink-0 text-muted" aria-label={device} />;
};

export const SourceText = ({ source, host, campaign }: { source: string; host?: string | null; campaign?: string | null }) => (
  <span className="flex min-w-0 flex-col">
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span aria-hidden className="size-2 shrink-0 rounded-[3px]" style={{ background: (SOURCE_COLORS as Record<string, string>)[source] ?? '#8b90a0' }} />
      {sourceLabel(source)}
    </span>
    {(host || campaign) && <span className="max-w-[180px] truncate text-[11px] text-muted">{[host, campaign && `“${campaign}”`].filter(Boolean).join(' · ')}</span>}
  </span>
);

export const PlaceText = ({ visit }: { visit: Pick<VisitRow, 'country' | 'region' | 'city' | 'ip'> }) => (
  <span className="flex min-w-0 flex-col">
    <span className="max-w-[220px] truncate" title={placeText(visit)}>
      {flagOf(visit.country)} {placeText(visit)}
    </span>
    {visit.ip && <span className="font-mono text-[11px] text-muted">{visit.ip}</span>}
  </span>
);

/** Person, bot or AI agent (backend audience/bots.py); `score`: automation minus person points. */
export const VerdictBadge = ({ verdict, score, className = '' }: { verdict: VisitVerdict; score?: number; className?: string }) => (
  <span title={`${VERDICT_HINTS[verdict]}${score === undefined ? '' : ` · score ${score > 0 ? '+' : ''}${score}`}`} className={className}>
    <Pill color={VERDICT_COLORS[verdict]} pulse={verdict === 'agent'} className="whitespace-nowrap">
      {VERDICT_LABELS[verdict]}
    </Pill>
  </span>
);
