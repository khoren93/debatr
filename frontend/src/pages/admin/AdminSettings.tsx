import { useState, type ReactNode } from 'react';
import { Plus, RotateCcw, Search, X } from 'lucide-react';
import { changeLever, getSettings, resetLever } from '../../api/admin/settings';
import type { AlertEvent, Lever, LeverKey, LeverValue, SettingsOut } from '../../api/admin/types';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { ActionDialog } from '../../components/admin/ActionDialog';
import { AlertEventsCard } from '../../components/admin/AlertEventsCard';
import { AlertsCard } from '../../components/admin/AlertsCard';
import { mutedSummary, mutesSecurity } from '../../components/admin/alertEvents';
import { formatTime, formatUsd } from '../../components/admin/helpers';
import { useLoad } from '../../components/admin/useLoad';
import { Button, Card, Dropdown, ErrorBox, Input, SectionLabel, Spinner, SwitchTrack, Textarea, useToast } from '../../components/ui';

const COPY: Record<LeverKey, { label: string; hint: string }> = {
  registration_open: { label: 'Sign-ups', hint: 'New accounts. Accounts that exist keep signing in.' },
  maintenance: { label: 'Maintenance mode', hint: 'No new debates, resumes or audio builds; the ones running finish. The site shows a banner.' },
  maintenance_message: { label: 'Maintenance message', hint: 'On the banner and in refused requests (the CLI shows it too). Empty: the standard text.' },
  disabled_models: {
    label: 'Turned-off models',
    hint: 'Hidden from the wizard, the CLI and MCP, refused when a debate starts or resumes; the Free Router skips them (its pick is asked again, a pinned one gives way to the router).',
  },
  signup_bonus_usd: { label: 'Signup bonus', hint: 'Credits every new account starts with.' },
  free_models_per_minute: { label: 'Free-model requests a minute', hint: 'System key, all users together; OpenRouter allows 20. Turns wait for a slot. 0: no limit.' },
  max_active_debates_per_user: { label: 'Debates at a time, per user', hint: 'Queued and running; more answer “wait”. 0: no limit.' },
  max_active_media_per_user: { label: 'Audio builds at a time, per user', hint: '0: no limit.' },
  muted_alerts: { label: 'Telegram notifications', hint: 'Events that are not sent to the chat.' },
  free_verdict_model: {
    label: 'Verdict model of free debates',
    hint: 'Structures the verdict and answers the gallery check when every participant argues on a free model, so such a debate costs nothing. Free models only; off: the paid VERDICT_MODEL. A model that stops answering sends those debates to the moderation queue.',
  },
};

const show = (lever: Lever, value: LeverValue, events: AlertEvent[] = []): string => {
  if (lever.kind === 'alerts') return mutedSummary(Array.isArray(value) ? value : [], events);
  if (lever.kind === 'bool') {
    if (lever.key === 'registration_open') return value ? 'open' : 'closed';
    return value ? 'on' : 'off';
  }
  if (lever.kind === 'models') return Array.isArray(value) && value.length ? value.join(', ') : 'none';
  if (lever.kind === 'model') return String(value) || 'off (paid model)';
  if (lever.key === 'signup_bonus_usd') return formatUsd(Number(value));
  if (lever.kind === 'text') return String(value) || '(standard text)';
  return String(value);
};

interface Pending {
  lever: Lever;
  value?: LeverValue;
  reset?: boolean;
}

const loadSettings = () => getSettings();

// Text and model lists take the row's whole width under the description.
const Row = ({ lever, onReset, children }: { lever: Lever; onReset: () => void; children: ReactNode }) => (
  <div className={`grid gap-3 py-4 first:pt-1 last:pb-1 ${lever.kind === 'text' || lever.kind === 'models' ? '' : 'md:grid-cols-[1fr_auto] md:items-center'}`}>
    <div className="min-w-0">
      <div className="text-sm font-semibold">{COPY[lever.key].label}</div>
      <p className="mt-0.5 text-xs leading-relaxed text-muted">{COPY[lever.key].hint}</p>
      <p className="mt-1 text-[11px] text-dim">
        {lever.overridden ? (
          <>
            Changed by {lever.updated_by ?? 'unknown'}
            {lever.updated_at && ` ${formatTime(lever.updated_at)}`} · .env value {show(lever, lever.default)} ·{' '}
            <button type="button" onClick={onReset} className="inline-flex cursor-pointer items-center gap-1 text-muted hover:text-text">
              <RotateCcw className="size-3" /> back to .env
            </button>
          </>
        ) : (
          'From .env'
        )}
      </p>
    </div>
    <div className={lever.kind === 'text' || lever.kind === 'models' ? '' : 'md:justify-self-end'}>{children}</div>
  </div>
);

