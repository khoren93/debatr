import { BadgeCheck } from 'lucide-react';
import { APP_NAME } from '../../lib/brand';
import { initialOf } from '../../lib/format';
import { LogoMark } from './Logo';

const PALETTE = ['#6C9CFF', '#D9FF3D', '#FF7A66', '#FFC46B', '#A78BFA', '#34D399', '#F472B6', '#22D3EE'];

const hash = (s: string) => {
  let h = 7;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
};

/** Gradient avatar derived from a seed (user avatars). */
// eslint-disable-next-line react-refresh/only-export-components
export const avatarGradient = (seed: string) => {
  const h = hash(seed || 'debatr');
  const a = PALETTE[h % PALETTE.length];
  // `>>>`: the hash is an unsigned 32-bit value; a signed shift gave negative indices.
  const b = PALETTE[(h >>> 3) % PALETTE.length];
  return `linear-gradient(135deg, ${a}, ${b === a ? PALETTE[(h + 1) % PALETTE.length] : b})`;
};

export const Avatar = ({ seed, size = 28, className = '', rounded = 'full' }: { seed: string; size?: number; className?: string; rounded?: 'full' | 'lg' }) => (
  <span
    className={`inline-block shrink-0 ${rounded === 'full' ? 'rounded-full' : 'rounded-[18px]'} ${className}`}
    style={{ width: size, height: size, background: avatarGradient(seed) }}
    aria-hidden="true"
  />
);

/** A person's avatar: the gradient of `seed`, or the site's logo for its own account (`official`). */
export const UserAvatar = ({ seed, official = false, size = 28, className = '', rounded = 'full' }: { seed: string; official?: boolean; size?: number; className?: string; rounded?: 'full' | 'lg' }) =>
  official ? (
    <span className={`inline-flex shrink-0 ${className}`}>
      <LogoMark size={size} />
    </span>
  ) : (
    <Avatar seed={seed} size={size} className={className} rounded={rounded} />
  );

/** The check next to the site's own account's name. */
export const OfficialMark = ({ className = 'size-3.5' }: { className?: string }) => (
  <span title={`Official ${APP_NAME} account`} className="inline-flex shrink-0 text-accent">
    <BadgeCheck className={className} strokeWidth={2.2} aria-hidden="true" />
    <span className="sr-only">Official {APP_NAME} account</span>
  </span>
);

/** Coloured square with the speaker's initial (transcript, lineup, review). */
export const SpeakerBadge = ({ name, color, size = 36, imageUrl, className = '' }: { name: string | null | undefined; color: string; size?: number; imageUrl?: string | null; className?: string }) => (
  <span
    className={`grid shrink-0 place-items-center overflow-hidden font-extrabold text-ink ${className}`}
    style={{ width: size, height: size, borderRadius: Math.round(size * 0.28), background: color, fontSize: Math.round(size * 0.36) }}
    aria-hidden="true"
  >
    {imageUrl ? <img src={imageUrl} alt="" className="size-full object-cover" /> : initialOf(name)}
  </span>
);
