import { ChevronDown } from 'lucide-react';
import type { ReactNode } from 'react';

interface PickerFaceProps {
  /** Content of the 36px tile (provider logo, mic, mask). */
  icon: ReactNode;
  /** Speaker colour: the icon, the tag and the open border. */
  color: string;
  /** Outline the tile in the speaker colour (model field). */
  outlined?: boolean;
  /** Role chip before the title (HOST / PRO / CON …). */
  tag?: string;
  title: ReactNode;
  sub?: ReactNode;
  open: boolean;
}

/** Inside of a speaker-row field: tile, title (+ role chip), subtitle and chevron. */
export const PickerFace = ({ icon, color, outlined = false, tag, title, sub, open }: PickerFaceProps) => (
  <>
    <span className="grid size-9 shrink-0 place-items-center rounded-[10px] border bg-surface-2" style={{ color, borderColor: outlined ? color : 'transparent' }}>
      {icon}
    </span>
    <span className="min-w-0 flex-1">
      <span className="flex min-w-0 items-center gap-2">
        {tag && (
          <span className="shrink-0 rounded-[5px] px-1.5 py-0.5 font-mono text-[10px] font-medium tracking-[0.08em]" style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}>
            {tag}
          </span>
        )}
        <span className="truncate text-sm font-semibold text-text">{title}</span>
      </span>
      {sub && <span className="mt-px block truncate text-xs text-muted">{sub}</span>}
    </span>
    <ChevronDown className={`size-4 shrink-0 text-muted transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
  </>
);
