import { useEffect, useState, type FormEvent } from 'react';
import { ExternalLink, KeyRound, Plus, Terminal, Trash2 } from 'lucide-react';
import { getErrorMessage } from '../../api/client';
import { createToken, listTokens, revokeToken } from '../../api/tokens';
import type { ApiToken, ApiTokenCreated } from '../../api/types';
import { CLI_DOCS_URL, claudeCodeSnippet, customSite, envSnippet, loginSnippet, mcpJsonSnippet } from '../../lib/cli';
import { formatDateShort } from '../../lib/format';
import { Button, Card, ConfirmDialog, ErrorBox, Modal, Progress, SectionLabel, Segmented, Spinner, Tag, useToast } from '../ui';
import { CopyBlock } from './CopyBlock';
import { money, timeAgo } from './helpers';
import { tokenRequest, type TokenOptions } from './tokenOptions';
import { TokenOptionsFields } from './TokenOptionsFields';

type SetupTab = 'terminal' | 'claude' | 'json';

const SETUP_TABS = [
  { value: 'terminal' as const, label: 'Terminal' },
  { value: 'claude' as const, label: 'Claude Code' },
  { value: 'json' as const, label: 'MCP config' },
];

const FRESH: TokenOptions = { name: '', expiry: '90', limit: '' };

/** Spent / limit line of a token. */
const Budget = ({ token }: { token: ApiToken }) => {
  const limit = token.spend_limit_usd;
  if (limit === null) return <div className="mt-1 text-xs text-muted">Spent {money(token.spent_usd)} · no spending limit</div>;
  if (limit === 0) return <div className="mt-1 text-xs text-muted">Free models only</div>;
  const share = token.spent_usd / limit;
  return (
    <div className="mt-2 max-w-[300px]">
      <div className="flex justify-between font-mono text-[11px] text-muted">
        <span>spent {money(token.spent_usd)}</span>
        <span>limit {money(limit)}</span>
      </div>
      <Progress value={share} color={share >= 0.9 ? '#FF7A66' : '#D9FF3D'} className="mt-1" />
    </div>
  );
};

const TokenRow = ({ token, onRevoke }: { token: ApiToken; onRevoke: () => void }) => {
  const used = token.last_used_at ? `last used ${timeAgo(token.last_used_at)}` : 'never used';
  const expiry = token.expires_at ? `${token.expired ? 'expired' : 'expires'} ${formatDateShort(token.expires_at)}` : 'never expires';
  return (
    <li className="flex items-start gap-3 py-3.5">
      <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-surface-2 text-muted">
        <KeyRound className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <span className="font-semibold text-text break-words">{token.name}</span>
          <span className="font-mono text-xs text-dim">{token.token_hint}</span>
          {token.expired && <Tag className="text-con!">expired</Tag>}
        </div>
        <div className="mt-1 text-xs text-muted">
          Created {formatDateShort(token.created_at)} · {used} · {expiry}
        </div>
        <Budget token={token} />
      </div>
      <Button variant="danger" size="sm" onClick={onRevoke} aria-label={`Revoke ${token.name}`} icon={<Trash2 className="size-3.5" />}>
        <span className="hidden sm:inline">Revoke</span>
      </Button>
    </li>
  );
};

/** The new token, shown once, with ready-to-paste setups. */
const CreatedToken = ({ token }: { token: ApiTokenCreated }) => {
  const [tab, setTab] = useState<SetupTab>('terminal');
  const site = customSite();
  const snippet =
    tab === 'terminal' ? envSnippet(token.token, site) : tab === 'claude' ? claudeCodeSnippet(token.token, site) : mcpJsonSnippet(token.token, site);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <p className="text-sm text-text-3">
          Copy it now: for your security it is shown only once. Anyone with this token can run debates on your account
          {token.spend_limit_usd !== null ? ` and spend up to ${money(token.spend_limit_usd)} of your credits` : ' and spend your credits'}.
        </p>
        <CopyBlock text={token.token} label="Copy token" className="mt-3" />
      </div>
      <div>
        <Segmented size="sm" options={SETUP_TABS} value={tab} onChange={setTab} />
        <CopyBlock text={snippet} label="Copy snippet" className="mt-2.5" />
        <p className="mt-2 text-xs text-dim">
          {tab === 'terminal'
            ? 'For scripts and CI. On your own computer `debatr login` is simpler: it approves the device in the browser.'
            : tab === 'claude'
              ? 'Adds Debatr as a tool for Claude Code in every project.'
              : 'For Claude Desktop, Cursor, Windsurf and other MCP clients: merge it into their mcpServers config.'}
        </p>
      </div>
    </div>
  );
};

