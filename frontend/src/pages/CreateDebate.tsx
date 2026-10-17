import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { createDebate, getDebate, startDraft, updateDraft } from '../api/debates';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { Button, ErrorBox, PageLoader, useToast } from '../components/ui';
import { StepFormat } from '../components/create/StepFormat';
import { StepReview } from '../components/create/StepReview';
import { StepSpeakers } from '../components/create/StepSpeakers';
import { StepTopic } from '../components/create/StepTopic';
import { WizardProgress } from '../components/create/WizardProgress';
import {
  buildConfig,
  clearWizardState,
  configFromDebate,
  countDebaters,
  initialState,
  loadWizardState,
  maxReachableStep,
  pickDefaultModel,
  resolveVoices,
  saveWizardState,
  stateFromConfig,
  stepValid,
  type WizardState,
  type WizardStep,
} from '../components/create/wizardState';
import { useBillingConfig } from '../hooks/useBillingConfig';
import { useModels } from '../hooks/useModels';
import { useVoices } from '../hooks/useVoices';
import { useLocalKey } from '../lib/localKeys';
import { ttsKeyUsable, useElevenLabsKeyStatus } from '../hooks/useElevenLabsKeyStatus';

/**
 * Four-step wizard: topic → speakers (models, voice engine, voices) → format → review. `?draft=<id>` edits a saved draft,
 * `?remix=<id>` starts a new debate prefilled from an existing one.
 */
const CreateDebate = () => {
  const navigate = useNavigate();
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const draftId = searchParams.get('draft');
  const remixId = draftId ? null : searchParams.get('remix');
  const { user, refresh } = useAuth();
  const { models, loading: modelsLoading, error: modelsError } = useModels();
  const { config: billing } = useBillingConfig();
  const openrouterKey = useLocalKey('openrouter');
  const storedTtsKey = useLocalKey('elevenlabs');
  const ttsKeyCheck = useElevenLabsKeyStatus(storedTtsKey);
  // A key ElevenLabs rejected neither unlocks premium voices nor goes to the audio build.
  const elevenlabsKey = ttsKeyUsable(ttsKeyCheck) ? storedTtsKey : '';

  const [state, setState] = useState<WizardState>(() => (draftId ? initialState() : loadWizardState()));
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
        setState(stateFromConfig(configFromDebate(d), initialState()));
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

  // The in-progress wizard survives reloads (drafts live on the server instead). While a remix
  // loads, keep the stored state untouched in case it fails.
  useEffect(() => {
    if (!draftId && !remixId) saveWizardState(state);
  }, [state, draftId, remixId]);

  const patch = (changes: Partial<WizardState>) => setState((s) => ({ ...s, ...changes }));

  const debaters = countDebaters(state.speakers);
  // Premium voices on the system key are paid from credits: an empty balance locks
  // them unless the user brings an own ElevenLabs key.
  const premiumLocked = !elevenlabsKey && (user?.credits_usd ?? 0) <= 0;
  const premiumUsable = elevenlabsKey.length > 0 || (billing.elevenlabs_available && !premiumLocked);
  const provider = state.provider === 'elevenlabs' && !premiumUsable ? 'edge' : state.provider;
  const catalogue = useVoices(provider, state.language, debaters, state.step >= 2, provider === 'elevenlabs' ? elevenlabsKey : '');
  // Without a catalogue the server picks the voices (the Speakers step says so).
  const resolvedVoices = catalogue.error ? {} : resolveVoices(state, catalogue.voices, catalogue.defaults);

  const defaultModelId = pickDefaultModel(models);
  const validation = { defaultModelId, modelsLoading };
  const ownKey = openrouterKey.length > 0 || Boolean(user?.openrouter_key_masked);
  const paidLocked = !ownKey && (user?.credits_usd ?? 0) <= 0;
  // Locked options (no balance) are sent as off even if the stored wizard state has them on.
  const effective: WizardState = {
    ...state,
    images: state.images === 'ai' && (user?.credits_usd ?? 0) <= 0 ? 'off' : state.images,
    fact_check: state.fact_check && !paidLocked,
  };
  const config = buildConfig(effective, { defaultModelId, voices: resolvedVoices, provider, openrouterKey, elevenlabsKey });
  // Drafts are stored on the server: never send the browser keys along with them.
  const draftConfig = { ...config, user_provider_key: undefined, user_tts_key: undefined };
  const ready = !modelsLoading && config.participants.every((p) => p.model_id.length > 0);
  const maxStep = maxReachableStep(state, validation);

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
    goTo(Math.min(4, state.step + 1) as WizardStep);
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
        <h1 className="font-display text-[clamp(26px,3vw,38px)] font-extrabold tracking-[-0.03em]">{draftLoaded ? 'Edit draft' : 'New debate'}</h1>
        <button type="button" onClick={saveDraft} disabled={saving || starting} className="text-[13px] text-muted hover:text-text cursor-pointer disabled:opacity-50">
          {saving ? 'Saving…' : 'Save draft & exit'}
        </button>
      </div>
      {draftError && <ErrorBox className="mt-4">{draftError}</ErrorBox>}
      {remixError && <ErrorBox className="mt-4">Could not copy that debate: {remixError}</ErrorBox>}

      <WizardProgress step={state.step} maxStep={maxStep} onSelect={goTo} />

      {state.step === 1 && <StepTopic state={state} patch={patch} showErrors={showErrors} />}
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
          paidLocked={paidLocked}
          showErrors={showErrors}
        />
      )}
      {state.step === 3 && <StepFormat state={state} patch={patch} accountKeyMasked={user?.openrouter_key_masked ?? null} openrouterKey={openrouterKey} ttsKeyCheck={ttsKeyCheck} aiImagesLocked={(user?.credits_usd ?? 0) <= 0} factCheckLocked={paidLocked} />}
      {state.step === 4 && (
        <StepReview
          state={state}
          patch={patch}
          config={config}
          ready={ready}
          models={models}
          voices={catalogue.voices}
          ownKey={ownKey}
          credits={user?.credits_usd ?? 0}
          paymentsMode={billing.payments_mode}
          starting={starting}
          startError={startError}
          onStart={start}
        />
      )}

      {state.step < 4 && (
        <div className="mt-[26px] flex items-center justify-between gap-3">
          <Button variant="secondary" onClick={prev} disabled={state.step === 1} icon={<ArrowLeft className="size-4" />}>
            Back
          </Button>
          <Button variant="light" onClick={next} icon={<ArrowRight className="size-4" />}>
            Continue
          </Button>
        </div>
      )}
    </Page>
  );
};

export default CreateDebate;
