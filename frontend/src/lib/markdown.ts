import { micromark } from 'micromark';
import { gfm, gfmHtml } from 'micromark-extension-gfm';

/**
 * Markdown of the models' turns and verdicts (GFM: tables, strikethrough, task lists, autolinks)
 * as HTML for `dangerouslySetInnerHTML`. micromark is safe by default: raw HTML in the text comes
 * out escaped and `javascript:`-style link targets are dropped. Same output on the server and in
 * the browser, so hydration keeps the server's markup. A table column's alignment becomes an
 * inline style (as react-markdown wrote it): the `align` attribute loses to `.prose`'s
 * `text-align: start`. Only micromark's own cell tags can match: quotes in text come escaped.
 */
export const markdownHtml = (text: string): string =>
  micromark(text, { extensions: [gfm()], htmlExtensions: [gfmHtml()] }).replace(/<(th|td) align="(left|center|right)">/g, '<$1 style="text-align:$2">');
