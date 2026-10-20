import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { createDebate, getDebate, startDraft, updateDraft } from '../api/debates';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { Button, ErrorBox, PageLoader, useToast } from '../components/ui';
import { StepLaunch } from '../components/create/StepLaunch';
import { StepSpeakers } from '../components/create/StepSpeakers';
import { StepTopic } from '../components/create/StepTopic';
import { WizardProgress } from '../components/create/WizardProgress';
import {
  applyFormat,
  buildConfig,
  clearWizardState,
  configFromDebate,
  countDebaters,
  initialState,
  LAST_STEP,
  loadWizardState,
  maxReachableStep,
  pickDefaultModel,
  resolveVoices,
  saveWizardState,
  speakerNamesOf,
  stateFromConfig,
  stepValid,
  withinFreeLimits,
  type WizardState,
  type WizardStep,
} from '../components/create/wizardState';
import { useBillingConfig } from '../hooks/useBillingConfig';
import { estimateCost, useEstimate } from '../hooks/useEstimate';
import { useModels } from '../hooks/useModels';
import { useSiteStatus } from '../hooks/useSiteStatus';
import { useVoices } from '../hooks/useVoices';
import { useLocalKey } from '../lib/localKeys';
import { ttsKeyUsable, useElevenLabsKeyStatus } from '../hooks/useElevenLabsKeyStatus';
import { formatCost, formatMinutes } from '../lib/format';
import { FORMAT_IDS, FORMATS, formatSpec, type FormatSpec } from '../lib/formats';
import type { FormatId } from '../api/types';

/**
 * Three-step wizard: topic (trending news or your own, format) → speakers (models, voices,
 * personas; named after their models) → review (outputs, scenes, estimate, start).
 * `?draft=<id>` edits a saved draft, `?remix=<id>` starts a new debate prefilled from an existing one.
 */
