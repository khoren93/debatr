import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { useToast } from '../ui';

/** Monospaced snippet with a copy button (commands, configs, a new token). */
export const CopyBlock = ({ text, label = 'Copy', className = '' }: { text: string; label?: string; className?: string }) => {
  const toast = useToast();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Could not copy: select the text and copy it by hand');
    }
  };

  return (
    <div className={`relative min-w-0 rounded-field border border-line bg-ink ${className}`}>
      {/* Wrapped rather than scrolled, so a token or a long command is visible at once; the
          copy button always copies the exact text. */}
      <pre className="whitespace-pre-wrap px-3.5 py-3 pr-12 font-mono text-xs leading-relaxed text-text-2 [overflow-wrap:anywhere]">
        <code>{text}</code>
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label={label}
        title={label}
        className="absolute right-1.5 top-1.5 cursor-pointer rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-text"
      >
        {copied ? <Check className="size-4 text-ok" /> : <Copy className="size-4" />}
      </button>
    </div>
  );
};
