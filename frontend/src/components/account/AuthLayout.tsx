import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { APP_NAME } from '../../lib/brand';
import { Card, Logo, SectionLabel } from '../ui';

/** Same glow as the landing hero, toned down for a small centered card. */
const GLOW =
  'radial-gradient(60% 55% at 72% 18%, rgba(217,255,61,0.10), transparent 60%), radial-gradient(45% 50% at 18% 75%, rgba(108,156,255,0.12), transparent 60%)';

interface AuthLayoutProps {
  kicker: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}

/** Self-contained centered layout for /login and /register (the shell hides its chrome there). */
export const AuthLayout = ({ kicker, title, subtitle, footer, children }: AuthLayoutProps) => (
  <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden px-4 py-10 sm:py-14">
    <div aria-hidden="true" className="pointer-events-none absolute inset-0" style={{ background: GLOW }} />
    <div className="relative w-full max-w-[420px] animate-rise">
      <Link to="/" className="mx-auto mb-7 flex w-fit items-center" aria-label={`${APP_NAME} home`}>
        <Logo size={34} />
      </Link>
      <Card padding="lg" className="shadow-2xl">
        <SectionLabel>{kicker}</SectionLabel>
        <h1 className="mt-2 font-display text-[28px] font-extrabold leading-tight tracking-[-0.03em]">{title}</h1>
        {subtitle && <p className="mt-2 text-sm leading-relaxed text-muted">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </Card>
      {footer && <div className="mt-5 text-center text-sm text-muted">{footer}</div>}
    </div>
  </div>
);
