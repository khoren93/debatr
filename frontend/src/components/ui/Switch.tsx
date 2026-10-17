/** Visual on/off track; the surrounding button carries `role="switch"` and `aria-checked`. */
export const SwitchTrack = ({ on, size = 'md', className = '' }: { on: boolean; size?: 'sm' | 'md'; className?: string }) => {
  const sm = size === 'sm';
  return (
    <span
      aria-hidden="true"
      className={`relative shrink-0 rounded-full transition-colors ${on ? 'bg-accent' : 'bg-surface-4'} ${sm ? 'h-[18px] w-8' : 'h-[23px] w-10'} ${className}`}
    >
      <span
        className={`absolute rounded-full transition-transform ${on ? 'bg-ink' : 'bg-muted'} ${sm ? 'top-0.5 left-0.5 size-3.5' : 'top-[3px] left-[3px] size-[17px]'}`}
        style={{ transform: on ? `translateX(${sm ? 14 : 17}px)` : undefined }}
      />
    </span>
  );
};
