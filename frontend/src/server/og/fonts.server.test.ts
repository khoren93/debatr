import { describe, expect, it } from 'vitest';
import { headlineSize } from './card.server';
import { fontStack, parseUnicodeRange, scriptFamilies } from './fonts.server';

describe('preview card fonts', () => {
  it("reads fontsource's unicode ranges", () => {
    expect(parseUnicodeRange('U+0460-052F,U+1C80-1C8A, U+20B4')).toEqual([
      [0x460, 0x52f],
      [0x1c80, 0x1c8a],
      [0x20b4, 0x20b4],
    ]);
    expect(parseUnicodeRange('')).toEqual([]);
  });

  it('fetches fonts only for the scripts the bundle lacks', () => {
    expect(scriptFamilies('Is remote work better? Лучше ли? هل? क्या? Արդյո՞ք? 🍍', 'en')).toEqual([]);
    expect(scriptFamilies('リモートワークは良いか？', 'ja')).toEqual(['Noto Sans JP']);
    expect(scriptFamilies('원격 근무가 나은가?', 'ko')).toEqual(['Noto Sans KR']);
    expect(scriptFamilies('远程工作更好吗？', 'zh')).toEqual(['Noto Sans SC']);
    expect(scriptFamilies('遠程工作更好嗎？', 'zh-TW')).toEqual(['Noto Sans TC']);
    expect(scriptFamilies('生産性', 'ja')).toEqual(['Noto Sans JP']);
    expect(scriptFamilies('งานทางไกล', 'th')).toEqual(['Noto Sans Thai']);
  });

  it('falls back through the bundled scripts to the fetched ones and emoji', () => {
    expect(fontStack('Bricolage Grotesque', ['Noto Sans JP'])).toBe('"Bricolage Grotesque", "Noto Sans", "Noto Sans Armenian", "Noto Sans Arabic", "Noto Sans Hebrew", "Noto Sans JP", "Twemoji"');
  });

  it('sizes the headline to fit up to three lines', () => {
    expect(headlineSize('Tabs or spaces?')).toBe(74);
    expect(headlineSize('Is remote work better than the office?')).toBe(66);
    expect(headlineSize('x'.repeat(160))).toBe(41);
    // Wide characters count about double.
    expect(headlineSize('人工智能应该像药品一样受到监管吗？')).toBeLessThan(headlineSize('Should AI be regulated?'));
  });
});
