import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Heart } from 'lucide-react';
import { getErrorMessage } from '../../api/client';
import { setLike } from '../../api/debates';
import type { DebateDetail } from '../../api/types';
import { useToast } from '../ui';
import { ICON_ON_PHONES, TOOL_BUTTON } from './toolButton';

interface Props {
  debate: DebateDetail;
  onChange: (likes: number, liked: boolean) => void;
}

/** Heart toggle (the count is in the page's meta line). Anonymous visitors are sent to sign in. */
export const LikeButton = ({ debate, onChange }: Props) => {
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  const { likes, liked, can_like: canLike } = debate.engagement;
  const signIn = !canLike;

  const toggle = async () => {
    if (signIn) {
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
      return;
    }
    if (!canLike || busy) return;
    const next = !liked;
    onChange(Math.max(0, likes + (next ? 1 : -1)), next); // optimistic
    setBusy(true);
    try {
      const res = await setLike(debate.id, next);
      onChange(res.likes, res.liked);
    } catch (err) {
      onChange(likes, liked);
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const title = signIn ? 'Sign in to like this debate' : liked ? 'Unlike' : 'Like this debate';
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
