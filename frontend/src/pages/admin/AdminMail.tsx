import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { Send } from 'lucide-react';
import { getMailStatus, listMail, sendTestMail } from '../../api/admin/mail';
import type { MailKind, MailLetter, MailPage, MailQuery, MailStatusFilter, MailStatusSummary } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { Pager } from '../../components/admin/DataTable';
import { FilterBar, FilterChip } from '../../components/admin/FilterBar';
import { pageOf, pickKey, withChanges, type FilterSpec } from '../../components/admin/filters';
import { TONE_CLASSES } from '../../components/admin/mail/format';
import { MailBadge, MailRow } from '../../components/admin/mail/MailRow';
import { StatTile } from '../../components/admin/StatTile';
import { useLoad } from '../../components/admin/useLoad';
import { Button, Card, ErrorBox, Input, Label, Modal, SectionLabel, Spinner, useToast } from '../../components/ui';
import { formatCount } from '../../lib/format';

const PAGE = 50;

const FILTERS: FilterSpec[] = [
  {
    key: 'status',
    label: 'State',
    options: [
      { value: '', label: 'Any state' },
      { value: 'problems', label: 'Not sent or not delivered' },
      { value: 'sent', label: 'Sent' },
      { value: 'waiting', label: 'Sent, no report yet' },
      { value: 'delivered', label: 'Delivered' },
      { value: 'delayed', label: 'Delayed' },
      { value: 'bounced', label: 'Bounced' },
      { value: 'complained', label: 'Marked as spam' },
      { value: 'suppressed', label: 'Suppressed' },
      { value: 'failed', label: 'Refused or failed' },
      { value: 'off', label: 'Not sent: no relay' },
      { value: 'sending', label: 'Sending' },
    ],
  },
  {
    key: 'kind',
    label: 'Letter',
    options: [
      { value: '', label: 'Any letter' },
      { value: 'verify', label: 'Confirmation' },
      { value: 'reset', label: 'Password reset' },
      { value: 'test', label: 'Test' },
    ],
  },
  {
    key: 'days',
    label: 'Period',
    options: [
      { value: '', label: 'Any time' },
      { value: '1', label: 'Last 24 hours' },
      { value: '7', label: 'Last 7 days' },
      { value: '30', label: 'Last 30 days' },
    ],
  },
];

/** The API query of the page's URL (`user` comes from an account card's link). */
const toQuery = (params: URLSearchParams): MailQuery => {
  const days = pickKey(params, FILTERS, 'days');
  return {
    q: params.get('q')?.trim() || undefined,
    status: (pickKey(params, FILTERS, 'status') || undefined) as MailStatusFilter | undefined,
    kind: (pickKey(params, FILTERS, 'kind') || undefined) as MailKind | undefined,
    user_id: params.get('user') || undefined,
    days: days ? Number(days) : undefined,
    limit: PAGE,
    offset: pageOf(params) * PAGE,
  };
};

const loadStatus = () => getMailStatus();

const Setting = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="min-w-0">
    <div className="text-[11px] text-muted">{label}</div>
    <div className="truncate text-[13px] text-text-2">{children}</div>
  </div>
);

const Env = ({ children }: { children: ReactNode }) => <code className="font-mono text-xs text-text-2">{children}</code>;

/** How the server sends mail, and where the delivery reports come from. */
const RelayCard = ({ status }: { status: MailStatusSummary }) => {
  const relay = status.relay;
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <SectionLabel>Mail relay</SectionLabel>
        <span className={`shrink-0 rounded-full border px-1.5 py-px font-mono text-[10px] font-semibold uppercase tracking-[0.06em] ${TONE_CLASSES[relay.configured ? 'ok' : 'bad']}`}>
          {relay.configured ? 'on' : 'off'}
        </span>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        {relay.configured ? (
          <>Letters go out through the relay below as soon as they are asked for. “Sent” means the relay took the letter, not that it reached the inbox.</>
        ) : (
          <>
            Off: no letter leaves the server. Set <Env>MAIL_SMTP_HOST</Env>, <Env>MAIL_SMTP_PASSWORD</Env> and <Env>MAIL_FROM</Env> in the server’s .env, then recreate the api
            container (a restart keeps the old values).
          </>
        )}
      </p>
      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-4 sm:grid-cols-3 lg:grid-cols-5">
        <Setting label="Relay">{relay.host ? `${relay.host}:${relay.port}` : 'not set'}</Setting>
        <Setting label="Login">{relay.user || 'not set'}</Setting>
        <Setting label="From">{relay.from_address || 'not set'}</Setting>
        <Setting label="Replies to">{relay.reply_to || 'not set'}</Setting>
        <Setting label="Kept for">{relay.log_days > 0 ? `${relay.log_days} days` : 'ever'}</Setting>
      </div>
      <div className="mt-4 border-t border-line pt-4 text-sm leading-relaxed text-muted">
        {relay.webhook ? (
          <>Delivery reports are on: the sending service tells whether each letter was delivered, bounced or marked as spam.</>
        ) : (
          <>
            Delivery reports are off, so this page only knows what the relay answered. In Resend → Webhooks add <Env>{relay.webhook_url}</Env> with the <Env>email.*</Env>{' '}
            events and put its signing secret in <Env>MAIL_WEBHOOK_SECRET</Env>.
          </>
        )}
      </div>
    </Card>
  );
};

