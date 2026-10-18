import { Route, Routes } from 'react-router-dom';
import { AdminAuthProvider, RequireAdmin } from '../../auth/AdminAuthContext';
import { AdminShell } from '../../components/admin/AdminShell';
import { Page } from '../../components/layout/AppShell';
import { LinkButton } from '../../components/ui';
import AdminAudit from './AdminAudit';
import AdminDebate from './AdminDebate';
import AdminDebates from './AdminDebates';
import AdminFinance from './AdminFinance';
import AdminLogin from './AdminLogin';
import AdminModels from './AdminModels';
import AdminModeration from './AdminModeration';
import AdminOverview from './AdminOverview';
import AdminSecurity from './AdminSecurity';
import AdminSettings from './AdminSettings';
import AdminSystem from './AdminSystem';
import AdminTrending from './AdminTrending';
import AdminUser from './AdminUser';
import AdminUsers from './AdminUsers';

const AdminNotFound = () => (
  <Page className="text-center">
    <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">404</div>
    <h1 className="mt-2 font-display text-3xl font-extrabold tracking-tight">No such page</h1>
    <div className="mt-6">
      <LinkButton to="/admin" variant="secondary">
        Back to the overview
      </LinkButton>
    </div>
  </Page>
);

/** The admin console (`/admin/*`): its own session, layout and pages, loaded on demand. */
const AdminApp = () => (
  <AdminAuthProvider>
    <Routes>
      <Route path="login" element={<AdminLogin />} />
      <Route
        element={
          <RequireAdmin>
            <AdminShell />
          </RequireAdmin>
        }
      >
        <Route index element={<AdminOverview />} />
        <Route path="users" element={<AdminUsers />} />
        <Route path="users/:id" element={<AdminUser />} />
        <Route path="debates" element={<AdminDebates />} />
        <Route path="debates/:id" element={<AdminDebate />} />
        <Route path="moderation" element={<AdminModeration />} />
        <Route path="trending" element={<AdminTrending />} />
        <Route path="finance" element={<AdminFinance />} />
        <Route path="models" element={<AdminModels />} />
        <Route path="system" element={<AdminSystem />} />
        <Route path="settings" element={<AdminSettings />} />
        <Route path="audit" element={<AdminAudit />} />
        <Route path="security" element={<AdminSecurity />} />
        <Route path="*" element={<AdminNotFound />} />
      </Route>
    </Routes>
  </AdminAuthProvider>
);

export default AdminApp;