/** "API TOKENS": tokens for the `debatr` CLI, scripts and AI agents (MCP). */
export const ApiTokensCard = ({ className = '' }: { className?: string }) => {
  const toast = useToast();
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [creating, setCreating] = useState(false);
  const [options, setOptions] = useState<TokenOptions>(FRESH);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);
  const [revoking, setRevoking] = useState<ApiToken | null>(null);

  useEffect(() => {
    let cancelled = false;
    listTokens()
      .then((rows) => {
        if (cancelled) return;
        setTokens(rows);
        setLoadError(null);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const openCreate = () => {
    setOptions(FRESH);
    setFormError(null);
    setCreated(null);
    setCreating(true);
  };

  const closeCreate = () => {
    setCreating(false);
    setCreated(null); // the secret leaves memory with the dialog
  };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const request = tokenRequest(options);
    if (request.error !== undefined) {
      setFormError(request.error);
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      setCreated(await createToken(request.body));
      setReload((n) => n + 1);
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!revoking) return;
    setBusy(true);
    try {
      await revokeToken(revoking.id);
      toast.success(`“${revoking.name}” revoked`);
      setRevoking(null);
      setReload((n) => n + 1);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className={className}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionLabel>API tokens</SectionLabel>
        <Button size="sm" variant="secondary" onClick={openCreate} icon={<Plus className="size-4" />}>
          New token
        </Button>
      </div>
      <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-muted">
        Run debates from the terminal with the <span className="font-mono text-text-3">debatr</span> CLI, or let AI agents such as Claude use Debatr as a tool
        over MCP. A token acts as you, except for your password, keys and payments; give agents a spending limit.{' '}
        <a href={CLI_DOCS_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-accent hover:text-accent-hover">
          Docs <ExternalLink className="size-3" />
        </a>
      </p>

      {loadError ? (
        <ErrorBox className="mt-3">{loadError}</ErrorBox>
      ) : tokens === null ? (
        <div className="mt-3 flex items-center gap-2 py-6 text-xs text-muted">
          <Spinner className="size-4" /> Loading tokens…
        </div>
      ) : tokens.length === 0 ? (
        <div className="mt-4 grid gap-3 rounded-field border border-dashed border-line-2 p-4 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-center">
          <div className="grid size-10 place-items-center rounded-xl bg-surface-2 text-muted">
            <Terminal className="size-5" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-text-2">No tokens yet. On your computer, install the CLI and sign in:</div>
            <CopyBlock text={loginSnippet(customSite())} label="Copy commands" className="mt-2" />
          </div>
        </div>
      ) : (
        <ul className="mt-2 divide-y divide-line">
          {tokens.map((t) => (
            <TokenRow key={t.id} token={t} onRevoke={() => setRevoking(t)} />
          ))}
        </ul>
      )}

      <Modal
        open={creating}
        onClose={closeCreate}
        title={created ? 'Your new token' : 'New API token'}
        footer={
          created ? (
            <Button onClick={closeCreate}>Done</Button>
          ) : (
            <>
              <Button variant="secondary" onClick={closeCreate} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" form="new-api-token" loading={busy}>
                Create token
              </Button>
            </>
          )
        }
      >
        {created ? (
          <CreatedToken token={created} />
        ) : (
          <form id="new-api-token" onSubmit={submit} noValidate className="grid gap-4">
            <TokenOptionsFields value={options} onChange={setOptions} />
            {formError && <ErrorBox>{formError}</ErrorBox>}
          </form>
        )}
      </Modal>

      <ConfirmDialog
        open={revoking !== null}
        title={`Revoke “${revoking?.name ?? ''}”?`}
        body="Everything that uses this token (the CLI, scripts, AI agents) loses access at once. Debates it started stay in your library."
        confirmLabel="Revoke token"
        danger
        busy={busy}
        onConfirm={revoke}
        onClose={() => setRevoking(null)}
      />
    </Card>
  );
};
