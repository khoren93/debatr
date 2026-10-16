import { Link, NavLink, useLocation } from 'react-router-dom';
import { Home, LayoutGrid, Play, Plus, Trophy, UserRound } from 'lucide-react';
import type { ReactNode } from 'react';
import { useAuth } from '../../auth/AuthContext';
import { Avatar, Logo, Progress } from '../ui';

const NAV = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/library', label: 'Library', icon: LayoutGrid },
  { to: '/create', label: 'Create', icon: Plus },
  { to: '/gallery', label: 'Gallery', icon: Play },
  // Phones keep five bottom tabs; the gallery links to the ranking there.
  { to: '/leaderboard', label: 'Ranking', icon: Trophy, desktopOnly: true },
  { to: '/account', label: 'Account', icon: UserRound },
];

const money = (n: number) => `$${n.toFixed(2)}`;

const CreditsCard = () => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) {
    return (
      <div className="rounded-[14px] border border-line bg-surface p-3.5">
        <div className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted">Account</div>
        <p className="mt-1.5 text-xs text-muted leading-relaxed">Sign in to run debates, keep a library and buy credits.</p>
        <div className="mt-3 flex gap-2">
          <Link to="/login" className="flex-1 rounded-[10px] bg-surface-2 border border-line-2 px-3 py-2 text-center text-xs font-semibold hover:bg-surface-3">
            Sign in
          </Link>
          <Link to="/register" className="flex-1 rounded-[10px] bg-accent px-3 py-2 text-center text-xs font-bold text-ink hover:bg-accent-hover">
            Join
          </Link>
        </div>
      </div>
    );
  }
  const balance = Math.max(0, user.credits_usd);
  return (
    <div className="rounded-[14px] border border-line bg-surface p-3.5">
      <div className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted">Credits</div>
      <div className="mt-1.5 flex items-baseline justify-between">
        <span className="font-display text-[22px] font-bold">{money(user.credits_usd)}</span>
        <Link to="/account" className="text-xs text-accent hover:text-accent-hover">
          Top up
        </Link>
      </div>
      <Progress value={Math.min(1, balance / 10)} className="mt-2.5" />
    </div>
  );
};

const Sidebar = () => {
  const { user } = useAuth();
  return (
    <aside className="sticky top-0 hidden h-screen w-[236px] shrink-0 flex-col border-r border-line bg-ink-2 px-4 py-5.5 md:flex">
      <Link to="/" className="flex items-center gap-2.5 px-2 pb-5 pt-1">
        <Logo />
      </Link>
      <nav className="flex flex-col gap-1">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-[10px] px-3 py-2.5 text-sm font-medium transition-colors ${isActive ? 'bg-surface-2 text-text' : 'text-muted hover:bg-surface-2 hover:text-text'}`
            }
          >
            <Icon className="size-[18px]" strokeWidth={1.8} />
            {label}
          </NavLink>
        ))}
      </nav>
      <Link to="/create" className="mt-4 flex items-center justify-center gap-2 rounded-field bg-accent px-3 py-3 text-sm font-bold text-ink hover:bg-accent-hover">
        <Plus className="size-4" strokeWidth={2.5} /> New debate
      </Link>
      <div className="mt-auto">
        {user && (
          <Link to="/account" className="mb-3 flex items-center gap-2.5 rounded-[10px] px-2 py-1.5 hover:bg-surface-2">
            <Avatar seed={user.avatar_seed} size={26} />
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold">{user.display_name}</span>
              <span className="block truncate text-[11px] text-muted">{user.email}</span>
            </span>
          </Link>
        )}
        <CreditsCard />
      </div>
    </aside>
  );
};

const MobileTopBar = () => {
  const { user } = useAuth();
  return (
    <header data-bar="top" className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-ink/85 px-4 py-3 backdrop-blur-xl md:hidden">
      <Link to="/" className="flex items-center gap-2">
        <Logo size={26} />
      </Link>
      {user ? (
        <Link to="/account" className="flex items-center gap-2 rounded-full border border-line-2 bg-surface py-1.5 pl-3 pr-1.5 font-mono text-xs">
          {money(user.credits_usd)}
          <Avatar seed={user.avatar_seed} size={22} />
        </Link>
      ) : (
        <Link to="/login" className="rounded-full bg-accent px-3.5 py-1.5 text-xs font-bold text-ink">
          Sign in
        </Link>
      )}
    </header>
  );
};

const MobileTabs = () => (
  <nav data-bar="bottom" className="fixed inset-x-0 bottom-0 z-30 flex items-center justify-around border-t border-line bg-ink-2/95 px-1.5 pt-2 pb-[calc(10px+env(safe-area-inset-bottom))] backdrop-blur-xl md:hidden">
    {NAV.filter((item) => !item.desktopOnly).map(({ to, label, icon: Icon, end }) => (
      <NavLink
        key={to}
        to={to}
        end={end}
        className={({ isActive }) =>
          `flex min-h-11 min-w-14 flex-col items-center justify-center gap-1 rounded-field px-2 py-1.5 text-[10px] font-semibold ${isActive ? 'text-text' : 'text-muted'}`
        }
      >
        <Icon className="size-[22px]" strokeWidth={1.8} />
        {label}
      </NavLink>
    ))}
  </nav>
);

/** Desktop sidebar + mobile top bar / bottom tabs around the routed page. */
export const AppShell = ({ children }: { children: ReactNode }) => {
  const { pathname } = useLocation();
  const bare = pathname === '/login' || pathname === '/register';
  return (
    <div className="relative flex min-h-screen bg-ink">
      {/* The sidebar stays pinned to the left edge; only the page content is capped and centred. */}
      {!bare && <Sidebar />}
      <main className="flex min-w-0 flex-1 flex-col pb-24 md:pb-0">
        {!bare && <MobileTopBar />}
        <div className="mx-auto flex w-full max-w-[1364px] flex-1 flex-col">{children}</div>
      </main>
      {!bare && <MobileTabs />}
    </div>
  );
};

/** Standard page padding from the design. */
export const Page = ({ children, className = '' }: { children: ReactNode; className?: string }) => (
  <section className={`w-full px-[clamp(18px,4vw,48px)] pt-[clamp(20px,3.5vw,44px)] pb-24 ${className}`}>
    {children}
  </section>
);

export const PageTitle = ({ kicker, title, right }: { kicker?: ReactNode; title: ReactNode; right?: ReactNode }) => (
  <div className="flex flex-wrap items-end justify-between gap-4">
    <div>
      {kicker && <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">{kicker}</div>}
      <h1 className="mt-1.5 font-display text-[clamp(28px,3.4vw,42px)] font-extrabold leading-tight tracking-[-0.03em]">{title}</h1>
    </div>
    {right}
  </div>
);
