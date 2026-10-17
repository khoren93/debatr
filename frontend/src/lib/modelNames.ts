import type { ModelInfo } from '../api/types';
import { modelAuthor } from './modelIcons';

/** OpenRouter's "Free Models Router": routes each request to an available free model. */
export const FREE_ROUTER_ID = 'openrouter/free';
const FREE_ROUTER_NAME = 'Free Router';

/** "Anthropic: Claude Sonnet 4.5" -> provider "Anthropic", title "Claude Sonnet 4.5". */
export const splitModelName = (model: Pick<ModelInfo, 'id' | 'name'>) => {
  const sep = model.name.indexOf(': ');
  if (sep > 0) return { provider: model.name.slice(0, sep), title: model.name.slice(sep + 2) };
  const author = modelAuthor(model.id);
  return { provider: !author || author === 'openrouter' ? 'OpenRouter' : author, title: model.name };
};

/** Price per 1M tokens: "$0.60", "$15", "$0". */
export const perMillion = (price: string) => {
  const n = parseFloat(price) * 1_000_000;
  if (!Number.isFinite(n) || n < 0) return 'varies';
  if (n === 0) return '$0';
  return `$${n >= 10 ? n.toFixed(0) : n.toFixed(2)}`;
};

/** Model title without the provider and without a trailing "(free)" / "(batch)" qualifier. */
export const modelTitle = (modelId: string, models: ModelInfo[]) => {
  const model = models.find((m) => m.id === modelId);
  if (modelId === FREE_ROUTER_ID) return FREE_ROUTER_NAME;
  if (model) return splitModelName(model).title.replace(/\s*\([^)]*\)\s*$/, '').trim() || model.name;
  // Not in the catalogue (retired model in an old draft): "anthropic/claude-sonnet-4.5:free" -> "Claude sonnet 4.5".
  const raw = (modelId.split('/').pop() ?? modelId).replace(/:.*$/, '').replace(/-/g, ' ').trim();
  return raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : 'Model';
};

/** What a debater is called on stage: the model family ("Claude", "Gemini", "GPT-5.5"). */
const familyName = (title: string) => (title === FREE_ROUTER_NAME ? title : (title.split(/\s+/)[0] ?? title));

/**
 * Speaker names come from the models (the wizard has no name fields): the host stays "The Host",
 * debaters are called after their model family. Two different models of one family get their
 * full titles ("Claude Sonnet 5" vs "Claude Opus 4.7"); the same model twice gets letters
 * ("Gemini A", "Gemini B") — the prompts and the judge's verdict need distinct names.
 */
export const speakerNames = (speakers: { role: string; modelId: string }[], models: ModelInfo[], hostName: string) => {
  const titles = speakers.map((s) => modelTitle(s.modelId, models));
  const families = titles.map(familyName);
  const debaters = speakers.flatMap((s, i) => (s.role === 'moderator' ? [] : [i]));
  const names = speakers.map((s, i) => {
    if (s.role === 'moderator') return hostName;
    const clash = debaters.some((j) => families[j] === families[i] && speakers[j].modelId !== s.modelId);
    return clash ? titles[i] : families[i];
  });
  const counts = new Map<string, number>();
  for (const i of debaters) counts.set(names[i], (counts.get(names[i]) ?? 0) + 1);
  const seen = new Map<string, number>();
  for (const i of debaters) {
    if ((counts.get(names[i]) ?? 0) < 2) continue;
    const n = seen.get(names[i]) ?? 0;
    seen.set(names[i], n + 1);
    names[i] = `${names[i]} ${String.fromCharCode(65 + n)}`;
  }
  return names;
};
