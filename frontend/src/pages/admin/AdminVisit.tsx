import { useCallback, type ReactNode } from 'react';
import { Link, useParams } from 'react-router';
import { FileText, MousePointerClick } from 'lucide-react';
import { getVisit } from '../../api/admin/audience';
import type { VisitCard, VisitDetail, VisitEvent } from '../../api/admin/types';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { DataTable } from '../../components/admin/DataTable';
import { DeviceIcon, SourceText, VerdictBadge } from '../../components/admin/audience/VisitBits';
import { visitColumns } from '../../components/admin/audience/visitTable';
import { VERDICT_HINTS, duration, flagOf, placeText } from '../../components/admin/audience/format';
import { formatTime } from '../../components/admin/helpers';
import { useLoad } from '../../components/admin/useLoad';
import { Panel } from '../../components/admin/users/UserSections';
import { Card, ErrorBox, SectionLabel, Spinner } from '../../components/ui';

const Fact = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="min-w-0">
    <div className="text-[11px] uppercase tracking-[0.06em] text-muted">{label}</div>
    <div className="mt-0.5 break-words text-sm text-text-2">{children}</div>
  </div>
);

/** "+3:05" from the visit's start. */
const offset = (start: string, at: string) => {
  const s = Math.max(0, Math.round((new Date(at).getTime() - new Date(start).getTime()) / 1000));
  return `+${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

const propsText = (props: Record<string, unknown>) =>
  Object.entries(props)
    .filter(([, v]) => v !== null && v !== '')
    .map(([k, v]) => `${k} ${String(v)}`)
    .join(' · ');

const Timeline = ({ card }: { card: VisitCard }) => (
  <Panel title="What happened" aside={`${card.events.length} ${card.events.length === 1 ? 'event' : 'events'}`}>
    {card.events.length === 0 ? (
      <p className="px-4 py-4 text-sm text-muted">Nothing recorded.</p>
    ) : (
      <ol className="divide-y divide-line/70">
        {card.events.map((e: VisitEvent, i) => (
          <li key={`${e.at}-${i}`} className="flex items-start gap-3 px-4 py-2.5 text-xs">
            <span className="w-12 shrink-0 pt-0.5 text-right font-mono text-muted">{offset(card.visit.started_at, e.at)}</span>
            {e.kind === 'page' ? <FileText className="mt-0.5 size-3.5 shrink-0 text-muted" /> : <MousePointerClick className="mt-0.5 size-3.5 shrink-0 text-accent" />}
            <span className="min-w-0 flex-1">
              <span className={e.kind === 'action' ? 'font-semibold text-text' : 'text-text-2'}>{e.kind === 'page' ? <span className="font-mono">{e.path}</span> : e.label}</span>
              {e.debate_title && (
                <Link to={`/admin/debates/${e.debate_id}`} className="ml-2 text-muted hover:text-text">
                  {e.debate_title}
                </Link>
              )}
              {e.kind === 'action' && <span className="ml-2 font-mono text-[11px] text-dim">{[e.path, propsText(e.props)].filter(Boolean).join(' · ')}</span>}
            </span>
            {e.kind === 'page' && <span className="shrink-0 text-muted">{duration(e.engaged_ms)}</span>}
          </li>
        ))}
      </ol>
    )}
  </Panel>
);

/** The page's input counts (lib/presence.ts Signals) in words. */
const COUNTS: [string, string][] = [
  ['mv', 'mouse moves'],
  ['jmp', 'pointer jumps'],
  ['ck', 'clicks'],
  ['ckb', 'clicks with no path'],
  ['cc', 'centred presses'],
  ['tp', 'touches'],
  ['ky', 'keys'],
  ['kf', 'too-fast keys'],
  ['fill', 'texts without keys'],
  ['wh', 'wheel scrolls'],
  ['hid', 'tab switches'],
  ['syn', 'script events'],
];
const GRAPHICS: Record<string, string> = { hw: 'GPU', soft: 'software (no GPU)', none: 'no WebGL' };

/** Why the visit got its verdict: the reasons with their points, the network, what was counted. */
const VerdictPanel = ({ visit }: { visit: VisitDetail }) => {
  const counts = visit.signals.c ?? {};
  const env = visit.signals.env ?? {};
  const counted = COUNTS.filter(([key]) => counts[key]);
  const facts = [
    env.gl !== undefined && `graphics: ${GRAPHICS[String(env.gl)] ?? String(env.gl)}`,
    env.plat && `platform: ${String(env.plat)}`,
    env.pl !== undefined && `${String(env.pl)} plugins`,
    env.ln !== undefined && `${String(env.ln)} languages`,
  ].filter(Boolean);
  return (
    <Panel title="Person or bot?" aside={<VerdictBadge verdict={visit.verdict} score={visit.bot_score} />}>
      <p className="px-4 pt-3 text-xs text-muted">
        {VERDICT_HINTS[visit.verdict]}. Score {visit.bot_score > 0 ? '+' : ''}
        {visit.bot_score}: automation points minus person points.
      </p>
      {visit.reasons.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted">No signal either way.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line/70">
          {visit.reasons.map((r) => (
            <li key={r.code} className="flex items-start gap-3 px-4 py-2 text-xs">
              <span className={`w-9 shrink-0 text-right font-mono font-semibold ${r.points > 0 ? 'text-danger' : 'text-ok'}`}>
                {r.points > 0 ? '+' : '−'}
                {Math.abs(r.points)}
              </span>
              <span className="min-w-0 flex-1 text-text-2">
                {r.label}
                {r.detail && <span className="ml-1.5 text-muted">· {r.detail}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-1 border-t border-line px-4 py-3 text-xs text-muted">
        <div>
          Network: <span className="text-text-3">{visit.network ?? 'unknown'}</span>
          {visit.network_kind && <span> · {visit.network_kind === 'hosting' ? 'data centre' : 'relay / VPN'}</span>}
        </div>
        <div>Input: {counted.length ? counted.map(([key, label]) => `${counts[key]} ${label}`).join(' · ') : 'none counted'}</div>
        {facts.length > 0 && <div>Browser: {facts.join(' · ')}</div>}
      </div>
    </Panel>
  );
};

/** One visit (`/admin/audience/visits/:id`): who, from where, every page and action, whether a
 *  person or a bot made it, the visitor's other visits and the accounts seen on the same address. */
const AdminVisit = () => {
  const { id = '' } = useParams();
  const load = useCallback(() => getVisit(id), [id]);
  const { data: card, error } = useLoad(load);
  const v = card?.visit;

  return (
    <Page>
      <PageTitle
        kicker="Visit"
        title={v ? (v.user ? v.user.email : 'Anonymous visitor') : 'Visit'}
        right={
          <Link to="/admin/audience/visits" className="text-sm text-accent hover:text-accent-hover">
            ← Visits
          </Link>
        }
      />
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!card && !error && <Spinner className="mt-10 size-6" />}
      {card && v && (
        <>
          <Card className="mt-4">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Fact label="When">
                {formatTime(v.started_at)} · {duration(v.engaged_ms)} on the site
              </Fact>
              <Fact label="Where">
                {flagOf(v.country)} {placeText(v)}
              </Fact>
              <Fact label="IP">{v.ip ? <span className="font-mono">{v.ip}</span> : <span className="text-muted">cleared</span>}</Fact>
              <Fact label="Came from">
                <SourceText source={v.source} host={v.referrer_host} />
              </Fact>
              <Fact label="Person or bot">
                <VerdictBadge verdict={v.verdict} score={v.bot_score} />
              </Fact>
              <Fact label="Account">
                {v.user ? (
                  <Link to={`/admin/users/${v.user.id}`} className="text-accent hover:text-accent-hover">
                    {v.user.display_name} · {v.user.email}
                  </Link>
                ) : (
                  'Not signed in'
                )}
                {v.staff && <span className="ml-2 text-muted">(staff)</span>}
              </Fact>
              <Fact label="Pages · actions">
                {v.pageviews} · {v.actions}
              </Fact>
              <Fact label="Device">
                <span className="inline-flex items-center gap-1.5">
                  <DeviceIcon device={v.device} /> {[v.browser, v.os].filter(Boolean).join(' · ') || v.device}
                  {v.screen && <span className="text-muted">· {v.screen}</span>}
                </span>
              </Fact>
              <Fact label="Language · time zone">{[v.language, v.timezone].filter(Boolean).join(' · ') || '—'}</Fact>
              <Fact label="Landing → exit">
                <span className="font-mono text-xs">
                  {v.landing} → {v.exit_path}
                </span>
              </Fact>
              <Fact label="Referrer">{v.referrer ? <span className="font-mono text-xs">{v.referrer}</span> : '—'}</Fact>
              <Fact label="Campaign">{[v.utm_source, v.utm_medium, v.utm_campaign].filter(Boolean).join(' / ') || (v.ref ? `ref ${v.ref}` : '—')}</Fact>
              <Fact label="Visitor">
                <span className="font-mono text-xs">{card.visitor.visitor_id}</span>
                <div className="text-xs text-muted">
                  {card.visitor.visits} {card.visitor.visits === 1 ? 'visit' : 'visits'} since {formatTime(card.visitor.first_seen)} · {duration(card.visitor.engaged_ms)} in all
                </div>
              </Fact>
            </div>
            {v.user_agent && <div className="mt-4 border-t border-line pt-3 font-mono text-[11px] text-dim">{v.user_agent}</div>}
          </Card>

          <div className="mt-4 grid items-start gap-4 xl:grid-cols-[3fr_2fr]">
            <Timeline card={card} />
            <div className="grid gap-4">
              <VerdictPanel visit={v} />
              <Panel title="Accounts of this browser">
                {card.visitor.accounts.length === 0 ? (
                  <p className="px-4 py-4 text-sm text-muted">Never signed in.</p>
                ) : (
                  <ul className="divide-y divide-line/70">
                    {card.visitor.accounts.map((u) => (
                      <li key={u.id} className="px-4 py-2.5 text-sm">
                        <Link to={`/admin/users/${u.id}`} className="text-text-2 hover:text-text">
                          {u.display_name} <span className="text-muted">{u.email}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
              <Panel title="Accounts on this IP" aside={v.ip ?? 'IP cleared'}>
                {card.same_ip.length === 0 ? (
                  <p className="px-4 py-4 text-sm text-muted">{v.ip ? 'No account was seen on it.' : 'The address is no longer kept.'}</p>
                ) : (
                  <ul className="divide-y divide-line/70">
                    {card.same_ip.map((s) => (
                      <li key={s.user.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-xs">
                        <Link to={`/admin/users/${s.user.id}`} className="min-w-0 truncate text-text-2 hover:text-text">
                          {s.user.email}
                        </Link>
                        <span className="shrink-0 text-muted">
                          {s.visits} {s.visits === 1 ? 'visit' : 'visits'} · last {formatTime(s.last_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
          </div>

          <section className="mt-8">
            <SectionLabel>Other visits of this browser</SectionLabel>
            <Card padding="none" className="mt-3 overflow-hidden">
              {card.visitor_visits.length === 0 ? (
                <p className="px-4 py-4 text-sm text-muted">This is its only visit.</p>
              ) : (
                <DataTable caption="Other visits" columns={visitColumns()} rows={card.visitor_visits} rowKey={(r) => r.id} rowHref={(r) => `/admin/audience/visits/${r.id}`} />
              )}
            </Card>
          </section>
        </>
      )}
    </Page>
  );
};

export default AdminVisit;
