import { useState } from 'react';
import { Link } from 'react-router';
import { BellRing, Send } from 'lucide-react';
import { getAlerts, sendTestAlert } from '../../api/admin/settings';
import type { AlertSeverity } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { Button, Card, ErrorBox, SectionLabel, Spinner, useToast } from '../ui';
import { formatTime } from './helpers';
import { useLoad } from './useLoad';

const DOT: Record<AlertSeverity, string> = { critical: 'bg-con', warning: 'bg-host', info: 'bg-pro' };
const loadAlerts = () => getAlerts();

/** Telegram alerts: whether they are set up, a test message and what went out lately. */
export const AlertsCard = () => {
  const toast = useToast();
  const { data, error, reload } = useLoad(loadAlerts, 30_000);
  const [sending, setSending] = useState(false);

  const test = async () => {
    setSending(true);
    try {
      const out = await sendTestAlert();
      if (out.sent) toast.success('Test alert sent');
      else toast.error(out.error ?? 'Not sent');
      reload();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionLabel>Alerts in Telegram</SectionLabel>
        <Button variant="secondary" size="sm" icon={<Send className="size-4" />} loading={sending} disabled={!data?.configured} onClick={test}>
          Send a test
        </Button>
      </div>
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!data && !error && <Spinner className="mt-6 size-5" />}
      {data && (
        <>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            {data.configured ? (
              <>
                On. Events marked “at once” go out when they happen, the others are checked every {Math.round(data.check_every_seconds / 60)} minutes; a lasting
                problem is reported once, again when it gets worse. New accounts and debates are capped at 30 an hour each.
              </>
            ) : (
              <>
                Off. Create a bot with @BotFather, send it a message, then set <code className="font-mono text-xs text-text-2">ALERT_TELEGRAM_BOT_TOKEN</code> and{' '}
                <code className="font-mono text-xs text-text-2">ALERT_TELEGRAM_CHAT_ID</code> (your user id, or a group with the bot) in the server’s .env and
                restart. Until then alerts are only listed here.
              </>
            )}
          </p>
          {data.recent.length === 0 ? (
            <p className="mt-4 flex items-center gap-2 text-sm text-text-3">
              <BellRing className="size-4 text-muted" /> No alerts yet.
            </p>
          ) : (
            <ul className="mt-3 max-h-[420px] divide-y divide-line/70 overflow-y-auto">
              {data.recent.map((alert, i) => (
                <li key={`${alert.at}-${i}`} className="grid gap-0.5 py-2.5 text-xs">
                  <div className="flex flex-wrap items-center gap-x-2">
                    <span className={`size-2 shrink-0 rounded-full ${DOT[alert.severity]}`} aria-label={alert.severity} />
                    {alert.path ? (
                      <Link to={alert.path} className="font-semibold text-text-2 hover:text-text hover:underline">
                        {alert.title}
                      </Link>
                    ) : (
                      <span className="font-semibold text-text-2">{alert.title}</span>
                    )}
                    <span className="ml-auto whitespace-nowrap text-muted">{formatTime(alert.at)}</span>
                  </div>
                  {alert.detail && <div className="pl-4 text-text-3">{alert.detail}</div>}
                  {!alert.sent && <div className="pl-4 text-dim">not sent: {alert.error ?? 'unknown reason'}</div>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
};
