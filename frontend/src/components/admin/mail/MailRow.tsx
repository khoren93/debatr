import { useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { MailLetter } from '../../../api/admin/types';
import { formatTime } from '../helpers';
import { KIND_LABELS, TONE_CLASSES, eventLabel, mailState } from './format';

/** The letter's state as a pill (its meaning on hover). */
export const MailBadge = ({ letter }: { letter: Pick<MailLetter, 'status' | 'delivery'> }) => {
  const state = mailState(letter);
  return (
    <span title={state.hint} className={`shrink-0 rounded-full border px-1.5 py-px font-mono text-[10px] font-semibold uppercase tracking-[0.06em] ${TONE_CLASSES[state.tone]}`}>
      {state.label}
    </span>
  );
};

const Detail = ({ label, mono = true, children }: { label: string; mono?: boolean; children: ReactNode }) => (
  <div className="grid gap-0.5 sm:grid-cols-[150px_1fr] sm:gap-3">
    <div className="text-muted">{label}</div>
    <div className={`min-w-0 text-text-2 ${mono ? 'break-all font-mono' : ''}`}>{children}</div>
  </div>
);

const took = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

/** One letter: state, subject, address and time; unfolds to the relay's answer and the service's
 *  events. `account` links the address to the account's card. */
export const MailRow = ({ letter, account = true }: { letter: MailLetter; account?: boolean }) => {
  const [open, setOpen] = useState(false);
  const Icon = open ? ChevronDown : ChevronRight;
  const state = mailState(letter);
  return (
    <li className="px-4 py-2.5 text-xs">
      <div className="flex items-start gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label={open ? 'Hide details' : 'Show details'} className="mt-0.5 cursor-pointer rounded p-0.5 text-muted hover:text-text">
          <Icon className="size-3.5" />
        </button>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <MailBadge letter={letter} />
            <span className="font-semibold text-text-2">{letter.subject}</span>
            <span className="text-muted">{KIND_LABELS[letter.kind] ?? letter.kind}</span>
            <span className="ml-auto whitespace-nowrap text-muted" title={new Date(letter.created_at).toLocaleString()}>
              {formatTime(letter.created_at)}
            </span>
          </div>
          <div className="text-muted">
            to{' '}
            {account && letter.user_id ? (
              <Link to={`/admin/users/${letter.user_id}`} className="text-text-3 hover:text-text hover:underline">
                {letter.to_address}
              </Link>
            ) : (
              <span className="text-text-3">{letter.to_address}</span>
            )}
            {letter.duration_ms !== null && ` · ${took(letter.duration_ms)}`}
          </div>
          {letter.error && <div className="break-words text-con">{letter.error}</div>}
          {open && (
            <div className="mt-2 grid gap-1.5 rounded-[10px] border border-line bg-ink-2 p-3">
              <Detail label="State" mono={false}>
                {state.hint}
              </Detail>
              {letter.reply && <Detail label="Relay answered">{letter.reply}</Detail>}
              {letter.provider_id && <Detail label="Id at the service">{letter.provider_id}</Detail>}
              {letter.message_id && <Detail label="Message-ID">{letter.message_id}</Detail>}
              <Detail label="Letter">{letter.id}</Detail>
              {letter.events.length > 0 && (
                <div className="mt-1 grid gap-1 border-t border-line pt-2">
                  <div className="text-muted">Reported by the service</div>
                  <ul className="grid gap-1">
                    {letter.events.map((event, i) => (
                      <li key={`${event.type}-${event.at}-${i}`} className="grid gap-0.5 sm:grid-cols-[150px_1fr] sm:gap-3">
                        <span className="text-muted">{formatTime(event.at)}</span>
                        <span className="text-text-2">
                          {eventLabel(event.type)}
                          {event.note && <span className="text-text-3"> · {event.note}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
};
