import { Play, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getErrorMessage, getErrorStatus } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { deleteMedia, generateMedia, getMediaCapabilities, getVoices } from '../../api/media';
import type { DebateDetail, DebateMedia, ImageSource, MediaCapabilities, TTSProviderName, VoiceInfo } from '../../api/types';
import { useBillingConfig } from '../../hooks/useBillingConfig';
import { ttsKeyUsable, useElevenLabsKeyStatus } from '../../hooks/useElevenLabsKeyStatus';
import { formatCost } from '../../lib/format';
import { setLocalKey, useLocalKey } from '../../lib/localKeys';
import { Button, ConfirmDialog, ErrorBox, Hint, Input, Label, Modal, Select, useToast } from '../ui';

const MODEL_LABELS: Record<string, string> = {
  eleven_v3: 'eleven_v3 — most expressive, understands [emotion] tags',
  eleven_multilingual_v2: 'eleven_multilingual_v2 — stable, no tags',
  eleven_flash_v2_5: 'eleven_flash_v2_5 — cheap draft',
};

interface Props {
  open: boolean;
  onClose: () => void;
  debate: DebateDetail;
  media: DebateMedia | null;
  onQueued: () => void;
}

interface SpeakerRow {
  id: string;
  name: string;
}

/** Choose the voice engine and a voice per speaker, then queue the audio build. */
export const RegenerateAudioDialog = ({ open, onClose, debate, media, onQueued }: Props) => {
  const toast = useToast();
  const { config: billing } = useBillingConfig();
  const { user } = useAuth();
  const [caps, setCaps] = useState<MediaCapabilities | null>(null);
  const [providerChoice, setProviderChoice] = useState<TTSProviderName | null>(null);
  const [modelChoice, setModelChoice] = useState<string | null>(null);
  // The key saved in this browser is used by default; typing replaces it for this build only.
  const storedKey = useLocalKey('elevenlabs');
  const [keyDraft, setKeyDraft] = useState<string | null>(null);
  const [rememberKey, setRememberKey] = useState(true);
  const ttsKey = keyDraft ?? storedKey;
  const keyChanged = ttsKey.length > 0 && ttsKey !== storedKey;
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [voicesError, setVoicesError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [force, setForce] = useState(false);
  const [visualsChoice, setVisualsChoice] = useState<boolean | null>(null);
  const [imagesChoice, setImagesChoice] = useState<ImageSource | null>(null);
  const [submitError, setSubmitError] = useState<{ status: number | null; message: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getMediaCapabilities()
      .then((c) => {
        if (!cancelled) setCaps(c);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open]);

  const plannedProvider = debate.media_plan?.provider;
  const provider: TTSProviderName = providerChoice ?? media?.options?.provider ?? (plannedProvider === 'elevenlabs' && caps?.elevenlabs ? 'elevenlabs' : caps?.default_provider ?? 'edge');
  const modelId = modelChoice ?? media?.options?.model_id ?? debate.media_plan?.model_id ?? caps?.default_model_id ?? 'eleven_v3';
  const rows = useMemo<SpeakerRow[]>(
    () => [...debate.participants.map((p, i) => ({ id: p.id || `participant_${i}`, name: p.name ?? `Speaker ${i + 1}` })), { id: 'judge', name: 'Judge (verdict)' }],
    [debate.participants],
  );
  // Only a key ElevenLabs accepts unlocks premium voices (typed keys are checked after a pause).
  const keyCheck = useElevenLabsKeyStatus(open && provider === 'elevenlabs' ? ttsKey : '', 500);
  const keyRejected = keyCheck.status === 'invalid';
  const ownKeyUsable = ttsKeyUsable(keyCheck);
  const keyMissing = provider === 'elevenlabs' && !caps?.elevenlabs && !ownKeyUsable;
  // Empty balance: the system key is locked, only an own key unlocks premium voices.
  const noCredits = (user?.credits_usd ?? 0) <= 0;
  const creditsMissing = provider === 'elevenlabs' && Boolean(caps?.elevenlabs) && !ownKeyUsable && noCredits;
  const voicesKey = provider === 'elevenlabs' ? ttsKey : '';
  const savedVoices = media?.options?.provider === provider ? media.options.voices : debate.media_plan?.provider === provider ? debate.media_plan.voices : {};
  const savedKey = JSON.stringify(savedVoices);

  useEffect(() => {
    if (!open || keyMissing || keyRejected) return;
    let cancelled = false;
    getVoices(provider, { debateId: debate.id }, voicesKey || undefined)
      .then((r) => {
        if (cancelled) return;
        const saved = JSON.parse(savedKey) as Record<string, string>;
        setVoicesError(null);
        setVoices(r.voices);
        setChosen((prev) => {
          const next: Record<string, string> = {};
          for (const [id, voice] of Object.entries(r.defaults)) {
            const keep = prev[id] && r.voices.some((v) => v.id === prev[id]) ? prev[id] : saved[id] && r.voices.some((v) => v.id === saved[id]) ? saved[id] : voice;
            next[id] = keep;
          }
          return next;
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) setVoicesError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [open, provider, debate.id, voicesKey, keyMissing, keyRejected, savedKey]);

  const visuals = visualsChoice ?? media?.options?.visuals ?? debate.media_plan?.visuals ?? true;
  const storedImages = imagesChoice ?? media?.options?.images ?? debate.media_plan?.images ?? 'off';
  // AI pictures are paid from the balance; without credits they fall back to free photos.
  const images: ImageSource = storedImages === 'ai' && noCredits ? 'stock' : storedImages;
  const chars = debate.turns.reduce((acc, t) => acc + (t.error ? 0 : t.text.length), 0);
  const premiumCost = (chars / 1000) * billing.tts_price_per_1k_chars;

  const submit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const userKey = provider === 'elevenlabs' ? ttsKey || undefined : undefined;
      await generateMedia(debate.id, { provider, model_id: provider === 'elevenlabs' ? modelId : 'edge', voices: chosen, visuals, images: visuals ? images : 'off', force, user_tts_key: userKey });
      if (userKey && keyChanged && rememberKey) setLocalKey('elevenlabs', userKey);
      toast.success('Audio build queued');
      onQueued();
      onClose();
    } catch (err) {
      setSubmitError({ status: getErrorStatus(err), message: getErrorMessage(err) });
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async () => {
    setDeleting(true);
    try {
      await deleteMedia(debate.id);
      toast.info('Audio deleted');
      setConfirmDelete(false);
      onQueued();
      onClose();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  const preview = (voice: VoiceInfo | undefined) => {
    if (!voice?.preview_url) return;
    void new Audio(voice.preview_url).play();
  };

  const ready = media?.media_status === 'ready';

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={ready ? 'Regenerate audio' : 'Generate audio'}
        width="lg"
        footer={
          <>
            {ready && (
              <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)} icon={<Trash2 className="size-3.5" />} className="mr-auto">
                Delete audio
              </Button>
            )}
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={submit} loading={submitting} disabled={keyMissing || creditsMissing || keyRejected || keyCheck.status === 'checking' || voices.length === 0}>
              {ready ? 'Regenerate' : 'Generate'}
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label>Voice engine</Label>
              <Select value={provider} onChange={(e) => setProviderChoice(e.target.value as TTSProviderName)} className="mt-1.5">
                <option value="edge">Edge neural — free</option>
                <option value="elevenlabs">
                  Premium neural (ElevenLabs){caps && !caps.elevenlabs ? ' — needs your key' : !ownKeyUsable && noCredits ? ' — needs credits or your key' : ''}
                </option>
              </Select>
            </div>
            {provider === 'elevenlabs' && (
              <div>
                <Label>Model</Label>
                <Select value={modelId} onChange={(e) => setModelChoice(e.target.value)} className="mt-1.5">
                  {(caps?.elevenlabs_models ?? Object.keys(MODEL_LABELS)).map((m) => (
                    <option key={m} value={m}>
                      {MODEL_LABELS[m] ?? m}
                    </option>
                  ))}
                </Select>
              </div>
            )}
          </div>
          {provider === 'elevenlabs' && (
            <div>
              <Label hint={caps?.elevenlabs && !noCredits ? '(optional — otherwise billed to credits)' : '(required)'}>Your ElevenLabs key</Label>
              <Input type="password" value={ttsKey} onChange={(e) => setKeyDraft(e.target.value.trim())} placeholder="sk_…" autoComplete="off" spellCheck={false} maxLength={200} className="mt-1.5 font-mono" />
              {keyChanged ? (
                <label className="mt-2 flex items-center gap-2 text-xs text-muted">
                  <input type="checkbox" checked={rememberKey} onChange={(e) => setRememberKey(e.target.checked)} /> Remember in this browser (never stored on our servers)
                </label>
              ) : (
                storedKey &&
                ttsKey === storedKey && (
                  <Hint>
                    Using the key saved in this browser{caps?.elevenlabs ? ' — clear the field to pay with credits instead' : ''}.{' '}
                    <Link to="/account" className="text-accent hover:text-accent-hover">
                      Manage keys
                    </Link>
                  </Hint>
                )
              )}
              {keyRejected && (
                <Hint tone="danger">
                  ElevenLabs rejected this key: {keyCheck.error}.{caps?.elevenlabs && !noCredits ? ' Fix it or clear the field to pay with credits.' : ''}
                </Hint>
              )}
              {creditsMissing && !keyRejected && (
                <Hint>
                  Premium voices on our key are paid from your balance.{' '}
                  <Link to="/account" className="font-semibold text-accent hover:text-accent-hover">
                    Top up credits
                  </Link>{' '}
                  to unlock them, enter your own key or switch to the free Edge voices.
                </Hint>
              )}
              {keyMissing && !keyRejected && (
                <Hint tone="danger">
                  {caps?.elevenlabs_error ? `Premium voices are unavailable on this server: ${caps.elevenlabs_error}.` : 'No premium key is configured on this server.'} Enter your own key or switch to the free Edge voices.
                </Hint>
              )}
            </div>
          )}
          {voicesError && !keyRejected && <ErrorBox>{voicesError}</ErrorBox>}
          {!keyMissing && (
            <div className="grid gap-2 sm:grid-cols-2">
              {rows.map((row) => {
                const voice = voices.find((v) => v.id === chosen[row.id]);
                return (
                  <div key={row.id} className="flex items-center gap-2">
                    <span className="w-28 shrink-0 truncate text-sm font-medium" title={row.name}>
                      {row.name}
                    </span>
                    <Select value={chosen[row.id] ?? ''} onChange={(e) => setChosen({ ...chosen, [row.id]: e.target.value })} disabled={voices.length === 0} className="min-w-0 flex-1 !py-2 text-[13px]">
                      {voices.length === 0 && <option value="">loading voices…</option>}
                      {voices.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name}
                          {v.description ? ` — ${v.description}` : ''}
                        </option>
                      ))}
                    </Select>
                    <button type="button" onClick={() => preview(voice)} disabled={!voice?.preview_url} title="Voice sample" className="grid size-9 shrink-0 place-items-center rounded-[10px] border border-line-2 bg-surface-2 text-text disabled:opacity-40 cursor-pointer">
                      <Play className="size-3 fill-current" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
            <span>
              ~{chars.toLocaleString()} characters ·{' '}
              {provider === 'elevenlabs' ? (ttsKey ? 'billed to your ElevenLabs account' : `≈ ${formatCost(premiumCost)} in credits`) : 'free'}
            </span>
            <label className="flex items-center gap-2" title="Charts, numbers and hand-drawn schemes synced with the speech">
              <input type="checkbox" checked={visuals} onChange={(e) => setVisualsChoice(e.target.checked)} /> visual scenes
            </label>
            {visuals && (
              <label className="flex items-center gap-2" title="Pictures among the scenes: free photos from Wikimedia Commons, or AI images paid from your balance (about $0.01 each)">
                pictures
                <select value={images} onChange={(e) => setImagesChoice(e.target.value as ImageSource)} className="rounded-md border border-line-2 bg-ink px-1.5 py-1 text-xs text-text">
                  <option value="off">none</option>
                  <option value="stock">free photos</option>
                  <option value="ai" disabled={noCredits}>
                    AI images{noCredits ? ' (needs credits)' : ''}
                  </option>
                </select>
              </label>
            )}
            {ready && (
              <label className="flex items-center gap-2" title="Re-voice every turn and design the scenes again">
                <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> ignore cached turns
              </label>
            )}
          </div>
          {submitError && (
            <ErrorBox>
              {submitError.message}
              {submitError.status === 402 && (
                <div className="mt-2">
                  <Link to="/account" className="font-semibold text-accent hover:text-accent-hover">
                    Top up credits →
                  </Link>
                </div>
              )}
            </ErrorBox>
          )}
        </div>
      </Modal>
      <ConfirmDialog open={confirmDelete} title="Delete the generated audio?" body="The mixed track, the timeline and the cached turns are removed. You can generate them again later." confirmLabel="Delete audio" danger busy={deleting} onConfirm={remove} onClose={() => setConfirmDelete(false)} />
    </>
  );
};
