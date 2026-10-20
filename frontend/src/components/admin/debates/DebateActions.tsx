import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { AudioLines, Ban, CheckCircle2, CircleDollarSign, Eye, EyeOff, Layers, Play, RefreshCw, Square, Trash2 } from 'lucide-react';
import { debateAction, moveDebateMotion, rebuildDebateMedia, refundDebate, type DebateAction } from '../../../api/admin/debates';
import type { AdminDebateCard } from '../../../api/admin/types';
import { FormField } from '../../account/FormField';
import { Button, SwitchTrack, useToast } from '../../ui';
import { ActionDialog } from '../ActionDialog';
import { formatUsd } from '../helpers';

type Dialog = DebateAction | 'media' | 'refund' | 'motion';

interface Spec {
  title: string;
  body: string;
  confirm: string;
  danger?: boolean;
  sudo?: boolean;
}

const SIMPLE: Record<DebateAction, Spec> = {
  stop: { title: 'Stop the debate?', body: 'A running turn ends early; the owner is charged for what ran.', confirm: 'Stop', danger: true },
  resume: {
    title: 'Resume the debate?',
    body: 'It runs again from the failed turn on the system key. The owner is charged for what the run adds, as if they resumed it; refund it afterwards if it was our fault.',
    confirm: 'Resume',
  },
  recount: { title: 'Recount likes and votes?', body: 'The counters are rebuilt from the like and vote rows.', confirm: 'Recount' },
  delete: {
    title: 'Delete the debate?',
    body: 'Turns, likes, votes, audio and pictures go with it; ledger rows stay. This cannot be undone.',
    confirm: 'Delete for good',
    danger: true,
    sudo: true,
  },
  approve: { title: 'Approve for the gallery?', body: 'It goes public at once when the owner asked for the gallery; otherwise it stays private.', confirm: 'Approve' },
  reject: { title: 'Reject it?', body: 'It leaves the gallery now and the owner cannot publish it.', confirm: 'Reject', danger: true },
  publish: { title: 'Publish to the gallery?', body: 'The owner asked for it; it gets its public link.', confirm: 'Publish' },
  unpublish: { title: 'Take it out of the gallery?', body: 'The link stops working for others; the owner may publish it again unless it is rejected.', confirm: 'Unpublish', danger: true },
};

interface DebateActionsProps {
  card: AdminDebateCard;
  permissions: string[];
  onChanged: () => void;
}

