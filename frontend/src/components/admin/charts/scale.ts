/** Axis maths shared by the admin charts (pure). */

/** Rounded maximum and ticks from 0: 0 / 5 / 10 / 15, 0 / 0.02 / 0.04 … `integer` keeps whole
 * steps (counts of people or debates never sit at 2.5). */
export const niceTicks = (max: number, count = 4, integer = false): number[] => {
  if (!(max > 0)) return [0, 1];
  const raw = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const factors = integer ? [1, 2, 5, 10] : [1, 2, 2.5, 5, 10];
  let step = factors.map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
  if (integer) step = Math.max(1, Math.round(step));
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.999; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
};

/** Indexes of at most `count` evenly spread x labels (always the first and the last). */
export const labelIndexes = (length: number, count: number): number[] => {
  if (length <= count) return Array.from({ length }, (_, i) => i);
  const step = (length - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => Math.round(i * step));
};

export type Bucket = 'hour' | 'day' | 'week';

/** "17:00", "Oct 18", "wk Oct 12" in UTC (the buckets are UTC). */
export const bucketLabel = (iso: string, bucket: Bucket): string => {
  const date = new Date(iso);
  if (bucket === 'hour') {
    return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
  }
  const day = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
  return bucket === 'week' ? `wk ${day}` : day;
};
