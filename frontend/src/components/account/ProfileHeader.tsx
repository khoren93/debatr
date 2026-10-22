import { useState, type ReactNode } from 'react';
import { Check, Pencil, RefreshCw, X } from 'lucide-react';
import { updateProfile } from '../../api/auth';
import { getErrorMessage } from '../../api/client';
import type { User } from '../../api/types';
import { Button, Input, OfficialMark, UserAvatar, useToast } from '../ui';
import { monthYear } from './helpers';

const randomSeed = () => Math.random().toString(36).slice(2, 10);

interface ProfileHeaderProps {
  user: User;
  onUser: (user: User) => void;
  /** Right-hand slot (the page tabs). */
  children?: ReactNode;
}

/** Avatar with a "new avatar" button, inline-editable display name, email and member-since line. */
export const ProfileHeader = ({ user, onUser, children }: ProfileHeaderProps) => {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [shuffling, setShuffling] = useState(false);

  const startEdit = () => {
    setDraft(user.display_name);
    setEditing(true);
  };

  const saveName = async () => {
    const name = draft.trim();
    if (!name || name === user.display_name) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      onUser(await updateProfile({ display_name: name }));
      toast.success('Name updated');
      setEditing(false);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const shuffleAvatar = async () => {
    setShuffling(true);
    try {
      onUser(await updateProfile({ avatar_seed: randomSeed() }));
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setShuffling(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-[18px]">
      <div className="relative shrink-0">
        <UserAvatar seed={user.avatar_seed} official={user.official} size={64} rounded="lg" />
        {/* The site's own account keeps the logo. */}
        {!user.official && (
          <button
            type="button"
            onClick={shuffleAvatar}
            disabled={shuffling}
            title="New avatar"
            aria-label="Generate a new avatar"
            className="absolute -right-1.5 -bottom-1.5 grid size-[26px] cursor-pointer place-items-center rounded-[9px] border-2 border-ink bg-surface-2 text-text-3 transition-colors hover:text-accent disabled:cursor-wait"
          >
            <RefreshCw className={`size-3 ${shuffling ? 'animate-spin' : ''}`} strokeWidth={2.4} />
          </button>
        )}
      </div>
      <div className="min-w-[200px] flex-1">
        {editing ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void saveName();
            }}
            className="flex flex-wrap items-center gap-2"
          >
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setEditing(false);
              }}
              autoFocus
              maxLength={60}
              aria-label="Display name"
              className="max-w-xs font-display text-lg! font-bold"
            />
            <Button type="submit" size="sm" loading={saving} icon={<Check className="size-4" />}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={saving} icon={<X className="size-4" />}>
              Cancel
            </Button>
          </form>
        ) : (
          <div className="flex items-center gap-2.5">
            <h1 className="truncate font-display text-[clamp(26px,3vw,36px)] leading-none font-extrabold tracking-[-0.03em]">{user.display_name}</h1>
            {user.official && <OfficialMark className="size-5" />}
            <button
              type="button"
              onClick={startEdit}
              className="shrink-0 cursor-pointer rounded-lg p-1 text-dim transition-colors hover:text-text"
              aria-label="Edit name"
              title="Edit name"
            >
              <Pencil className="size-3.5" />
            </button>
          </div>
        )}
        <div className="mt-1.5 flex flex-wrap gap-x-1.5 text-sm text-muted">
          <span className="min-w-0 truncate">{user.email}</span>
          <span className="max-sm:hidden" aria-hidden="true">
            ·
          </span>
          <span>Member since {monthYear(user.created_at)}</span>
        </div>
      </div>
      {children}
    </div>
  );
};
