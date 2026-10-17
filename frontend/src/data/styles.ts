export interface PersonaStyle {
  id: string;
  label: string; // chip label
  full: string; // long label
  short: string; // one-line summary under the label in the wizard
  desc: string; // appended to the system prompt as "Style: …"
}

export const STYLE_PRESETS: PersonaStyle[] = [
  { id: 'neutral', label: 'Neutral', full: 'Neutral / Logical', short: 'Calm, evidence-first, no theatrics', desc: 'Maintain a neutral, objective, and logical tone. Avoid emotional language and focus on facts.' },
  { id: 'polite', label: 'Polite', full: 'Respectful / Polite', short: 'Concedes small points, wins big ones', desc: 'Be consistently polite and respectful. Acknowledge valid points from other speakers.' },
  { id: 'aggressive', label: 'Aggressive', full: 'Aggressive / Confrontational', short: 'Attacks every weak point', desc: "Be aggressive and confrontational. Attack the opponent's arguments relentlessly and show no mercy." },
  { id: 'sarcastic', label: 'Sarcastic', full: 'Sarcastic / Witty', short: 'Quotable one-liners, sharp humour', desc: "Use sarcasm, irony, and wit to undermine the opponent's position. Be clever and biting." },
  { id: 'passionate', label: 'Passionate', full: 'Emotional / Passionate', short: 'Vivid stories, strong feelings', desc: 'Appeal to emotion. Use passionate language, vivid anecdotes, and strong feelings.' },
  { id: 'academic', label: 'Academic', full: 'Academic / Formal', short: 'Formal, theory and frameworks', desc: 'Use formal, academic language. Cite abstract concepts and theoretical frameworks.' },
  { id: 'simple', label: 'ELI5', full: 'Simple / ELI5', short: 'Plain words, no jargon', desc: 'Explain arguments simply as if to a 5-year-old. Avoid jargon and complex sentences.' },
  { id: 'rude', label: 'Rude', full: 'Rude / Vulgar (NSFW)', short: 'Raw language, holds nothing back', desc: "Be raw, rude, and use strong language/profanity if necessary to make a point. Don't hold back." },
];

/** Replace (or append) the "Style: …" line of a system prompt. */
export const applyStyle = (prompt: string, style: PersonaStyle) =>
  prompt.includes('Style:') ? prompt.replace(/Style:[\s\S]*$/, `Style: ${style.desc}`) : `${prompt.trim()}\n\nStyle: ${style.desc}`;

/** Drop the "Style: …" line: the prompt becomes the user's own (persona "Custom"). */
export const clearStyle = (prompt: string) => prompt.replace(/\s*Style:[\s\S]*$/, '').trim();

/** Which preset a prompt currently uses, if any. */
export const detectStyle = (prompt: string) => STYLE_PRESETS.find((s) => prompt.includes(s.desc)) ?? null;
