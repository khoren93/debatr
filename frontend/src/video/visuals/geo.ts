import { geoArea, geoGraticule10, geoNaturalEarth1, geoPath, type GeoProjection } from 'd3-geo';
import type { Feature, FeatureCollection, Polygon } from 'geojson';
import { feature } from 'topojson-client';
import type { GeometryCollection, Topology } from 'topojson-specification';
import atlasUrl from 'world-atlas/countries-110m.json?url';

/**
 * World map for the `map` scene (lazy chunk, see geoLoader.ts): the 110m Natural Earth atlas,
 * projected and fitted to the scene box. Paths are memoized per layout, since the scene is
 * redrawn on every frame.
 */

// ISO alpha-3 + alpha-2 + numeric atlas id; mirrors COUNTRY_TABLE in backend/app/schemas/geo.py.
const COUNTRY_TABLE = `
AFGAF004 AGOAO024 ALBAL008 AREAE784 ARGAR032 ARMAM051 ATAAQ010 ATFTF260 AUSAU036 AUTAT040
AZEAZ031 BDIBI108 BELBE056 BENBJ204 BFABF854 BGDBD050 BGRBG100 BHSBS044 BIHBA070 BLRBY112
BLZBZ084 BOLBO068 BRABR076 BRNBN096 BTNBT064 BWABW072 CAFCF140 CANCA124 CHECH756 CHLCL152
CHNCN156 CIVCI384 CMRCM120 CODCD180 COGCG178 COLCO170 CRICR188 CUBCU192 CYPCY196 CZECZ203
DEUDE276 DJIDJ262 DNKDK208 DOMDO214 DZADZ012 ECUEC218 EGYEG818 ERIER232 ESHEH732 ESPES724
ESTEE233 ETHET231 FINFI246 FJIFJ242 FLKFK238 FRAFR250 GABGA266 GBRGB826 GEOGE268 GHAGH288
GINGN324 GMBGM270 GNBGW624 GNQGQ226 GRCGR300 GRLGL304 GTMGT320 GUYGY328 HNDHN340 HRVHR191
HTIHT332 HUNHU348 IDNID360 INDIN356 IRLIE372 IRNIR364 IRQIQ368 ISLIS352 ISRIL376 ITAIT380
JAMJM388 JORJO400 JPNJP392 KAZKZ398 KENKE404 KGZKG417 KHMKH116 KORKR410 KWTKW414 LAOLA418
LBNLB422 LBRLR430 LBYLY434 LKALK144 LSOLS426 LTULT440 LUXLU442 LVALV428 MARMA504 MDAMD498
MDGMG450 MEXMX484 MKDMK807 MLIML466 MMRMM104 MNEME499 MNGMN496 MOZMZ508 MRTMR478 MWIMW454
MYSMY458 NAMNA516 NCLNC540 NERNE562 NGANG566 NICNI558 NLDNL528 NORNO578 NPLNP524 NZLNZ554
OMNOM512 PAKPK586 PANPA591 PERPE604 PHLPH608 PNGPG598 POLPL616 PRIPR630 PRKKP408 PRTPT620
PRYPY600 PSEPS275 QATQA634 ROURO642 RUSRU643 RWARW646 SAUSA682 SDNSD729 SENSN686 SLBSB090
SLESL694 SLVSV222 SOMSO706 SRBRS688 SSDSS728 SURSR740 SVKSK703 SVNSI705 SWESE752 SWZSZ748
SYRSY760 TCDTD148 TGOTG768 THATH764 TJKTJ762 TKMTM795 TLSTL626 TTOTT780 TUNTN788 TURTR792
TWNTW158 TZATZ834 UGAUG800 UKRUA804 URYUY858 USAUS840 UZBUZ860 VENVE862 VNMVN704 VUTVU548
YEMYE887 ZAFZA710 ZMBZM894 ZWEZW716
`;

interface Country {
  code: string; // alpha-3
  alpha2: string;
  shape: Feature;
  main: Feature; // the largest polygon (mainland France without Guiana), to frame and label
}

