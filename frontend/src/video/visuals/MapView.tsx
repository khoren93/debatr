import type { MapScene } from '../../api/visuals';
import { DISPLAY_FONT, FONT } from '../constants';
import { INK, compactNumber, easeOut, ramp, seedOf, sketch, withUnit } from './draw';
import { useGeo } from './geoLoader';
import { InkLayer, Stroke } from './Ink';
import type { SceneCtx } from './scene';

const regionName = (alpha2: string | null, locale: string): string => {
  if (!alpha2) return '';
  try {
    return new Intl.DisplayNames([locale || 'en'], { type: 'region' }).of(alpha2) ?? '';
  } catch {
    return '';
  }
};

interface Tag {
  text: string;
  x: number; // left
  y: number; // top
  w: number;
  h: number;
}

/** Where a name tag may go around its region: below / above / beside the ring, or inside. */
const candidates = (box: [number, number, number, number], ring: boolean, tw: number, th: number, gap: number): [number, number][] => {
  const [x0, y0, x1, y1] = box;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const inside: [number, number] = [cx - tw / 2, cy - th / 2];
  const around: [number, number][] = [
    [cx - tw / 2, y1 + gap],
    [cx - tw / 2, y0 - gap - th],
    [x1 + gap, cy - th / 2],
    [x0 - gap - tw, cy - th / 2],
  ];
  return ring ? [...around, inside] : [inside, ...around];
};

/** The first spot that stays in the box and clears the tags placed before; else pushed down. */
const placeTag = (spots: [number, number][], tw: number, th: number, placed: Tag[], width: number, height: number): [number, number] => {
  const clear = (x: number, y: number) => x >= 0 && y >= 0 && x + tw <= width && y + th <= height && placed.every((p) => x + tw + 6 <= p.x || p.x + p.w + 6 <= x || y + th + 4 <= p.y || p.y + p.h + 4 <= y);
  const free = spots.find(([x, y]) => clear(x, y));
  if (free) return free;
  let [x, y] = spots[0];
  x = Math.min(width - tw, Math.max(0, x));
  y = Math.min(height - th, Math.max(0, y));
  for (let tries = 0; tries < 6 && !clear(x, y); tries++) y = Math.min(height - th, y + th + 4);
  return [x, y];
};

/** World map: the named countries fill in and get circled with the marker as they are said. */
export const MapView = ({ scene, ctx }: { scene: MapScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, locale, id } = ctx;
  const loaded = useGeo();
  if (!loaded) return null;
  const seed = seedOf(id);
  const layout = loaded.geo.layoutMap(loaded.world, w, h, scene.regions.map((r) => r.codes), 8 * k);
  const at = (i: number) => items[i] ?? 500 + i * 700;
  const values = scene.regions.map((r) => r.value).filter((v) => v !== null);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const strength = (v: number | null) => (v === null || hi === lo ? 0.75 : 0.35 + (0.55 * (v - lo)) / (hi - lo));
  const unit = scene.unit.length <= 3 ? scene.unit : '';
  const fs = 28 * k;
  // Small countries get a marker ring; big ones are visible enough when filled.
  const rings = layout.regions.map(({ box }) => {
    if (!box || (box[2] - box[0] > w * 0.16 || box[3] - box[1] > h * 0.3)) return null;
    const cx = (box[0] + box[2]) / 2;
    const cy = (box[1] + box[3]) / 2;
    const rw = Math.max(56 * k, box[2] - box[0] + 30 * k);
    const rh = Math.max(56 * k, box[3] - box[1] + 28 * k);
    return [cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2] as [number, number, number, number];
  });
  const tags: Tag[] = [];
  scene.regions.forEach((region, i) => {
    const name = region.label || regionName(layout.regions[i].alpha2, locale);
    const text = region.value === null ? name : `${name} ${withUnit(compactNumber(region.value, locale), unit)}`.trim();
    const tw = Math.min(w * 0.5, text.length * fs * 0.56 + 30 * k);
    const th = fs * 1.6;
    const box = rings[i] ?? layout.regions[i].box;
    const spots = box ? candidates(box, Boolean(rings[i]), tw, th, 4 * k) : [[(w - tw) / 2, h - th] as [number, number]];
    const [x, y] = placeTag(spots, tw, th, tags, w, h);
    tags.push({ text, x, y, w: tw, h: th });
  });
  return (
    <>
      <InkLayer w={w} h={h}>
        <path d={layout.graticule} fill="none" stroke={INK} strokeOpacity={0.07} strokeWidth={1 * k} opacity={ramp(t, 0, 600)} />
        <path d={layout.base} fill={INK} fillOpacity={0.06} stroke={INK} strokeOpacity={0.3} strokeWidth={0.9 * k} strokeLinejoin="round" opacity={easeOut(ramp(t, 0, 700))} />
        {scene.regions.map((region, i) => {
          const fill = easeOut(ramp(t, at(i), 500));
          return fill > 0 ? <path key={i} d={layout.regions[i].d} fill={color} fillOpacity={strength(region.value) * fill} stroke={color} strokeWidth={1.6 * k} strokeLinejoin="round" /> : null;
        })}
        {rings.map((ring, i) =>
          ring ? <Stroke key={`r${i}`} d={sketch.ellipse((ring[0] + ring[2]) / 2, (ring[1] + ring[3]) / 2, ring[2] - ring[0], ring[3] - ring[1], seed + i * 7, { roughness: 1.4 })} p={easeOut(ramp(t, at(i) + 150, 600))} color={color} width={4 * k} /> : null,
        )}
      </InkLayer>
      {tags.map((tag, i) =>
        tag.text ? (
          <div key={i} style={{ position: 'absolute', left: tag.x, top: tag.y, width: tag.w, height: tag.h, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 10 * k, background: '#0b1020d9', fontFamily: scene.regions[i].value === null ? FONT : DISPLAY_FONT, fontWeight: 800, fontSize: fs, color: INK, whiteSpace: 'nowrap', overflow: 'hidden', opacity: easeOut(ramp(t, at(i) + 300, 350)) }}>
            {tag.text}
          </div>
        ) : null,
      )}
    </>
  );
};
