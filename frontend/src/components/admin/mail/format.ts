/** Words of the Mail page (pure; a .ts file for react-refresh). */
import type { MailKind, MailLetter } from '../../../api/admin/types';

export const KIND_LABELS: Record<MailKind, string> = { verify: 'Confirmation', reset: 'Password reset', test: 'Test' };

export type MailTone = 'ok' | 'bad' | 'wait' | 'plain';

/** A letter's state in a word: what the sending service reported, else what our relay said. */
export const mailState = (letter: Pick<MailLetter, 'status' | 'delivery'>): { label: string; tone: MailTone; hint: string } => {
  if (letter.status === 'sending') return { label: 'sending', tone: 'wait', hint: 'waiting for the relay to answer' };
  if (letter.status === 'off') return { label: 'not sent', tone: 'bad', hint: 'no mail relay is set up on the server' };
  if (letter.status === 'failed') return { label: 'refused', tone: 'bad', hint: 'the relay refused the letter or could not be reached' };
  switch (letter.delivery) {
    case 'delivered':
      return { label: 'delivered', tone: 'ok', hint: 'the recipient’s mail server took it' };
    case 'delayed':
      return { label: 'delayed', tone: 'wait', hint: 'the service is still trying to deliver it' };
    case 'bounced':
      return { label: 'bounced', tone: 'bad', hint: 'the recipient’s mail server refused it' };
    case 'complained':
      return { label: 'spam', tone: 'bad', hint: 'the recipient marked it as spam' };
    case 'suppressed':
      return { label: 'suppressed', tone: 'bad', hint: 'not sent: the address bounced or complained before' };
    case 'failed':
      return { label: 'failed', tone: 'bad', hint: 'the service could not send it' };
    default:
      return { label: 'sent', tone: 'plain', hint: 'the relay took it; no report from the service yet' };
  }
};

export const TONE_CLASSES: Record<MailTone, string> = {
  ok: 'border-ok/30 bg-ok/10 text-ok',
  bad: 'border-con/30 bg-con/10 text-con',
  wait: 'border-host/30 bg-host/10 text-host',
  plain: 'border-line-2 bg-surface-2 text-text-2',
};

const EVENT_LABELS: Record<string, string> = {
  sent: 'Accepted by the service',
  delivered: 'Delivered to the recipient’s server',
  delivery_delayed: 'Delivery delayed',
  bounced: 'Bounced',
  complained: 'Marked as spam',
  suppressed: 'Suppressed',
  failed: 'Failed',
};

export const eventLabel = (type: string) => EVENT_LABELS[type] ?? type;
