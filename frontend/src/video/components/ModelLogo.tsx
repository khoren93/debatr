import { Img } from 'remotion';
import type { TimelineSpeaker } from '../../api/timeline';
import { modelAuthor, modelIcon } from '../../lib/modelIcons';
import { FONT } from '../constants';
import { LOGO_COLOR, usePaintedLogo } from '../logos';
import { speakerModelId } from '../speakers';

/** A logo painted to a raster (in `color` for single-colour ones), which every browser's MP4
 *  renderer draws the same. */
const PaintedLogo = ({ src, size, color }: { src: string; size: number; color: string | null }) => {
  const url = usePaintedLogo(src, color);
  return url ? <Img src={url} style={{ width: size, height: size, display: 'block' }} /> : <div style={{ width: size, height: size }} />;
};

/** Provider logo of a model, `size` px square (a letter for unknown providers). */
export const ModelLogo = ({ modelId, size, color = LOGO_COLOR }: { modelId: string; size: number; color?: string }) => {
  const icon = modelIcon(modelId);
  if (!icon) {
    const letter = (modelAuthor(modelId) || modelId || '?').charAt(0).toUpperCase();
    return <div style={{ width: size, height: size, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: FONT, fontWeight: 800, fontSize: size * 0.8, lineHeight: 1, color }}>{letter}</div>;
  }
  return <PaintedLogo src={icon.src} size={size} color={icon.mono ? color : null} />;
};

/** The logo on a rounded tile: tinted in the speaker's colour, framed when `framed`. */
export const LogoTile = ({ speaker, size, framed, round = false }: { speaker: TimelineSpeaker; size: number; framed: boolean; round?: boolean }) => (
  <div
    style={{
      width: size,
      height: size,
      flexShrink: 0,
      borderRadius: round ? size / 2 : size * 0.29,
      background: round ? '#0A0B0F' : `${speaker.color}29`,
      border: `${Math.max(2, size * 0.02)}px solid ${framed ? speaker.color : '#ffffff14'}`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
    }}
  >
    <ModelLogo modelId={speakerModelId(speaker)} size={size * (round ? 0.62 : 0.58)} />
  </div>
);
