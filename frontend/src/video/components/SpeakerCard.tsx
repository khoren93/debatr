import { useCurrentFrame, useVideoConfig } from 'remotion';
import type { TimelineSegment, TimelineSpeaker } from '../../api/timeline';
import { DISPLAY_FONT, FONT, MONO_FONT, barHeight } from '../constants';
import { frameToMs, levelAt } from '../utils';
import { LogoTile } from './ModelLogo';

const MUTED = '#8B90A0';
const DIM = '#5C6170';

/** A debater's card: model logo, name, model, and SPEAKING (or the side) under it. */
export const SpeakerCard = ({ speaker, tag, active, width }: { speaker: TimelineSpeaker; tag: string; active: boolean; width: number }) => {
  const name = width * 0.112;
  return (
    <div
      style={{
        width,
        padding: `${width * 0.106}px ${width * 0.07}px`,
        borderRadius: width * 0.106,
        background: 'rgba(18,20,27,0.72)',
        border: `2px solid ${active ? speaker.color : '#ffffff14'}`,
        outline: active ? `${Math.round(width * 0.02)}px solid ${speaker.color}38` : 'none',
        boxShadow: active ? `0 ${width * 0.06}px ${width * 0.18}px ${speaker.color}55` : 'none',
        opacity: active ? 1 : 0.72,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: width * 0.03,
        textAlign: 'center',
      }}
    >
      <LogoTile speaker={speaker} size={width * 0.33} framed={active} />
      <div style={{ marginTop: width * 0.02, maxWidth: '100%', fontFamily: DISPLAY_FONT, fontWeight: 700, fontSize: name, lineHeight: 1.1, letterSpacing: -0.02 * name, color: '#F2F3F7', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{speaker.name}</div>
      <div style={{ maxWidth: '100%', fontFamily: MONO_FONT, fontSize: width * 0.059, color: MUTED, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{speaker.model}</div>
      <div style={{ fontFamily: MONO_FONT, fontSize: width * 0.053, letterSpacing: 0.12 * width * 0.053, color: active ? speaker.color : DIM }}>{active ? 'SPEAKING' : tag}</div>
    </div>
  );
};

/** A debater in the Short's rows: logo on the left; name, model and SPEAKING (or the side) beside it. */
export const SpeakerRowCard = ({ speaker, tag, active, width, height }: { speaker: TimelineSpeaker; tag: string; active: boolean; width: number; height: number }) => {
  const logo = height * 0.64;
  const pad = (height - logo) / 2;
  const name = height * 0.26;
  return (
    <div
      style={{
        width,
        height,
        boxSizing: 'border-box',
        padding: `0 ${pad}px`,
        borderRadius: height * 0.24,
        background: 'rgba(18,20,27,0.72)',
        border: `2px solid ${active ? speaker.color : '#ffffff14'}`,
        outline: active ? `${Math.round(height * 0.04)}px solid ${speaker.color}38` : 'none',
        boxShadow: active ? `0 ${height * 0.1}px ${height * 0.3}px ${speaker.color}55` : 'none',
        opacity: active ? 1 : 0.72,
        display: 'flex',
        alignItems: 'center',
        gap: pad * 0.8,
      }}
    >
      <LogoTile speaker={speaker} size={logo} framed={active} />
      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: height * 0.025 }}>
        <div style={{ fontFamily: DISPLAY_FONT, fontWeight: 700, fontSize: name, lineHeight: 1.1, letterSpacing: -0.02 * name, color: '#F2F3F7', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{speaker.name}</div>
        <div style={{ fontFamily: MONO_FONT, fontSize: height * 0.135, color: MUTED, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{speaker.model}</div>
        <div style={{ fontFamily: MONO_FONT, fontSize: height * 0.12, letterSpacing: 0.12 * height * 0.12, color: active ? speaker.color : DIM }}>{active ? 'SPEAKING' : tag}</div>
      </div>
    </div>
  );
};

/** Pill of whoever speaks (host, debater or judge): logo, name, model and live level bars. */
export const SpeakingChip = ({ speaker, seg, offsetMs, u }: { speaker: TimelineSpeaker; seg: TimelineSegment | null; offsetMs: number; u: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = frameToMs(frame, fps) - offsetMs;
  const live = seg?.speaker_id === speaker.id ? seg : null;
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: u, height: barHeight(u), boxSizing: 'border-box', padding: `0 ${1.4 * u}px 0 ${0.6 * u}px`, borderRadius: 999, background: 'rgba(10,11,15,0.7)', border: `2px solid ${speaker.color}`, boxShadow: `0 0 ${3 * u}px ${speaker.color}38`, fontFamily: FONT }}>
      <LogoTile speaker={speaker} size={3 * u} framed round />
      <div style={{ display: 'flex', flexDirection: 'column', maxWidth: 16 * u }}>
        <span style={{ fontWeight: 700, fontSize: 1.4 * u, lineHeight: 1.2, color: '#F2F3F7', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{speaker.name}</span>
        <span style={{ fontFamily: MONO_FONT, fontSize: 0.85 * u, color: MUTED, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{speaker.model}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 0.25 * u, height: 1.8 * u }}>
        {[0, 70, 140, 35].map((shift) => (
          <div key={shift} style={{ width: 0.3 * u, height: 1.8 * u * Math.max(0.3, live ? levelAt(live, ms + shift) : 0), background: speaker.color }} />
        ))}
      </div>
    </div>
  );
};