/** The debate's action buttons (by role and state) and their dialogs. */
export const DebateActions = ({ card, permissions, onChanged }: DebateActionsProps) => {
  const toast = useToast();
  const navigate = useNavigate();
  const d = card.debate;
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [force, setForce] = useState(false);
  const [amount, setAmount] = useState('');
  const [requestKey, setRequestKey] = useState('');
  const [target, setTarget] = useState('');
  const [whole, setWhole] = useState(false);
  const may = (permission: string) => permissions.includes(permission);
  const finished = ['completed', 'error', 'stopped'].includes(d.status);
  const building = ['queued', 'running'].includes(d.media_status);
  const refundable = card.refundable ?? 0;
  const typed = amount.trim() ? Number(amount.trim().replace(',', '.')) : refundable;
  const amountOk = Number.isFinite(typed) && typed > 0 && typed <= refundable + 1e-9;

  const buttons: { key: Dialog; label: string; icon: ReactNode; show: boolean; variant?: 'primary' | 'secondary' | 'danger' }[] = [
    { key: 'approve', label: 'Approve', icon: <CheckCircle2 className="size-4" />, show: may('moderation') && d.moderation_status !== 'approved', variant: d.moderation_status === 'flagged' ? 'primary' : 'secondary' },
    { key: 'reject', label: 'Reject', icon: <Ban className="size-4" />, show: may('moderation') && d.moderation_status !== 'rejected', variant: 'danger' },
    {
      key: 'publish',
      label: 'Publish',
      icon: <Eye className="size-4" />,
      show: may('moderation') && !d.is_public && d.status === 'completed' && card.wants_public && !['flagged', 'rejected'].includes(d.moderation_status),
    },
    { key: 'unpublish', label: 'Unpublish', icon: <EyeOff className="size-4" />, show: may('moderation') && d.is_public },
    { key: 'stop', label: 'Stop', icon: <Square className="size-4" />, show: may('debates') && ['queued', 'running'].includes(d.status), variant: 'danger' },
    { key: 'resume', label: `Resume from turn ${(card.resume_from ?? 0) + 1}`, icon: <Play className="size-4" />, show: may('debates') && card.resume_from !== null },
    { key: 'media', label: 'Rebuild audio', icon: <AudioLines className="size-4" />, show: may('debates') && finished && !building },
    { key: 'refund', label: 'Refund', icon: <CircleDollarSign className="size-4" />, show: may('money') && refundable > 0 && d.owner !== null },
    { key: 'motion', label: 'Topic…', icon: <Layers className="size-4" />, show: may('moderation') && card.motion !== null },
    { key: 'recount', label: 'Recount likes', icon: <RefreshCw className="size-4" />, show: may('debates') },
    { key: 'delete', label: 'Delete', icon: <Trash2 className="size-4" />, show: may('debates'), variant: 'danger' },
  ];

  const open = (key: Dialog) => {
    if (key === 'media') setForce(false);
    if (key === 'refund') {
      setAmount('');
      setRequestKey(crypto.randomUUID());
    }
    if (key === 'motion') {
      setTarget('');
      setWhole(false);
    }
    setDialog(key);
  };
  const close = () => setDialog(null);
  const simple = dialog && dialog !== 'media' && dialog !== 'refund' && dialog !== 'motion' ? dialog : null;

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {buttons
          .filter((b) => b.show)
          .map((b) => (
            <Button key={b.key} size="sm" variant={b.variant ?? 'secondary'} icon={b.icon} onClick={() => open(b.key)}>
              {b.label}
            </Button>
          ))}
      </div>

      {simple && (
        <ActionDialog
          open
          title={SIMPLE[simple].title}
          body={SIMPLE[simple].body}
          confirmLabel={SIMPLE[simple].confirm}
          danger={SIMPLE[simple].danger}
          sudo={SIMPLE[simple].sudo}
          autoFocusReason
          onClose={close}
          onSubmit={async (reason) => {
            const out = await debateAction(d.id, simple, reason);
            toast.success(out.message);
            if (simple === 'delete') navigate('/admin/debates', { replace: true });
            else onChanged();
          }}
        />
      )}

      <ActionDialog
        open={dialog === 'media'}
        title="Rebuild the audio?"
        body="Same voices and scene options as the last build, on the system keys. Free for the owner: nothing is charged."
        confirmLabel="Rebuild"
        onClose={close}
        onSubmit={async (reason) => {
          const out = await rebuildDebateMedia(d.id, reason, force);
          toast.success(out.message);
          onChanged();
        }}
      >
        <button
          type="button"
          role="switch"
          aria-checked={force}
          onClick={() => setForce(!force)}
          className="flex w-full cursor-pointer items-start gap-3 rounded-[12px] border border-line bg-ink px-3 py-2.5 text-left"
        >
          <SwitchTrack on={force} size="sm" className="mt-0.5" />
          <span>
            <span className="block text-sm font-semibold text-text-2">Voice every turn again</span>
            <span className="block text-xs text-muted">Off: turns voiced before are reused from the cache</span>
          </span>
        </button>
      </ActionDialog>

      <ActionDialog
        open={dialog === 'motion'}
        title="Change the topic?"
        body={`Versions of one topic share a card in the gallery. This one is in a topic with ${card.motion?.debates ?? 0} ${card.motion?.debates === 1 ? 'debate' : 'debates'} (${card.motion?.public_versions ?? 0} public).`}
        confirmLabel={whole ? 'Merge the topic' : target.trim() ? 'Move it' : 'Split it off'}
        ready={!whole || target.trim().length > 0}
        onClose={close}
        onSubmit={async (reason) => {
          const out = await moveDebateMotion(d.id, { reason, target: target.trim() || undefined, whole });
          toast.success(out.message);
          onChanged();
        }}
      >
        <FormField
          label="Into the topic of"
          optional
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="Topic link (/t/…), debate link or id"
          hint="Empty: a topic of its own (later debates with this exact text still join the old topic)"
        />
        <button
          type="button"
          role="switch"
          aria-checked={whole}
          onClick={() => setWhole(!whole)}
          className="flex w-full cursor-pointer items-start gap-3 rounded-[12px] border border-line bg-ink px-3 py-2.5 text-left"
        >
          <SwitchTrack on={whole} size="sm" className="mt-0.5" />
          <span>
            <span className="block text-sm font-semibold text-text-2">Move the whole topic (merge)</span>
            <span className="block text-xs text-muted">Every version goes, and the topic's text and link lead to the other one from now on</span>
          </span>
        </button>
      </ActionDialog>

      <ActionDialog
        open={dialog === 'refund'}
        title="Refund the debate?"
        body={`Up to ${formatUsd(refundable)} goes back to ${d.owner?.email ?? 'the owner'} as a refund row tied to this debate.`}
        confirmLabel={amountOk ? `Refund ${formatUsd(typed)}` : 'Refund'}
        ready={amountOk}
        onClose={close}
        onSubmit={async (reason) => {
          const out = await refundDebate(d.id, { reason, amount: amount.trim() ? amount.trim().replace(',', '.') : undefined, idempotency_key: requestKey });
          toast.success(out.duplicate ? 'Already refunded: nothing changed' : `Refunded ${formatUsd(out.amount)}; balance ${formatUsd(out.balance_after)}`);
          onChanged();
        }}
      >
        <FormField
          label="Amount, USD"
          optional
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder={String(refundable)}
          hint="Empty: everything still refundable"
          error={amount.trim() && !amountOk ? `A positive amount up to ${formatUsd(refundable)}` : undefined}
        />
      </ActionDialog>
    </>
  );
};
