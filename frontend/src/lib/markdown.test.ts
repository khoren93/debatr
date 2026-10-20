import { describe, expect, it } from 'vitest';
import { markdownHtml } from './markdown';

describe('markdownHtml', () => {
  it('renders the Markdown the models write', () => {
    const html = markdownHtml('## Point\n\n**Bold**, *italic*, ~~gone~~ and `code`.\n\n- one\n- two\n\n1. first\n\n> quoted');
    expect(html).toContain('<h2>Point</h2>');
    expect(html).toContain('<strong>Bold</strong>, <em>italic</em>, <del>gone</del> and <code>code</code>.');
    expect(html).toContain('<ul>\n<li>one</li>\n<li>two</li>\n</ul>');
    expect(html).toContain('<ol>\n<li>first</li>\n</ol>');
    expect(html).toContain('<blockquote>\n<p>quoted</p>\n</blockquote>');
  });

  it('renders GFM tables and links', () => {
    const html = markdownHtml('| Side | Score |\n| --- | ---: |\n| For | 7 |\n\nSee [the study](https://example.com/a?b=1&c=2) and https://example.org.');
    expect(html).toContain('<table>');
    expect(html).toContain('<th align="right">Score</th>');
    expect(html).toContain('<td align="right">7</td>');
    expect(html).toContain('<a href="https://example.com/a?b=1&amp;c=2">the study</a>');
    expect(html).toContain('<a href="https://example.org">https://example.org</a>');
  });

  it('escapes raw HTML instead of passing it through', () => {
    const html = markdownHtml('Hi <script>alert(1)</script> <img src=x onerror=alert(1)>\n\n<iframe src="https://evil.example"></iframe>');
    expect(html).not.toMatch(/<script|<img|<iframe/);
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
  });

  it('drops dangerous link targets', () => {
    const html = markdownHtml('[click](javascript:alert(1)) [data](data:text/html;base64,PHNjcmlwdD4=) ![x](javascript:alert(2))');
    expect(html).not.toContain('javascript:');
    expect(html).not.toContain('data:text/html');
  });
});
