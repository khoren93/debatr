import { useState } from 'react';
import { RotateCcw } from 'lucide-react';
import type { AlertEvent, Lever } from '../../api/admin/types';
import { Button, Card, SectionLabel, SwitchTrack } from '../ui';
import { ALERT_GROUPS, mutedSummary } from './alertEvents';
import { formatTime } from './helpers';

interface Props {
  /** The `muted_alerts` lever. */
  lever: Lever;
  events: AlertEvent[];
  onSave: (muted: string[]) => void;
  onReset: () => void;
}

/** Which events go to Telegram: a switch per event, saved together (code + reason, audited).
 * The parent keys it by the saved value, so a save starts a fresh draft. */
export const AlertEventsCard = ({ lever, events, onSave, onReset }: Props) => {
  const saved = Array.isArray(lever.value) ? (lever.value as string[]) : [];
  const [draft, setDraft] = useState<string[] | null>(null);
  const muted = draft ?? saved;
  const dirty = draft !== null && (draft.length !== saved.length || draft.some((kind) => !saved.includes(kind)));
  const on = events.filter((e) => !muted.includes(e.kind)).length;

  const toggle = (kind: string) => {
    const next = muted.includes(kind) ? muted.filter((k) => k !== kind) : [...muted, kind];
    setDraft(events.map((e) => e.kind).filter((k) => next.includes(k))); // the catalogue's order
  };

  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <SectionLabel>Telegram notifications</SectionLabel>
        <span className="text-xs tabular-nums text-muted">
          {on} of {events.length} on
        </span>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        Pick the events that go to the chat. Muted ones are neither sent nor listed under the recent alerts; a test message and changes to this list always go
        out.
      </p>
      <div className="mt-3 grid gap-4">
        {ALERT_GROUPS.map(({ group, label }) => {
          const items = events.filter((e) => e.group === group);
          if (!items.length) return null;
          return (
            <section key={group}>
              <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-dim">{label}</div>
              <ul className="mt-1 divide-y divide-line/70">
                {items.map((event) => {
                  const sends = !muted.includes(event.kind);
                  return (
                    <li key={event.kind}>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={sends}
                        aria-label={event.label}
                        onClick={() => toggle(event.kind)}
                        className="flex w-full cursor-pointer items-start gap-4 py-2.5 text-left"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-baseline gap-x-2">
                            <span className={`text-sm font-semibold ${sends ? 'text-text-2' : 'text-muted'}`}>{event.label}</span>
                            <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-dim">{event.at_once ? 'at once' : 'periodic check'}</span>
                          </span>
                          <span className="mt-0.5 block text-xs leading-relaxed text-muted">{event.hint}</span>
                        </span>
                        <SwitchTrack on={sends} size="sm" className="mt-0.5" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
        <p className="text-[11px] text-dim">
          {lever.overridden ? (
            <>
              Changed by {lever.updated_by ?? 'unknown'}
              {lever.updated_at && ` ${formatTime(lever.updated_at)}`} ·{' '}
              <button type="button" onClick={onReset} className="inline-flex cursor-pointer items-center gap-1 text-muted hover:text-text">
                <RotateCcw className="size-3" /> everything on
              </button>
            </>
          ) : (
            'Everything on (the default)'
          )}
        </p>
        {dirty && (
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDraft(null)}>
              Undo
            </Button>
            <Button size="sm" onClick={() => onSave(muted)} title={mutedSummary(muted, events)}>
              Save changes
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
};
