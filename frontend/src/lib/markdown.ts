import { micromark } from 'micromark';
import { gfm, gfmHtml } from 'micromark-extension-gfm';

/**
 * Markdown of the models' turns and verdicts (GFM: tables, strikethrough, task lists, autolinks)
 * as HTML for `dangerouslySetInnerHTML`. micromark is safe by default: raw HTML in the text comes
 * out escaped and `javascript:`-style link targets are dropped. Same output on the server and in
 * the browser, so hydration keeps the server's markup.
 */
export const markdownHtml = (text: string): string => micromark(text, { extensions: [gfm()], htmlExtensions: [gfmHtml()] });
