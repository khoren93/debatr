import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { Database, Gauge, LogOut, ShieldCheck } from 'lucide-react';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Logo } from '../ui';
import { formatTime } from './helpers';

// Sections arrive phase by phase (PROGRESS stage A); each item names the permission it needs.
const NAV = [
  { to: '/admin', label: 'Overview', icon: Gauge, end: true, permission: 'console' },
  { to: '/admin/security', label: 'Security', icon: ShieldCheck, end: false, permission: 'console' },
];

const navClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 rounded-[10px] px-3 py-2.5 text-sm font-medium transition-colors ${isActive ? 'bg-surface-2 text-text' : 'text-muted hover:bg-surface-2 hover:text-text'}`;

const AdminBadge = () => (
  <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-accent">
    Admin
  </span>
);

/** Sidebar (desktop) / top bar (phones) of the admin console around the routed page. */
export const AdminShell = () => {
  const { me, signOut } = useAdminAuth();
  const navigate = useNavigate();
  if (!me) return null;
  const items = NAV.filter((item) => me.permissions.includes(item.permission));
  const database = me.permissions.includes('database');

  const leave = async () => {
    await signOut();
    navigate('/admin/login', { replace: true });
  };

  return (
    <div className="flex min-h-screen bg-ink">
      <aside className="sticky top-0 hidden h-screen w-[236px] shrink-0 flex-col border-r border-line bg-ink-2 px-4 py-5.5 md:flex">
        <div className="flex items-center gap-2.5 px-2 pb-5 pt-1">
          <Logo />
          <AdminBadge />
        </div>
        <nav className="flex flex-col gap-1">
          {items.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={navClass}>
              <Icon className="size-[18px]" strokeWidth={1.8} />
              {label}
            </NavLink>
          ))}
          {database && (
            // sqladmin is a server-rendered page, so a full page load.
            <a href="/api/admin/db/" className={navClass({ isActive: false })}>
              <Database className="size-[18px]" strokeWidth={1.8} />
              Database
            </a>
          )}
        </nav>
        <div className="mt-auto rounded-[14px] border border-line bg-surface p-3.5">
          <div className="truncate text-sm font-semibold">{me.user.display_name}</div>
          <div className="truncate text-[11px] text-muted">{me.user.email}</div>
          <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.06em] text-dim">
            {me.user.role} · signed in until {formatTime(me.session.ends_at)}
          </div>
          <button type="button" onClick={leave} className="mt-3 flex w-full cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-line-2 bg-surface-2 px-3 py-2 text-xs font-semibold hover:bg-surface-3">
            <LogOut className="size-3.5" /> Sign out
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col overflow-x-clip">
        <header className="sticky top-0 z-20 border-b border-line bg-ink/85 px-4 py-3 backdrop-blur-xl md:hidden">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Logo size={26} />
              <AdminBadge />
            </div>
            <button type="button" onClick={leave} aria-label="Sign out" className="cursor-pointer rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-text">
              <LogOut className="size-4" />
            </button>
          </div>
          <nav className="-mx-1 mt-3 flex gap-1 overflow-x-auto">
            {items.map(({ to, label, end }) => (
              <NavLink key={to} to={to} end={end} className={({ isActive }) => `shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold ${isActive ? 'bg-surface-2 text-text' : 'text-muted'}`}>
                {label}
              </NavLink>
            ))}
            {database && (
              <a href="/api/admin/db/" className="shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold text-muted">
                Database
              </a>
            )}
          </nav>
        </header>
        <div className="mx-auto flex w-full max-w-[1364px] flex-1 flex-col">
          <Outlet />
        </div>
      </main>
    </div>
  );
};
