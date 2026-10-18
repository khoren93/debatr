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
 * Spend categories, stacked models → voices → pictures: the reference categorical order's first
 * three slots (blue, orange, aqua), validated against the card surface with every pair in play
 * (worst CVD ΔE 9.4, normal vision 20.9).
 */
export const SPEND_COLORS = { models: '#3987e5', voices: '#d95926', pictures: '#199e70' } as const;
