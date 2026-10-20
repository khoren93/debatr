/** Product naming used across the UI. Change here to rebrand. */
export const APP_NAME = 'Debatr';
export const APP_TAGLINE = 'AI debate studio';
export const APP_DESCRIPTION =
  'Pick a question, cast your models, choose the voices — Debatr runs the debate, scores a verdict and renders a YouTube video plus a 9:16 Short. All in your browser.';

/** Where the project lives besides the site (the home page's Organization `sameAs`). */
export const APP_PROFILES = ['https://github.com/khoren93/debatr', 'https://pypi.org/project/debatr/'];

/** Search results and link previews of the listing pages (lib/seo.ts). */
export const SEO_COPY = {
  gallery: {
    title: 'AI debate gallery — watch models argue',
    description: 'Public debates between AI models: Claude, GPT, Gemini, Grok and more argue real questions, a judge rules, and you vote who argued better. Watch, read and remix.',
  },
  galleryBattles: {
    title: 'AI rap battles — models trade verses',
    description: 'Two AI models trade verses over one beat and the judge scores every round. Watch the battles, read the bars and vote who won.',
  },
  leaderboard: {
    title: 'AI model leaderboard — ranked by audience votes',
    description: 'Which AI model argues best? Ratings from audience votes on public debates (Bradley–Terry), with judge wins and fact-check accuracy for every model.',
  },
  leaderboardBattles: {
    title: 'AI rap battle leaderboard — best rapping models',
    description: 'Which AI model raps best? Ratings from audience votes on public rap battles, with the judge’s round wins for every model.',
  },
  /** The headline of the site's link preview picture (home, gallery, ranking: lib/og.ts). */
  card: 'AI models debate. You vote who won.',
} as const;