/** A test letter to any address, sent at once; the answer shows what the relay said. */
const TestDialog = ({ open, onClose, onSent }: { open: boolean; onClose: () => void; onSent: () => void }) => {
  const { me } = useAdminAuth();
  const toast = useToast();
  const [to, setTo] = useState(me?.user.email ?? '');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<MailLetter | null>(null);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const letter = await sendTestMail(to.trim());
      setResult(letter);
      if (letter.status === 'sent') toast.success('The relay took the letter');
      else toast.error(letter.error ?? 'Not sent');
      onSent();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Send a test letter"
      width="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button type="submit" form="mail-test" icon={<Send className="size-4" />} loading={busy} disabled={!to.trim()}>
            Send
          </Button>
        </>
      }
    >
      <form id="mail-test" onSubmit={send} className="grid gap-2">
        <Label>Address</Label>
        <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} autoComplete="off" required />
        <p className="text-xs leading-relaxed text-muted">Goes out now through the same relay as the site’s letters and lands in the list below.</p>
      </form>
      {result && (
        <div className="mt-4 grid gap-1 rounded-[10px] border border-line bg-ink-2 p-3 text-xs">
          <div className="flex items-center gap-2">
            <MailBadge letter={result} />
            <span className="text-text-3">to {result.to_address}</span>
          </div>
          {result.reply && <div className="break-all font-mono text-text-2">{result.reply}</div>}
          {result.error && <div className="break-words text-con">{result.error}</div>}
        </div>
      )}
    </Modal>
  );
};

const AdminMail = () => {
  const { me } = useAdminAuth();
  const [params, setParams] = useSearchParams();
  const [result, setResult] = useState<{ key: string; data: MailPage } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [version, setVersion] = useState(0);
  const status = useLoad(loadStatus, 60_000);
  const key = `${params.toString()}#${version}`;
  const query = toQuery(params);

  useEffect(() => {
    let cancelled = false;
    listMail(toQuery(new URLSearchParams(key.split('#')[0])))
      .then((data) => {
        if (!cancelled) {
          setResult({ key, data });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [key]);

  const update = (changes: Record<string, string>) => setParams(withChanges(params, changes), { replace: true, preventScrollReset: true });
  const refresh = () => {
    setVersion((n) => n + 1);
    status.reload();
  };
  const data = result?.data;
  const loading = result?.key !== key;
  const week = status.data?.last_7_days;
  const reports = status.data?.relay.webhook;
  const canTest = me?.permissions.includes('system') ?? false;

  return (
    <Page>
      <PageTitle
        kicker="Admin console"
        title="Mail"
        right={
          canTest && (
            <Button variant="secondary" size="sm" icon={<Send className="size-4" />} onClick={() => setTesting(true)}>
              Send a test letter
            </Button>
          )
        }
      />
      <p className="mt-2 max-w-2xl text-sm text-muted">
        Every letter the site sent or tried to send: confirmations and password resets, newest first. Only the address, subject and outcome are kept, never the text (it carries
        one-time links).
      </p>

      {status.error && <ErrorBox className="mt-6">{status.error}</ErrorBox>}
      {status.data && (
        <div className="mt-6 grid gap-4">
          <RelayCard status={status.data} />
          {week && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <StatTile label="Letters" value={formatCount(week.letters)} hint="last 7 days" />
              <StatTile label="Sent" value={formatCount(week.sent)} hint="the relay took them" />
              <StatTile label="Not sent" value={formatCount(week.not_sent)} hint="refused, or no relay" />
              <StatTile label="Delivered" value={reports ? formatCount(week.delivered) : '—'} hint={reports ? 'reported by the service' : 'needs delivery reports'} />
              <StatTile label="Bounced or spam" value={reports ? formatCount(week.problems) : '—'} hint={reports ? 'bounced, spam, suppressed' : 'needs delivery reports'} />
            </div>
          )}
        </div>
      )}

      <div className="mt-8">
        <FilterBar
          params={params}
          filters={FILTERS}
          searchLabel="Search letters"
          searchPlaceholder="Address, subject or letter id"
          onChange={update}
          onReset={() => setParams(new URLSearchParams(), { replace: true, preventScrollReset: true })}
        />
      </div>
      {query.user_id && (
        <div className="mt-3 flex flex-wrap gap-2">
          <FilterChip label={`Account ${query.user_id.slice(0, 8)}`} onClear={() => update({ user: '' })} />
        </div>
      )}
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      <Card padding="none" className="mt-4 overflow-hidden">
        {!data && !error ? (
          <div className="flex justify-center py-10">
            <Spinner className="size-6" />
          </div>
        ) : (
          data && (
            <>
              {data.rows.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm text-muted">No letter matches.</p>
              ) : (
                <ul className={`divide-y divide-line/70 transition-opacity ${loading ? 'opacity-60' : ''}`}>
                  {data.rows.map((letter) => (
                    <MailRow key={letter.id} letter={letter} />
                  ))}
                </ul>
              )}
              <Pager offset={data.offset} limit={data.limit} total={data.total} disabled={loading} onChange={(offset) => update({ page: String(offset / PAGE) })} />
            </>
          )
        )}
      </Card>
      {testing && <TestDialog open onClose={() => setTesting(false)} onSent={refresh} />}
    </Page>
  );
};

export default AdminMail;
