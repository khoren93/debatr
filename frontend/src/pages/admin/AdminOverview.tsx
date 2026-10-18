import { Database, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { formatTime } from '../../components/admin/helpers';
import { Card, SectionLabel } from '../../components/ui';

/** Landing page of the console. The statistics sections arrive with the next phases. */
const AdminOverview = () => {
  const { me } = useAdminAuth();
  if (!me) return null;
  const fewCodes = me.recovery_codes_left <= 3;
  return (
    <Page>
      <PageTitle kicker="Admin console" title="Overview" />
      <div className="mt-8 grid gap-4 md:grid-cols-3">
        <Card>
          <SectionLabel>Signed in</SectionLabel>
          <div className="mt-2 truncate font-semibold">{me.user.email}</div>
          <div className="mt-1 text-xs text-muted">
            Role {me.user.role} · session ends by {formatTime(me.session.ends_at)}, or after 30 minutes idle
          </div>
        </Card>
        <Card tone={fewCodes ? 'accent' : 'surface'}>
          <SectionLabel>Recovery codes</SectionLabel>
          <div className="mt-2 font-display text-2xl font-bold">{me.recovery_codes_left} left</div>
          <Link to="/admin/security" className="mt-1 inline-flex items-center gap-1.5 text-xs text-accent hover:text-accent-hover">
            <ShieldCheck className="size-3.5" /> {fewCodes ? 'Make new ones' : 'Sessions and codes'}
          </Link>
        </Card>
        {me.permissions.includes('database') && (
          <Card>
            <SectionLabel>Raw tables</SectionLabel>
            <p className="mt-2 text-sm text-muted">Every row, with edits logged to the audit trail.</p>
            <a href="/api/admin/db/" className="mt-2 inline-flex items-center gap-1.5 text-xs text-accent hover:text-accent-hover">
              <Database className="size-3.5" /> Open the database view
            </a>
          </Card>
        )}
      </div>
      <p className="mt-8 text-sm text-muted">Users, debates, money and system pages come next.</p>
    </Page>
  );
};

export default AdminOverview;
