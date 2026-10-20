import { describe, expect, it } from 'vitest';
import { FORMATS } from '../../lib/formats';
import { applyFormat, initialState } from './wizardState';

describe('applyFormat', () => {
  it('keeps the topic and its news story when the format changes', () => {
    const news = { topic_id: 't1', brief: 'Nvidia passed AMD in chip sales.', outlet: 'BBC', title: 'Nvidia passes AMD', url: 'https://example.com/a', published_at: null };
    const debate = { ...initialState(), topic: 'Should chipmakers be broken up?', description: 'Focus on prices.', news };
    const battle = applyFormat(debate, 'rap_battle');
    expect(battle.format).toBe('rap_battle');
    expect(battle.topic).toBe(debate.topic);
    expect(battle.news).toEqual(news);
    expect(battle.description).toBe('Focus on prices.');
    expect(applyFormat(battle, 'debate').topic).toBe(debate.topic);
  });
});

describe('topic lists', () => {
  it('give the rap battle its own news topics', () => {
    expect(FORMATS.debate.topicList).toBe('debate');
    expect(FORMATS.rap_battle.topicList).toBe('rap_battle');
  });
});
