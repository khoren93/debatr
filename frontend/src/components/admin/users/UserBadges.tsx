import type { AdminRole } from '../../../api/admin/types';

const pill = 'shrink-0 rounded-full px-1.5 py-px font-mono text-[10px] font-semibold uppercase tracking-[0.06em]';

/** Role and "disabled" marks next to an account's name. */
export const UserBadges = ({ role, active }: { role: AdminRole | null; active: boolean }) => (
  <>
    {role && <span className={`${pill} border border-accent/30 bg-accent/10 text-accent`}>{role}</span>}
    {!active && <span className={`${pill} border border-con/30 bg-con/10 text-con`}>disabled</span>}
  </>
);
