import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react';

export const fieldClass =
  'w-full rounded-field border border-line-2 bg-ink px-3.5 py-2.5 text-sm text-text outline-none transition-colors focus:border-accent disabled:opacity-50';

export const Label = ({ children, hint, className = '' }: { children: ReactNode; hint?: ReactNode; className?: string }) => (
  <label className={`block text-[13px] font-semibold text-text-3 ${className}`}>
    {children}
    {hint && <span className="ml-1.5 font-normal text-dim">{hint}</span>}
  </label>
);

export const Hint = ({ children, tone = 'muted', className = '' }: { children: ReactNode; tone?: 'muted' | 'ok' | 'danger' | 'accent'; className?: string }) => {
  const color = { muted: 'text-dim', ok: 'text-ok', danger: 'text-con', accent: 'text-accent' }[tone];
  return <div className={`mt-1.5 text-xs leading-relaxed ${color} ${className}`}>{children}</div>;
};

export const Input = ({ className = '', ...rest }: InputHTMLAttributes<HTMLInputElement>) => (
  <input className={`${fieldClass} ${className}`} {...rest} />
);

export const Textarea = ({ className = '', ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea className={`${fieldClass} leading-relaxed ${className}`} {...rest} />
);
