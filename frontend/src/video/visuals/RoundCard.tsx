import { ACCENT, DISPLAY_FONT } from '../constants';
import { cardCover, type RoundCard } from '../groove';
import { INK, easeOut, fitFont, ramp } from './draw';

/** "ROUND 2" slamming onto the stage: big and in the accent with lines shooting out to the sides
 *  in a battle, smaller and white in a debate. On a dark plate when a scene is up behind it. */
export const RoundCardView = ({ card, ms, w, k, plate }: { card: RoundCard; ms: number; w: number; k: number; plate: boolean }) => {
  const land = easeOut(ramp(ms, card.slamMs, 220));
  const scale = (card.loud ? 1.7 : 1.25) - (card.loud ? 0.7 : 0.25) * land;
  const size = fitFont(card.label, w * 0.7, 1, (card.loud ? 180 : 120) * k, 80 * k);
  const lines = easeOut(ramp(ms, card.slamMs + 60, 320));
  // The lines stop short of the label (its width estimated like fitFont's).
  const reach = Math.max(0, w / 2 - size * 0.3 * card.label.length - 0.5 * size);
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: cardCover(card, ms) }}>
      {plate && <div style={{ position: 'absolute', left: w * 0.12, right: w * 0.12, top: '32%', bottom: '32%', borderRadius: 36 * k, background: '#0c1226ee' }} />}
      {card.loud && (
        <>
          <div style={{ position: 'absolute', left: 0, width: reach, top: '50%', height: 6 * k, marginTop: -3 * k, background: `linear-gradient(90deg, transparent, ${ACCENT})`, transform: `scaleX(${lines})`, transformOrigin: 'right center' }} />
          <div style={{ position: 'absolute', right: 0, width: reach, top: '50%', height: 6 * k, marginTop: -3 * k, background: `linear-gradient(90deg, ${ACCENT}, transparent)`, transform: `scaleX(${lines})`, transformOrigin: 'left center' }} />
        </>
      )}
      <div style={{ position: 'relative', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: size, lineHeight: 1, letterSpacing: -0.02 * size, color: card.loud ? ACCENT : INK, whiteSpace: 'nowrap', transform: `scale(${scale})` }}>
        {card.label}
      </div>
    </div>
  );
};
