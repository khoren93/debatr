import { Smile } from 'lucide-react';
import { STYLE_PRESETS, type PersonaStyle } from '../../data/styles';
import { PresetPicker } from './PresetPicker';

interface PersonaPickerProps {
  /** Preset the system prompt currently uses; null = custom prompt. */
  value: PersonaStyle | null;
  /** Speaker colour for the trigger icon. */
  color: string;
  onChange: (style: PersonaStyle) => void;
  /** "Custom": the user writes the whole system prompt. */
  onCustom: () => void;
}

const CUSTOM = 'custom';
/** Presets plus "Custom" at the end of the list. */
const OPTIONS = [...STYLE_PRESETS.map((s) => ({ id: s.id, full: s.full, short: s.short })), { id: CUSTOM, full: 'Custom', short: 'Your own system prompt' }];

/** Persona preset dropdown: replaces the "Style: …" line of the speaker's system prompt. */
export const PersonaPicker = ({ value, color, onChange, onCustom }: PersonaPickerProps) => (
  <PresetPicker
    value={value?.id ?? CUSTOM}
    options={OPTIONS}
    icon={<Smile className="size-4" />}
    color={color}
    label="Persona"
    onPick={(id) => {
      const style = STYLE_PRESETS.find((s) => s.id === id);
      if (style) onChange(style);
      else onCustom();
    }}
  />
);