const mainland = (shape: Feature): Feature => {
  if (shape.geometry.type !== 'MultiPolygon') return shape;
  const pieces = shape.geometry.coordinates.map((coordinates): Feature<Polygon> => ({ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates } }));
  return pieces.reduce((best, piece) => (geoArea(piece) > geoArea(best) ? piece : best));
};

export interface World {
  countries: Map<string, Country>;
  all: Feature[];
}

export const loadWorld = async (): Promise<World> => {
  const response = await fetch(atlasUrl);
  if (!response.ok) throw new Error(`World map: HTTP ${response.status}`);
  const atlas = (await response.json()) as Topology<{ countries: GeometryCollection }>;
  const shapes = (feature(atlas, atlas.objects.countries) as FeatureCollection).features;
  const byId = new Map(shapes.map((f) => [String(f.id), f]));
  const countries = new Map<string, Country>();
  for (const entry of COUNTRY_TABLE.split(/\s+/).filter(Boolean)) {
    const shape = byId.get(entry.slice(5));
    if (shape) countries.set(entry.slice(0, 3), { code: entry.slice(0, 3), alpha2: entry.slice(3, 5), shape, main: mainland(shape) });
  }
  return { countries, all: shapes };
};

export interface MapRegionLayout {
  d: string; // outline of every country of the region
  box: [number, number, number, number] | null; // x0, y0, x1, y1 on screen; null: out of view
  alpha2: string | null; // for a localized name when the region is one country
}

export interface MapLayout {
  base: string; // every country, one path
  graticule: string;
  regions: MapRegionLayout[];
}

const MAX_ZOOM = 7;
const CONTEXT = 0.6; // zoom out from a tight fit so the neighbours stay visible
const cache = new Map<string, MapLayout>();

/** Fit the world (or the highlighted countries, zoomed out a little) into a w×h box. */
const fitProjection = (w: number, h: number, focus: Feature[], pad: number): GeoProjection => {
  const full = geoNaturalEarth1().fitExtent([[pad, pad], [w - pad, h - pad]], { type: 'Sphere' });
  if (!focus.length) return full;
  const collection: FeatureCollection = { type: 'FeatureCollection', features: focus };
  const fit = geoNaturalEarth1().fitExtent([[pad * 4, pad * 4], [w - pad * 4, h - pad * 4]], collection);
  const target = Math.min(fit.scale() * CONTEXT, full.scale() * MAX_ZOOM);
  if (target < full.scale() * 1.4) return full;
  // Scale about the box centre, where fitExtent put the highlighted countries.
  const f = target / fit.scale();
  const [tx, ty] = fit.translate();
  return fit.scale(target).translate([w / 2 + f * (tx - w / 2), h / 2 + f * (ty - h / 2)]);
};

export const layoutMap = (world: World, w: number, h: number, groups: string[][], pad: number): MapLayout => {
  const key = `${Math.round(w)}x${Math.round(h)}:${Math.round(pad)}:${groups.map((g) => g.join(',')).join(';')}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const members = groups.map((codes) => codes.map((c) => world.countries.get(c)).filter((c): c is Country => Boolean(c)));
  const projection = fitProjection(w, h, members.flat().map((c) => c.main), pad).clipExtent([[0, 0], [w, h]]);
  const path = geoPath(projection);
  const regions = members.map((list): MapRegionLayout => {
    let box: MapRegionLayout['box'] = null;
    for (const country of list) {
      const [[x0, y0], [x1, y1]] = path.bounds(country.main);
      if (!Number.isFinite(x0) || x1 - x0 <= 0) continue;
      box = box ? [Math.min(box[0], x0), Math.min(box[1], y0), Math.max(box[2], x1), Math.max(box[3], y1)] : [x0, y0, x1, y1];
    }
    return { d: list.map((c) => path(c.shape) ?? '').join(' '), box, alpha2: list.length === 1 ? list[0].alpha2 : null };
  });
  const layout: MapLayout = { base: world.all.map((f) => path(f) ?? '').join(' '), graticule: path(geoGraticule10()) ?? '', regions };
  if (cache.size > 24) cache.clear();
  cache.set(key, layout);
  return layout;
};
