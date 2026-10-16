import { useState } from 'react';
import { Check, Pencil, RefreshCw, X } from 'lucide-react';
import { updateProfile } from '../../api/auth';
import { getErrorMessage } from '../../api/client';
import type { User } from '../../api/types';
import { Avatar, Button, Input, useToast } from '../ui';

const randomSeed = () => Math.random().toString(36).slice(2, 10);

/** Avatar, inline-editable display name and "email · new avatar" line. */
export const ProfileHeader = ({ user, onUser }: { user: User; onUser: (user: User) => void }) => {
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

  const spin = shuffling ? 'animate-spin' : '';

  return (
    <div className="flex items-center gap-4">
      <button
        type="button"
        onClick={shuffleAvatar}
        disabled={shuffling}
        title="New avatar"
        aria-label="Generate a new avatar"
        className="group relative shrink-0 cursor-pointer rounded-[18px] disabled:cursor-wait"
      >
        <Avatar seed={user.avatar_seed} size={56} rounded="lg" />
        <span className="absolute inset-0 grid place-items-center rounded-[18px] bg-ink/60 opacity-0 transition-opacity group-hover:opacity-100">
          <RefreshCw className={`size-4 ${spin}`} />
        </span>
      </button>
      <div className="min-w-0 flex-1">
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
          <div className="flex items-center gap-2">
            <h1 className="truncate font-display text-[clamp(24px,3vw,34px)] font-extrabold leading-tight tracking-[-0.03em]">{user.display_name}</h1>
            <button
              type="button"
              onClick={startEdit}
              className="shrink-0 cursor-pointer rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-text"
              aria-label="Edit name"
            >
              <Pencil className="size-3.5" />
            </button>
          </div>
        )}
        <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[13px] text-muted">
          <span className="truncate">{user.email}</span>
          <span aria-hidden="true">·</span>
          <button
            type="button"
            onClick={shuffleAvatar}
            disabled={shuffling}
            className="inline-flex cursor-pointer items-center gap-1 text-muted hover:text-text disabled:opacity-50"
          >
            <RefreshCw className={`size-3 ${spin}`} /> new avatar
          </button>
        </div>
      </div>
    </div>
  );
};
