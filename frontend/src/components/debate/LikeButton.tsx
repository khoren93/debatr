import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Heart } from 'lucide-react';
import { getErrorMessage } from '../../api/client';
import { setLike } from '../../api/debates';
import type { DebateDetail } from '../../api/types';
import { formatCount } from '../../lib/format';
import { useToast } from '../ui';
import { TOOL_BUTTON } from './toolButton';

interface Props {
  debate: DebateDetail;
  onChange: (likes: number, liked: boolean) => void;
}

/** Heart toggle with the like count. Anonymous visitors are sent to sign in; owners see the count. */
export const LikeButton = ({ debate, onChange }: Props) => {
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  const { likes, liked, can_like: canLike } = debate.engagement;
  const signIn = !canLike && !debate.is_owner;

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

  const title = debate.is_owner ? 'Likes on your debate' : signIn ? 'Sign in to like this debate' : liked ? 'Unlike' : 'Like this debate';
  return (
    <button
      type="button"
      onClick={toggle}
      disabled={debate.is_owner}
      aria-pressed={liked}
      title={title}
      aria-label={`${title} (${likes})`}
      className={`${TOOL_BUTTON} disabled:cursor-default disabled:hover:bg-surface ${liked ? '!border-like/45 text-like' : ''}`}
    >
      <Heart className={`size-4 transition-transform ${liked ? 'scale-110 fill-current' : ''}`} />
      {likes > 0 ? formatCount(likes) : 'Like'}
    </button>
  );
};
