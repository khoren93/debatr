import type { AdminRole } from '../../../api/admin/types';

const pill = 'shrink-0 rounded-full px-1.5 py-px font-mono text-[10px] font-semibold uppercase tracking-[0.06em]';

/** Role and "disabled" marks next to an account's name. */
export const UserBadges = ({ role, active, official = false, emailPending = false }: { role: AdminRole | null; active: boolean; official?: boolean; emailPending?: boolean }) => (
  <>
    {official && <span className={`${pill} border border-accent/30 bg-accent/10 text-accent`}>official</span>}
    {emailPending && <span className={`${pill} border border-host/30 bg-host/10 text-host`}>email unconfirmed</span>}
    {role && <span className={`${pill} border border-accent/30 bg-accent/10 text-accent`}>{role}</span>}
    {!active && <span className={`${pill} border border-con/30 bg-con/10 text-con`}>disabled</span>}
  </>
);
