import { Link } from 'react-router-dom';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'light';
export type ButtonSize = 'sm' | 'md' | 'lg';

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-ink hover:bg-accent-hover font-bold',
  secondary: 'bg-surface border border-line-2 text-text hover:bg-surface-2 font-semibold',
  ghost: 'bg-transparent text-muted hover:text-text hover:bg-surface-2 font-semibold',
  danger: 'bg-surface border border-line-2 text-con hover:bg-surface-2 font-semibold',
  light: 'bg-text text-ink hover:bg-white font-bold',
};

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-9 px-3.5 text-[13px] rounded-[10px] gap-1.5',
  md: 'h-11 px-5 text-sm rounded-[12px] gap-2',
  lg: 'h-13 px-6 text-[15px] rounded-[14px] gap-2',
};

// eslint-disable-next-line react-refresh/only-export-components
export const buttonClass = (variant: ButtonVariant = 'primary', size: ButtonSize = 'md', extra = '') =>
  `inline-flex items-center justify-center whitespace-nowrap transition-colors cursor-pointer select-none disabled:opacity-50 disabled:cursor-not-allowed ${VARIANTS[variant]} ${SIZES[size]} ${extra}`;

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = ({ variant = 'primary', size = 'md', loading = false, icon, className = '', children, disabled, type = 'button', ...rest }: ButtonProps) => (
  <button type={type} className={buttonClass(variant, size, className)} disabled={disabled || loading} {...rest}>
    {loading ? <Spinner className="size-4" /> : icon}
    {children}
  </button>
);

interface LinkButtonProps {
  to: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  className?: string;
  /** Open in a new tab (keeps an in-progress form intact). */
  newTab?: boolean;
  children: ReactNode;
}

export const LinkButton = ({ to, variant = 'primary', size = 'md', icon, className = '', newTab = false, children }: LinkButtonProps) => (
  <Link to={to} className={buttonClass(variant, size, className)} {...(newTab ? { target: '_blank', rel: 'noreferrer' } : {})}>
    {icon}
    {children}
  </Link>
);
