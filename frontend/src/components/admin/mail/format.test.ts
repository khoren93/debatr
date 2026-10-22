import { describe, expect, it } from 'vitest';
import { mailState } from './format';

describe('mailState', () => {
  it('says what the relay did before any report', () => {
    expect(mailState({ status: 'off', delivery: null }).label).toBe('not sent');
    expect(mailState({ status: 'failed', delivery: null }).tone).toBe('bad');
    expect(mailState({ status: 'sent', delivery: null })).toMatchObject({ label: 'sent', tone: 'plain' });
  });

  it('prefers what the sending service reported', () => {
    expect(mailState({ status: 'sent', delivery: 'delivered' })).toMatchObject({ label: 'delivered', tone: 'ok' });
    expect(mailState({ status: 'sent', delivery: 'complained' }).label).toBe('spam');
    expect(mailState({ status: 'sent', delivery: 'delayed' }).tone).toBe('wait');
  });
});