const Toggle = ({ lever, onChange }: { lever: Lever; onChange: (value: boolean) => void }) => {
  const on = Boolean(lever.value);
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={COPY[lever.key].label} onClick={() => onChange(!on)} className="flex cursor-pointer items-center gap-2.5 text-sm">
      <span className={on ? 'text-text' : 'text-muted'}>{show(lever, on)}</span>
      <SwitchTrack on={on} />
    </button>
  );
};

const NumberField = ({ lever, onSave }: { lever: Lever; onSave: (value: number) => void }) => {
  const [draft, setDraft] = useState<string | null>(null);
  const money = lever.kind === 'float';
  const text = draft ?? String(lever.value);
  const value = Number(text);
  const valid =
    text.trim() !== '' &&
    Number.isFinite(value) &&
    (money || Number.isInteger(value)) &&
    (lever.minimum === null || value >= lever.minimum) &&
    (lever.maximum === null || value <= lever.maximum);
  const dirty = draft !== null && value !== Number(lever.value);
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid && dirty) {
          onSave(value);
          setDraft(null);
        }
      }}
    >
      <div className="relative">
        {money && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted">$</span>}
        <Input
          type="number"
          inputMode={money ? 'decimal' : 'numeric'}
          aria-label={COPY[lever.key].label}
          min={lever.minimum ?? undefined}
          max={lever.maximum ?? undefined}
          step={money ? 0.01 : 1}
          value={text}
          onChange={(e) => setDraft(e.target.value)}
          className={`w-28 tabular-nums ${money ? 'pl-7' : ''}`}
        />
      </div>
      <Button type="submit" size="sm" variant="secondary" disabled={!valid || !dirty}>
        Save
      </Button>
    </form>
  );
};

const MessageField = ({ lever, onSave }: { lever: Lever; onSave: (value: string) => void }) => {
  const [draft, setDraft] = useState<string | null>(null);
  const text = draft ?? String(lever.value);
  const dirty = draft !== null && text.trim() !== String(lever.value);
  return (
    <form
      className="grid w-full gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty) {
          onSave(text.trim());
          setDraft(null);
        }
      }}
    >
      <Textarea aria-label={COPY[lever.key].label} maxLength={300} value={text} onChange={(e) => setDraft(e.target.value)} className="min-h-[64px]" placeholder="Debatr is being updated…" />
      <Button type="submit" size="sm" variant="secondary" className="justify-self-end" disabled={!dirty}>
        Save
      </Button>
    </form>
  );
};

