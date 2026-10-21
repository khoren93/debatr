/**
 * Chart colours of the admin console, checked with the dataviz palette validator against the
 * card surface (`--color-surface` #12141b, dark mode):
 * - two series: blue #3987e5 + orange #d95926 pass every check (CVD ΔE 26.8, normal 31.8);
 * - debate statuses stacked in this order: aqua #199e70 (completed), violet #9085e9 (stopped),
 *   red #e66767 (error) pass every check (worst adjacent CVD ΔE 17.3, normal 22.5).
 * The brand's pro/con colours are too light for chart marks (outside the lightness band).
 */
export const SERIES = ['#3987e5', '#d95926'] as const;

export const STATUS_COLORS = {
  completed: '#199e70',
  stopped: '#9085e9',
  error: '#e66767',
} as const;

export const SURFACE = '#12141b';
export const GRID = 'rgba(255,255,255,0.07)';
export const BASELINE = 'rgba(255,255,255,0.18)';
export const AXIS_TEXT = '#8b90a0';

/**
 * Spend categories, stacked models → voices → pictures → music → cover: the reference categorical
 * order's first three slots (blue, orange, aqua), validated against the card surface with every
 * pair in play (worst CVD ΔE 9.4, normal vision 20.9), then violet, whose only neighbour in the
 * stack is aqua (that pair passed with the status colours: CVD ΔE 17.3, normal 22.5), then the
 * reference's yellow beside violet (CVD ΔE 27.3, normal 27.5; all five adjacent pairs pass).
 */
export const SPEND_COLORS = { models: '#3987e5', voices: '#d95926', pictures: '#199e70', music: '#9085e9', cover: '#c98500' } as const;

/**
 * Where views came from, stacked search → AI assistants → social → embeds → other sites → direct →
 * the site's own pages: the reference categorical order's first seven dark steps in order (blue,
 * orange, aqua, yellow, magenta, green, violet), validated against the card surface: every check
 * passes (worst adjacent CVD ΔE 8.4 aqua↔yellow, normal vision 19.3 magenta↔yellow).
 */
export const SOURCE_COLORS = { search: '#3987e5', ai: '#d95926', social: '#199e70', embed: '#c98500', other: '#d55181', direct: '#008300', internal: '#9085e9' } as const;

export const SOURCE_LABELS = { search: 'Search', ai: 'AI assistants', social: 'Social', embed: 'Embeds', other: 'Other sites', direct: 'Direct', internal: 'On the site' } as const;

/**
 * Magnitude in one hue (the Audience page's weekday × hour grid): the reference blue ramp's
 * steps 600, 450, 350, 200 and 100, few → many on the dark card. Checked with the validator as an
 * ordinal ramp against the card surface: monotone lightness, every adjacent gap ≥ 0.06, the
 * darkest step 2.27:1 against the surface, one hue. An empty cell is the neutral surface step.
 */
export const HEAT_STEPS = ['#184f95', '#2a78d6', '#5598e7', '#9ec5f4', '#cde2fb'] as const;
export const HEAT_EMPTY = 'rgba(255,255,255,0.05)';
