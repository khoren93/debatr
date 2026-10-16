/**
 * Provider logos for OpenRouter model ids. OpenRouter's API has no icons, so the author part of
 * the id ("anthropic/claude-sonnet-4" -> "anthropic") picks a file in public/model-icons
 * (LobeHub Icons, MIT; see the README there). Unknown authors get a letter tile.
 */

/** Model families whose logo differs from their author's. Checked first. */
const BY_FAMILY: [RegExp, string][] = [[/^google\/gemma/, 'gemma-color']];

const BY_AUTHOR: Record<string, string> = {
  openai: 'openai',
  anthropic: 'claude-color',
  google: 'gemini-color',
  qwen: 'qwen-color',
  mistralai: 'mistral-color',
  'z-ai': 'zai',
  thudm: 'zai',
  deepseek: 'deepseek-color',
  nvidia: 'nvidia-color',
  meta: 'meta-color',
  'meta-llama': 'meta-color',
  'x-ai': 'grok',
  moonshotai: 'kimi-color',
  minimax: 'minimax-color',
  tencent: 'hunyuan-color',
  cohere: 'cohere-color',
  bytedance: 'bytedance-color',
  'bytedance-seed': 'bytedance-color',
  amazon: 'nova-color',
  perplexity: 'perplexity-color',
  xiaomi: 'xiaomimimo',
  microsoft: 'microsoft-color',
  'ibm-granite': 'ibm',
  nousresearch: 'nousresearch',
  liquid: 'liquid',
  inception: 'inception',
  stepfun: 'stepfun-color',
  'stepfun-ai': 'stepfun-color',
  upstage: 'upstage-color',
  'arcee-ai': 'arcee-color',
  ai21: 'ai21-brand-color',
  openrouter: 'openrouter-color',
  sakana: 'sakana-color',
  inflection: 'inflection',
  poolside: 'poolside-color',
  baidu: 'baidu-color',
  alibaba: 'alibaba-color',
  'dots-studio': 'dotsstudio',
  'rednote-hilab': 'dotsstudio',
  fireworks: 'fireworks-color',
  meituan: 'longcat-color',
  inclusionai: 'antgroup-color',
  kwaipilot: 'kwaipilot-color',
  allenai: 'ai2-color',
  rekaai: 'reka',
  morph: 'morph-color',
  relace: 'relace',
  perceptron: 'perceptron',
  baai: 'baai',
  huggingfaceh4: 'huggingface-color',
};

export interface ModelIconInfo {
  src: string;
  /** Single-colour logo (`currentColor`): draw it as a mask in the text colour. */
  mono: boolean;
}

/** "~anthropic/claude-x" -> "anthropic" (OpenRouter prefixes alias ids with "~"). */
export const modelAuthor = (modelId: string) => (modelId.includes('/') ? modelId.split('/')[0].replace(/^~/, '').toLowerCase() : '');

export const modelIcon = (modelId: string | null | undefined): ModelIconInfo | null => {
  if (!modelId) return null;
  const id = modelId.replace(/^~/, '').toLowerCase();
  const file = BY_FAMILY.find(([re]) => re.test(id))?.[1] ?? BY_AUTHOR[modelAuthor(id)];
  return file ? { src: `/model-icons/${file}.svg`, mono: !file.endsWith('-color') } : null;
};
