import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { HealthSection, ProvidersSection } from '../../components/admin/system/HealthSection';
import { QueuesSection } from '../../components/admin/system/QueuesSection';
import { LimitsSection, RunsSection } from '../../components/admin/system/RunsSection';

const PARTS = [
  { id: 'runs', label: 'Runs' },
  { id: 'queues', label: 'Queues' },
  { id: 'limits', label: 'Limits' },
  { id: 'providers', label: 'Providers' },
  { id: 'health', label: 'Health' },
];

/** Workers, queues, runs in flight, limits, providers and health on one page. */
const AdminSystem = () => {
  const { hash } = useLocation();
  // Links from the overview point at a part (#runs, #health): a client-side visit does not scroll.
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash]);

  return (
    <Page>
      <PageTitle kicker="Admin console" title="System" />
      <nav className="sticky top-0 z-10 -mx-1 mt-4 flex gap-1 overflow-x-auto bg-ink/85 px-1 py-2 backdrop-blur" aria-label="Parts of the page">
        {PARTS.map((part) => (
          <a key={part.id} href={`#${part.id}`} className="shrink-0 rounded-full border border-line-2 bg-surface px-3 py-1.5 text-xs font-semibold text-text-3 hover:text-text">
            {part.label}
          </a>
        ))}
      </nav>
      <RunsSection />
      <QueuesSection />
      <LimitsSection />
      <ProvidersSection />
      <HealthSection />
    </Page>
  );
};

export default AdminSystem;
