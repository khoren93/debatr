/** The `debatr` command-line client and MCP server (cli/ in the repository): install and setup
 *  snippets shown on the Account page. */

export const CLI_INSTALL = 'uv tool install debatr';
export const CLI_DOCS_URL = 'https://github.com/khoren93/debatr/tree/main/cli#readme';

/** Server the CLI talks to unless DEBATR_URL / --url say otherwise (cli/src/debatr/config.py). */
const CLI_DEFAULT_SITE = 'https://ai-debates.net';

/** This site, when the CLI has to be pointed at it (self-hosted or local), else null. */
export const customSite = (origin: string = window.location.origin): string | null => {
  const site = origin.replace(/\/+$/, '');
  return site === CLI_DEFAULT_SITE ? null : site;
};

export const loginSnippet = (site: string | null) => [CLI_INSTALL, site ? `debatr --url ${site} login` : 'debatr login'].join('\n');

export const envSnippet = (token: string, site: string | null) =>
  [`export DEBATR_TOKEN=${token}`, ...(site ? [`export DEBATR_URL=${site}`] : []), 'debatr whoami'].join('\n');

export const claudeCodeSnippet = (token: string, site: string | null) =>
  `claude mcp add debatr --scope user${site ? ` -e DEBATR_URL=${site}` : ''} -e DEBATR_TOKEN=${token} -- uvx debatr mcp`;

/** `mcpServers` entry for Claude Desktop, Cursor, Windsurf and other MCP clients. */
export const mcpJsonSnippet = (token: string, site: string | null) =>
  JSON.stringify(
    {
      mcpServers: {
        debatr: {
          command: 'uvx',
          args: ['debatr', 'mcp'],
          env: { DEBATR_TOKEN: token, ...(site ? { DEBATR_URL: site } : {}) },
        },
      },
    },
    null,
    2,
  );
