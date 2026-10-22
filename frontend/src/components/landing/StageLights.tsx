import type { CSSProperties } from 'react';

/** Lamps along the top edge, like a battle's club lights in the video (video/components/
 *  Background): the sides' colours outside, the accent inside, each leaning toward the middle. */
const BEAMS = [
  { x: 10, color: 'var(--color-pro)', strength: 30, lean: -18, delay: 0 },
  { x: 36, color: 'var(--color-accent)', strength: 18, lean: -7, delay: -3.5 },
  { x: 64, color: 'var(--color-accent)', strength: 18, lean: 7, delay: 0 },
  { x: 90, color: 'var(--color-con)', strength: 30, lean: 18, delay: -3.5 },
];

const tint = (color: string, percent: number) => `color-mix(in srgb, ${color} ${percent}%, transparent)`;

/** Stage lights over the home page's hero: four beams swinging slowly in opposite pairs and
 *  flaring on a battle's tempo; still for visitors who ask for less motion. Decoration only. */
export const StageLights = ({ className = '' }: { className?: string }) => (
  <div className={`pointer-events-none overflow-hidden ${className}`} aria-hidden="true">
    {BEAMS.map((beam) => (
      <div
        key={beam.x}
        className="absolute top-0 h-full w-[720px] origin-top -translate-x-1/2 animate-beam-swing motion-reduce:animate-none"
        style={{ left: `${beam.x}%`, rotate: `${beam.lean}deg`, animationDelay: `${beam.delay}s`, '--lean': `${beam.lean}deg`, '--swing': '11deg' } as CSSProperties}
      >
        <div
          className="size-full animate-beam-flare motion-reduce:animate-none"
          style={{
            // A soft cone from the lamp (brightest straight down, gone at ±13°), fading with distance.
            background: `radial-gradient(90px 34px at 50% 0, ${tint(beam.color, beam.strength * 1.6)}, transparent), conic-gradient(from 180deg at 50% 0, ${tint(beam.color, beam.strength)}, ${tint(beam.color, beam.strength * 0.45)} 5deg, transparent 13deg 347deg, ${tint(beam.color, beam.strength * 0.45)} 355deg, ${tint(beam.color, beam.strength)})`,
            maskImage: 'linear-gradient(to bottom, #000, transparent 95%)',
          }}
        />
      </div>
    ))}
  </div>
);
