import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Laptop, LogOut, RefreshCw } from 'lucide-react';
import { adminLogoutEverywhere, listAdminSessions, regenerateRecoveryCodes, revokeAdminSession } from '../../api/admin/auth';
import { needsSudo } from '../../api/admin/client';
import type { AdminSessionRow } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { PasskeysCard } from '../../components/admin/PasskeysCard';
import { RecoveryCodes } from '../../components/admin/RecoveryCodes';
import { SudoDialog } from '../../components/admin/SudoDialog';
import { describeAgent, formatTime } from '../../components/admin/helpers';
import { Button, Card, ConfirmDialog, ErrorBox, Modal, SectionLabel, Spinner, useToast } from '../../components/ui';

const AdminSecurity = () => {
  const { me, refresh, setMe } = useAdminAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [rows, setRows] = useState<AdminSessionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [revoking, setRevoking] = useState<AdminSessionRow | null>(null);
  const [everywhere, setEverywhere] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sudoOpen, setSudoOpen] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    listAdminSessions()
      .then((found) => {
        if (!cancelled) setRows(found);
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  if (!me) return null;

  const revoke = async () => {
    if (!revoking) return;
    setBusy(true);
    try {
      await revokeAdminSession(revoking.id);
      if (revoking.current) {
        setMe(null);
        navigate('/admin/login', { replace: true });
        return;
      }
      toast.success('Session ended');
      setReload((n) => n + 1);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
      setRevoking(null);
    }
  };

  const signOutEverywhere = async () => {
    setBusy(true);
    try {
      await adminLogoutEverywhere();
      setMe(null);
      navigate('/admin/login', { replace: true });
    } catch (err) {
      toast.error(getErrorMessage(err));
      setBusy(false);
    }
  };

  const newCodes = async () => {
    setBusy(true);
    try {
      setCodes((await regenerateRecoveryCodes()).recovery_codes);
      await refresh();
    } catch (err) {
      if (needsSudo(err)) setSudoOpen(true);
      else toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page>
      <PageTitle kicker="Admin console" title="Security" />
      <div className="mt-8 grid gap-5 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <SectionLabel>Your console sessions</SectionLabel>
            <Button variant="danger" size="sm" icon={<LogOut className="size-4" />} onClick={() => setEverywhere(true)}>
              Sign out everywhere
            </Button>
          </div>
          {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
          {!rows && !error && <Spinner className="mt-6 size-5" />}
          <ul className="mt-4 divide-y divide-line">
            {rows?.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-3 py-3">
                <Laptop className="size-5 shrink-0 text-muted" strokeWidth={1.6} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {describeAgent(row.user_agent)}
                    {row.current && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-bold uppercase text-accent">This device</span>}
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    {row.ip || 'unknown IP'} · signed in {formatTime(row.created_at)} · active {formatTime(row.last_seen_at)}
                  </div>
                </div>
                <Button variant="secondary" size="sm" onClick={() => setRevoking(row)}>
                  End
                </Button>
              </li>
            ))}
          </ul>
        </Card>

        {me.two_factor ? (
          <div className="grid content-start gap-5">
            <Card>
              <SectionLabel>Recovery codes</SectionLabel>
              <div className="mt-2 font-display text-2xl font-bold">{me.recovery_codes_left} left</div>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                New codes replace all the old ones. Lost the phone and the codes? On the server:{' '}
                <code className="font-mono text-xs text-text-2">python -m app.manage admin reset-2fa {me.user.email}</code>
              </p>
              <Button variant="secondary" size="sm" className="mt-4" icon={<RefreshCw className="size-4" />} loading={busy && !revoking && !everywhere} onClick={newCodes}>
                Make new codes
              </Button>
            </Card>
            <PasskeysCard />
          </div>
        ) : (
          <Card>
            <SectionLabel>Two-factor</SectionLabel>
            <div className="mt-2 font-display text-2xl font-bold">Off on this server</div>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              <code className="font-mono text-xs text-text-2">ADMIN_SKIP_2FA</code> lets the console in with the password alone and skips confirmation codes. Production ignores it.
            </p>
          </Card>
        )}
      </div>

      <ConfirmDialog
        open={revoking !== null}
        title="End this session?"
        body={revoking?.current ? 'This is the session you are using: you will be signed out.' : 'That browser will have to sign in again.'}
        confirmLabel="End session"
        danger
        busy={busy}
        onConfirm={revoke}
        onClose={() => setRevoking(null)}
      />
      <ConfirmDialog
        open={everywhere}
        title="Sign out everywhere?"
        body="Every console session ends, this one included."
        confirmLabel="Sign out everywhere"
        danger
        busy={busy}
        onConfirm={signOutEverywhere}
        onClose={() => setEverywhere(false)}
      />
      <SudoDialog
        open={sudoOpen}
        onClose={() => setSudoOpen(false)}
        onConfirmed={() => {
          setSudoOpen(false);
          void newCodes();
        }}
      />
      <Modal open={codes !== null} onClose={() => setCodes(null)} title="New recovery codes" width="sm">
        {codes && <RecoveryCodes codes={codes} />}
      </Modal>
    </Page>
  );
};

export default AdminSecurity;
