import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { Heart } from 'lucide-react';
import { getErrorMessage } from '../../api/client';
import { setLike } from '../../api/debates';
import type { DebateDetail } from '../../api/types';
import { useToast } from '../ui';
import { ICON_ON_PHONES, TOOL_BUTTON } from './toolButton';
import { track } from '../../lib/presence';

interface Props {
  debate: DebateDetail;
  onChange: (likes: number, liked: boolean) => void;
}

/** Heart toggle (the count is in the page's meta line). Anonymous visitors are sent to sign in;
 *  a new account with its email unconfirmed is told to confirm it (it may still take a like back). */
export const LikeButton = ({ debate, onChange }: Props) => {
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  const { likes, liked, can_like: canLike, like_reason: reason } = debate.engagement;
  // Older APIs sent no reason: "cannot like" meant signed out.
  const signIn = reason === 'sign_in' || (!canLike && reason === undefined);
  const confirm = reason === 'confirm_email';

  const toggle = async () => {
    if (signIn) {
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
      return;
    }
    if (confirm && !liked) {
      toast.error('Confirm your email to like debates: open the link we sent you.');
      return;
    }
    if ((!canLike && !(confirm && liked)) || busy) return;
    const next = !liked;
    onChange(Math.max(0, likes + (next ? 1 : -1)), next); // optimistic
    setBusy(true);
    try {
      const res = await setLike(debate.id, next);
      onChange(res.likes, res.liked);
      if (res.liked) track('like', {}, debate.id);
    } catch (err) {
      onChange(likes, liked);
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const title = signIn
    ? 'Sign in to like this debate'
    : confirm && !liked
      ? 'Confirm your email to like debates'
      : reason === 'owner'
        ? 'Your own debate'
        : liked
          ? 'Unlike'
          : 'Like this debate';
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={liked}
      title={title}
      aria-label={title}
      className={`${TOOL_BUTTON} ${ICON_ON_PHONES} ${liked ? '!border-like/45 text-like' : ''}`}
    >
      <Heart className={`size-4 transition-transform ${liked ? 'scale-110 fill-current' : ''}`} />
      <span className="max-sm:hidden">{liked ? 'Liked' : 'Like'}</span>
    </button>
  );
};
