/** The debate languages the site offers: `name` is what `DebateConfig.language` stores, `code`
 *  what the API answers as `language_code` (backend services/media/languages.LANGUAGE_CODES),
 *  `label` the language's own name. */
export const LANGUAGES: { code: string; name: string; label: string }[] = [
  { code: 'en', name: 'English', label: 'English' },
  { code: 'ru', name: 'Russian', label: 'Русский' },
  { code: 'es', name: 'Spanish', label: 'Español' },
  { code: 'fr', name: 'French', label: 'Français' },
  { code: 'de', name: 'German', label: 'Deutsch' },
  { code: 'it', name: 'Italian', label: 'Italiano' },
  { code: 'pt', name: 'Portuguese', label: 'Português' },
  { code: 'zh', name: 'Chinese', label: '中文' },
  { code: 'ja', name: 'Japanese', label: '日本語' },
  { code: 'ko', name: 'Korean', label: '한국어' },
  { code: 'uk', name: 'Ukrainian', label: 'Українська' },
  { code: 'hy', name: 'Armenian', label: 'Հայերեն' },
  { code: 'pl', name: 'Polish', label: 'Polski' },
  { code: 'tr', name: 'Turkish', label: 'Türkçe' },
  { code: 'ar', name: 'Arabic', label: 'العربية' },
  { code: 'hi', name: 'Hindi', label: 'हिन्दी' },
  { code: 'nl', name: 'Dutch', label: 'Nederlands' },
];

/** A language code's own name ("ru" → "Русский"); a code the site does not offer stays as is. */
export const languageName = (code: string) => LANGUAGES.find((l) => l.code === code)?.label ?? code.toUpperCase();
