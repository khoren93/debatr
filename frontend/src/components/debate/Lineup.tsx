import type { Participant } from '../../api/types';
import { JUDGE_COLOR, roleTag, shortModelName, speakerColor } from '../../lib/format';
import { Card, ModelIcon, SectionLabel, SpeakerBadge } from '../ui';

interface Props {
  participants: Participant[];
  judgeVoice?: string | null;
  className?: string;
}

/** LINEUP card: every speaker with their model, plus the judge. */
export const Lineup = ({ participants, judgeVoice, className = '' }: Props) => {
  const moderator = participants.find((p) => p.role === 'moderator');
  return (
    <Card padding="sm" className={`!p-5 ${className}`}>
      <SectionLabel>Lineup</SectionLabel>
      <div className="mt-3 grid gap-2.5">
        {participants.map((p, i) => {
          const id = p.id ?? `participant_${i}`;
          const color = speakerColor(id, participants);
          return (
            <div key={id} className="flex items-center gap-3">
              <SpeakerBadge name={p.name} color={color} size={32} imageUrl={p.avatar} />
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-[13px] font-semibold">
                  <span className="truncate">{p.name ?? 'Speaker'}</span>
                  <span className="font-mono text-[10px]" style={{ color }}>
                    {roleTag(p, participants)}
                  </span>
                </div>
                <div className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted">
                  <ModelIcon modelId={p.model} size={12} className="text-text-3" />
                  <span className="truncate">{shortModelName(p.model)}</span>
                </div>
              </div>
            </div>
          );
        })}
        <div className="flex items-center gap-3">
          <SpeakerBadge name="Judge" color={JUDGE_COLOR} size={32} />
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[13px] font-semibold">
              <span>Judge</span>
              <span className="font-mono text-[10px]" style={{ color: JUDGE_COLOR }}>
                VERDICT
              </span>
            </div>
            <div className="truncate text-[11px] text-muted">{judgeVoice ? judgeVoice : moderator ? shortModelName(moderator.model) : 'verdict'}</div>
          </div>
        </div>
      </div>
    </Card>
  );
};
