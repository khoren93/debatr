import { ArrowUpRight, CircleAlert, Info, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { AttentionItem } from '../../api/admin/types';

const LOOK = {
  critical: { icon: CircleAlert, tone: 'text-con', label: 'Critical' },
  warning: { icon: TriangleAlert, tone: 'text-host', label: 'Warning' },
  info: { icon: Info, tone: 'text-pro', label: 'Info' },
} as const;

const Target = ({ href, children }: { href: string | null; children: ReactNode }) => {
  const className = 'flex items-start gap-3 rounded-[12px] px-3 py-2.5 transition-colors hover:bg-surface-2';
  if (!href) return <div className={className}>{children}</div>;
  if (href.startsWith('/admin')) {
    return (
      <Link to={href} className={className}>
        {children}
      </Link>
    );
  }
  const external = href.startsWith('http');
  return (
    <a href={href} className={className} {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}>
      {children}
    </a>
  );
};

/** What needs a look now, most severe first; each row opens the place to act. */
export const AttentionList = ({ items }: { items: AttentionItem[] }) => (
  <ul className="grid gap-0.5">
    {items.map((item) => {
      const { icon: Icon, tone, label } = LOOK[item.severity];
      return (
        <li key={item.key}>
          <Target href={item.href}>
            <Icon className={`mt-0.5 size-4 shrink-0 ${tone}`} aria-label={label} />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-text">{item.title}</span>
              {item.detail && <span className="block text-xs text-muted">{item.detail}</span>}
            </span>
            {item.href && <ArrowUpRight className="mt-0.5 size-4 shrink-0 text-dim" />}
          </Target>
        </li>
      );
    })}
  </ul>
);