const ModelsField = ({ lever, catalogue, onChange }: { lever: Lever; catalogue: SettingsOut['models']; onChange: (value: string[]) => void }) => {
  const [text, setText] = useState('');
  const off = Array.isArray(lever.value) ? (lever.value as string[]) : [];
  const names = new Map(catalogue.map((m) => [m.id, m.name]));
  const needle = text.trim().toLowerCase();
  const matches = needle
    ? catalogue.filter((m) => !off.includes(m.id) && (m.id.toLowerCase().includes(needle) || m.name.toLowerCase().includes(needle))).slice(0, 8)
    : [];
  return (
    <div className="grid w-full gap-2">
      {off.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {off.map((id) => (
            <span key={id} className="inline-flex items-center gap-1.5 rounded-full border border-line-2 bg-surface-2 py-1 pl-3 pr-1.5 text-xs text-text-2" title={id}>
              {names.get(id) ?? id}
              <button type="button" onClick={() => onChange(off.filter((m) => m !== id))} aria-label={`Turn ${id} back on`} className="cursor-pointer rounded-full p-0.5 text-muted hover:text-text">
                <X className="size-3.5" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
        <Input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Find a model to turn off" aria-label="Find a model to turn off" className="pl-9" />
      </div>
      {matches.length > 0 && (
        <ul className="overflow-hidden rounded-[12px] border border-line bg-surface-2">
          {matches.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                onClick={() => {
                  setText('');
                  onChange([...off, m.id]);
                }}
                className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface-3"
              >
                <Plus className="size-3.5 text-muted" />
                <span className="font-semibold text-text-2">{m.name}</span>
                <span className="truncate font-mono text-[11px] text-muted">{m.id}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

// One free model, or none: the catalogue's `:free` models (and the current one if it left).
const FreeModelField = ({ lever, catalogue, onChange }: { lever: Lever; catalogue: SettingsOut['models']; onChange: (value: string) => void }) => {
  const current = String(lever.value);
  const free = catalogue.filter((m) => m.id.endsWith(':free'));
  const options = [
    { value: '', label: 'Off: the paid model' },
    ...(current && !free.some((m) => m.id === current) ? [{ value: current, label: current, hint: 'Not in the OpenRouter catalogue any more' }] : []),
    ...free.map((m) => ({ value: m.id, label: m.name, hint: m.id })),
  ];
  return <Dropdown value={current} options={options} onChange={onChange} aria-label={COPY[lever.key].label} className="w-full md:w-72" menuWidth={360} />;
};

const AdminSettings = () => {
  const toast = useToast();
  const { data, error } = useLoad(loadSettings);
  const [fresh, setFresh] = useState<SettingsOut | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const settings = fresh ?? data;

  const byKey = (key: LeverKey) => settings?.levers.find((l) => l.key === key);
  const ask = (lever: Lever, value: LeverValue) => setPending({ lever, value });
  const askReset = (lever: Lever) => setPending({ lever, reset: true });

  const submit = async (reason: string) => {
    if (!pending) return;
    const { lever, value, reset } = pending;
    const out = reset ? await resetLever(lever.key, reason) : await changeLever(lever.key, value as LeverValue, reason);
    setFresh(out);
    toast.success(`${COPY[lever.key].label}: saved. Every server process uses it within ${Math.ceil(out.cache_seconds)} s.`);
  };

  const row = (key: LeverKey, control: (lever: Lever) => ReactNode) => {
    const lever = byKey(key);
    return lever ? (
      <Row key={key} lever={lever} onReset={() => askReset(lever)}>
        {control(lever)}
      </Row>
    ) : null;
  };

  const number = (lever: Lever) => <NumberField key={String(lever.value)} lever={lever} onSave={(value) => ask(lever, value)} />;
  const pendingTarget = pending ? (pending.reset ? pending.lever.default : (pending.value as LeverValue)) : null;
  const events = settings?.alert_events ?? [];
  const mutedLever = byKey('muted_alerts');
  // Muting a security alert (sign-ins, locks) deserves the red button.
  const quietsSecurity = pending?.lever.key === 'muted_alerts' && Array.isArray(pendingTarget) && mutesSecurity(pendingTarget, events);

  return (
    <Page>
      <PageTitle kicker="Admin console" title="Settings" />
      <p className="mt-2 max-w-2xl text-sm text-muted">
        Levers that apply without a deploy. Each change asks for a code and a reason, goes to the audit log and reaches every server process within seconds.
        Without a change, the value from the server’s .env applies.
      </p>
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!settings && !error && <Spinner className="mt-10 size-6" />}
      {settings && (
        <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1.4fr_1fr]">
          <div className="grid gap-5">
            <Card>
              <SectionLabel>Access</SectionLabel>
              <div className="mt-2 divide-y divide-line">
                {row('registration_open', (lever) => (
                  <Toggle lever={lever} onChange={(value) => ask(lever, value)} />
                ))}
                {row('maintenance', (lever) => (
                  <Toggle lever={lever} onChange={(value) => ask(lever, value)} />
                ))}
                {row('maintenance_message', (lever) => (
                  <MessageField key={String(lever.value)} lever={lever} onSave={(value) => ask(lever, value)} />
                ))}
              </div>
            </Card>
            <Card>
              <SectionLabel>Models</SectionLabel>
              <div className="mt-2 divide-y divide-line">
                {row('disabled_models', (lever) => (
                  <ModelsField lever={lever} catalogue={settings.models} onChange={(value) => ask(lever, value)} />
                ))}
                {row('free_verdict_model', (lever) => (
                  <FreeModelField lever={lever} catalogue={settings.models} onChange={(value) => ask(lever, value)} />
                ))}
              </div>
            </Card>
            <Card>
              <SectionLabel>Money and limits</SectionLabel>
              <div className="mt-2 divide-y divide-line">
                {row('signup_bonus_usd', number)}
                {row('free_models_per_minute', number)}
                {row('max_active_debates_per_user', number)}
                {row('max_active_media_per_user', number)}
              </div>
            </Card>
          </div>
          <div className="grid gap-5">
            {mutedLever && (
              <AlertEventsCard
                key={JSON.stringify(mutedLever.value)}
                lever={mutedLever}
                events={events}
                onSave={(value) => ask(mutedLever, value)}
                onReset={() => askReset(mutedLever)}
              />
            )}
            <AlertsCard />
          </div>
        </div>
      )}

      <ActionDialog
        open={pending !== null}
        title={pending ? `${COPY[pending.lever.key].label}${pending.reset ? ': back to .env' : ''}` : ''}
        body={
          pending && (
            <>
              From <b className="text-text">{show(pending.lever, pending.lever.value, events)}</b> to{' '}
              <b className="text-text">{show(pending.lever, pendingTarget as LeverValue, events)}</b>.
            </>
          )
        }
        confirmLabel={pending?.reset ? 'Reset' : 'Apply'}
        danger={(pending?.lever.key === 'maintenance' && pending.value === true) || quietsSecurity}
        sudo
        autoFocusReason
        onSubmit={submit}
        onClose={() => setPending(null)}
      />
    </Page>
  );
};

export default AdminSettings;