const CreateDebate = () => {
  const navigate = useNavigate();
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const draftId = searchParams.get('draft');
  const remixId = draftId ? null : searchParams.get('remix');
  // `?format=rap_battle` (links from the gallery and the ranking) opens the wizard on that format.
  const formatParam = draftId || remixId ? null : searchParams.get('format');
  const { user, refresh } = useAuth();
  const { models, loading: modelsLoading, error: modelsError } = useModels();
  const { config: billing, loaded: billingLoaded } = useBillingConfig();
  const openrouterKey = useLocalKey('openrouter');
  const storedTtsKey = useLocalKey('elevenlabs');
  const ttsKeyCheck = useElevenLabsKeyStatus(storedTtsKey);
  const credits = user?.credits_usd ?? 0;
  // A key ElevenLabs rejected neither unlocks premium voices nor goes to the audio build; a key
  // on the free plan stays out of a rap battle's (no Music API there: credits pay our key).
  const keyFor = (spec: FormatSpec) => (ttsKeyUsable(ttsKeyCheck, spec.music) ? storedTtsKey : '');
  // A format voiced with premium voices only (rap battle) needs a key of one's own or a balance.
  const formatLock = (spec: FormatSpec): string | null => {
    if (!spec.premiumOnly || keyFor(spec) || !billingLoaded) return null;
    const plan = spec.music ? ' on a paid plan' : '';
    if (!billing.elevenlabs_available) return `${spec.name}s need premium voices, which are unavailable on this server right now: add your own ElevenLabs key${plan} in Account.`;
    if (credits > 0) return null;
    if (ttsKeyUsable(ttsKeyCheck) && spec.music)
      return `Your ElevenLabs key is on the free plan, which makes no music: top up credits to run ${spec.name.toLowerCase()}s on our key, or upgrade the key.`;
    return `${spec.name}s are voiced by ElevenLabs and paid from your balance: top up credits, or add your own ElevenLabs key${plan} in Account.`;
  };
  const formatLocks = Object.fromEntries(FORMAT_IDS.flatMap((id) => (formatLock(FORMATS[id]) ? [[id, formatLock(FORMATS[id])]] : []))) as Partial<Record<FormatId, string>>;

  const [state, setState] = useState<WizardState>(() => {
    if (draftId) return initialState();
    const stored = loadWizardState();
    return formatParam && (FORMAT_IDS as string[]).includes(formatParam) ? applyFormat({ ...stored, step: 1 }, formatParam as FormatId) : stored;
  });
  const [draftLoaded, setDraftLoaded] = useState<string | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [remixError, setRemixError] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  const [starting, setStarting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // Re-open a draft in the wizard.
  useEffect(() => {
    if (!draftId) return;
    let cancelled = false;
    getDebate(draftId)
      .then((d) => {
        if (cancelled) return;
        if (d.status !== 'draft') {
          setDraftError('This debate is no longer a draft.');
          return;
        }
        if (!d.config) {
          setDraftError('This draft cannot be opened.');
          return;
        }
        setState(stateFromConfig(d.config, initialState()));
        setDraftLoaded(draftId);
      })
      .catch((err: unknown) => {
        if (!cancelled) setDraftError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [draftId]);

  // Remix: replace the in-progress wizard with a copy of the debate, then drop the query param.
  useEffect(() => {
    if (!remixId) return;
    let cancelled = false;
    getDebate(remixId)
      .then((d) => {
        if (cancelled) return;
        setState({ ...stateFromConfig(configFromDebate(d), initialState()), remix: { id: d.id, topic: d.settings.topic || d.title || '' } });
        toast.info('Prefilled from the debate — tweak anything you like');
        navigate('/create', { replace: true });
      })
      .catch((err: unknown) => {
        if (!cancelled) setRemixError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [remixId, navigate, toast]);

  // The format was applied when the state was made: drop the parameter from the address.
  useEffect(() => {
    if (formatParam) navigate('/create', { replace: true });
  }, [formatParam, navigate]);

  // The in-progress wizard survives reloads (drafts live on the server instead). While a remix
  // loads, keep the stored state untouched in case it fails.
  useEffect(() => {
    if (!draftId && !remixId) saveWizardState(state);
  }, [state, draftId, remixId]);

  const patch = (changes: Partial<WizardState>) => setState((s) => ({ ...s, ...changes }));
  const setFormat = (format: FormatId) => setState((s) => applyFormat(s, format));

  const spec = formatSpec(state.format);
  const elevenlabsKey = keyFor(spec);
  const debaters = countDebaters(state.speakers);
  // Premium voices on the system key are paid from credits: an empty balance locks
  // them unless the user brings an own ElevenLabs key.
  const premiumLocked = !elevenlabsKey && credits <= 0;
  const premiumUsable = elevenlabsKey.length > 0 || (billing.elevenlabs_available && !premiumLocked);
  // A premium-only format always asks for ElevenLabs (its lock says why it cannot run).
  const provider = spec.premiumOnly ? 'elevenlabs' : state.provider === 'elevenlabs' && !premiumUsable ? 'edge' : state.provider;
  const catalogue = useVoices(provider, state.language, debaters, state.step >= 2, provider === 'elevenlabs' ? elevenlabsKey : '', state.format);
  // Without a catalogue the server picks the voices (the Speakers step says so).
  const resolvedVoices = catalogue.error ? {} : resolveVoices(state, catalogue.voices, catalogue.defaults);

  const defaultModelId = pickDefaultModel(models);
  const validation = { defaultModelId, modelsLoading };
  const ownKey = openrouterKey.length > 0 || Boolean(user?.openrouter_key_masked);
  const paidLocked = !ownKey && (user?.credits_usd ?? 0) <= 0;
  // Without credits or an own key every model is free, so the limits of free debates apply:
  // rounds and reply length are shown and sent within them (the choice stays in the state).
  const site = useSiteStatus();
  const free = paidLocked ? site.free_debates : null;
  const limited = withinFreeLimits(state, free);
  // Locked options (no balance) are sent as off even if the stored wizard state has them on.
  const effective: WizardState = {
    ...limited,
    images: state.images === 'ai' && credits <= 0 ? 'off' : state.images,
    fact_check: state.fact_check && !paidLocked,
  };
  const config = buildConfig(effective, { defaultModelId, models, voices: resolvedVoices, provider, openrouterKey, elevenlabsKey });
  const names = speakerNamesOf(state.speakers, models, defaultModelId, spec.id);
  // Drafts are stored on the server: never send the browser keys along with them.
  const draftConfig = { ...config, user_provider_key: undefined, user_tts_key: undefined };
  const ready = !modelsLoading && config.participants.every((p) => p.model_id.length > 0);
  const maxStep = maxReachableStep(state, validation);
  // Step 1 shows a one-line estimate, step 3 the full one; the topic step needs no voices.
  // Before a topic is chosen the estimate uses a stand-in: the topic barely changes it.
  const estimate = useEstimate(config.topic ? config : { ...config, topic: 'Topic' }, ready, credits);
  const shownCost = estimate.shown ? estimateCost(estimate.shown) : null;
  const estimateLine = estimate.shown
    ? `~${formatMinutes(estimate.shown.duration_ms)} episode · ${shownCost ? `~${formatCost(shownCost)} estimated` : 'free with these models'}`
    : null;

  const goTo = (step: WizardStep) => {
    setShowErrors(false);
    setState((s) => ({ ...s, step }));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  const next = () => {
    if (!stepValid(state, state.step, validation)) {
      setShowErrors(true);
      return;
    }
    goTo(Math.min(LAST_STEP, state.step + 1) as WizardStep);
  };
  const prev = () => goTo(Math.max(1, state.step - 1) as WizardStep);

  const start = async () => {
    setStarting(true);
    setStartError(null);
    try {
      let debateId: string;
      if (draftLoaded) {
        await updateDraft(draftLoaded, draftConfig);
        debateId = (await startDraft(draftLoaded, { user_provider_key: config.user_provider_key, user_tts_key: config.user_tts_key })).debate_id;
      } else {
        debateId = (await createDebate(config)).debate_id;
        clearWizardState();
      }
      toast.success('The debate is on its way');
      void refresh();
      navigate(`/debate/${debateId}`);
    } catch (err) {
      const message = getErrorMessage(err);
      setStartError(message);
      if (getErrorStatus(err) !== 402) toast.error(message);
    } finally {
      setStarting(false);
    }
  };

  const saveDraft = async () => {
    if (!state.topic.trim()) {
      navigate('/library');
      return;
    }
    if (!ready) {
      toast.info('Still loading the model list, try again in a second');
      return;
    }
    setSaving(true);
    try {
      if (draftLoaded) await updateDraft(draftLoaded, { ...draftConfig, draft: true });
      else {
        await createDebate({ ...draftConfig, draft: true });
        clearWizardState();
      }
      toast.success('Draft saved');
      navigate('/library');
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (remixId && !remixError) {
    return (
      <Page>
        <PageLoader label="Copying the debate…" />
      </Page>
    );
  }
  if (draftId && !draftLoaded && !draftError) {
    return (
      <Page>
        <PageLoader label="Opening the draft…" />
      </Page>
    );
  }

  return (
    <Page>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-[clamp(26px,3vw,38px)] font-extrabold tracking-[-0.03em]">{draftLoaded ? 'Edit draft' : `New ${spec.show}`}</h1>
        <button type="button" onClick={saveDraft} disabled={saving || starting} className="text-[13px] text-muted hover:text-text cursor-pointer disabled:opacity-50">
          {saving ? 'Saving…' : 'Save draft & exit'}
        </button>
      </div>
      {draftError && <ErrorBox className="mt-4">{draftError}</ErrorBox>}
      {remixError && <ErrorBox className="mt-4">Could not copy that debate: {remixError}</ErrorBox>}

      <WizardProgress step={state.step} maxStep={maxStep} onSelect={goTo} />

      {state.step === 1 && (
        <StepTopic state={limited} free={free} patch={patch} onFormat={setFormat} formatLocks={formatLocks} showErrors={showErrors} estimateLine={estimateLine} onContinue={next} />
      )}
      {state.step === 2 && (
        <StepSpeakers
          state={state}
          patch={patch}
          models={models}
          modelsLoading={modelsLoading}
          modelsError={modelsError}
          defaultModelId={defaultModelId}
          catalogue={catalogue}
          resolvedVoices={resolvedVoices}
          provider={provider}
          billing={billing}
          hasTtsKey={elevenlabsKey.length > 0}
          ttsKeyError={ttsKeyCheck.status === 'invalid' ? ttsKeyCheck.error : null}
          premiumLocked={premiumLocked}
          formatLock={formatLocks[state.format] ?? null}
          freePlanKey={spec.music && ttsKeyUsable(ttsKeyCheck) && !elevenlabsKey}
          paidLocked={paidLocked}
          free={free}
          showErrors={showErrors}
        />
      )}
      {state.step === 3 && (
        <StepLaunch
          state={limited}
          patch={patch}
          config={config}
          ready={ready}
          names={names}
          voices={catalogue.voices}
          estimate={estimate}
          ownKey={ownKey}
          paymentsMode={billing.payments_mode}
          accountKeyMasked={user?.openrouter_key_masked ?? null}
          openrouterKey={openrouterKey}
          ttsKeyCheck={ttsKeyCheck}
          formatLock={formatLocks[state.format] ?? null}
          aiImagesLocked={credits <= 0}
          factCheckLocked={paidLocked}
          starting={starting}
          startError={startError}
          onStart={start}
          goTo={goTo}
        />
      )}

      {state.step === 2 && (
        <div className="mt-[26px] flex items-center justify-between gap-3">
          <Button variant="secondary" onClick={prev} icon={<ArrowLeft className="size-4" />}>
            Back
          </Button>
          <Button variant="light" onClick={next}>
            Continue <ArrowRight className="size-4" />
          </Button>
        </div>
      )}
    </Page>
  );
};

export default CreateDebate;
