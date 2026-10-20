import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// Browser-only modules: Remotion, rough.js, d3-geo, the MP4 renderer, canvas work. Code that may
// render on the server reaches them only through `lazy()` inside <ClientOnly>; they may import
// each other. Type imports are fine everywhere.
const CLIENT_ONLY = [
  'src/video/**',
  'src/components/debate/DebatePlayer.tsx',
  'src/components/debate/SceneStill.tsx',
  'src/components/debate/ExportRail.tsx',
  'src/components/debate/ExportCard.tsx',
  'src/components/debate/PublishKit.tsx',
  'src/components/debate/youtubeKit.ts',
]

// The admin console: a separate SPA (src/admin-main.tsx), never part of the site's bundles.
const CONSOLE = ['src/admin-main.tsx', 'src/pages/admin/**', 'src/components/admin/**', 'src/api/admin/**', 'src/auth/AdminAuthContext.tsx']

const BROWSER_ONLY_IMPORTS = [
  {
    regex: '^(remotion|@remotion/.+|roughjs(/.*)?|d3-geo|topojson-client|world-atlas(/.*)?)$',
    allowTypeImports: true,
    message: 'Browser-only library: import it from a client-only module (eslint.config.js CLIENT_ONLY) loaded with lazy() inside <ClientOnly>.',
  },
  {
    regex: '(^|/)video/(?!(constants|timing)$)',
    allowTypeImports: true,
    message: 'src/video is browser-only (Remotion): use video/constants or video/timing, or lazy() inside <ClientOnly>.',
  },
  {
    regex: '(^|/)(DebatePlayer|SceneStill|ExportRail|ExportCard|PublishKit|youtubeKit)$',
    allowTypeImports: true,
    message: 'Browser-only component: load it with lazy() inside <ClientOnly>.',
  },
]

const CONSOLE_IMPORTS = [
  {
    regex: '(^|/)admin(/|$)|(^|/)AdminAuthContext$',
    message: 'Console code belongs to the admin SPA (src/admin-main.tsx), not to the site.',
  },
]

export default defineConfig([
  globalIgnores(['dist', 'build', '.react-router']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: [...CLIENT_ONLY, ...CONSOLE],
    rules: {
      '@typescript-eslint/no-restricted-imports': ['error', { patterns: [...BROWSER_ONLY_IMPORTS, ...CONSOLE_IMPORTS] }],
    },
  },
  {
    files: CLIENT_ONLY,
    rules: {
      '@typescript-eslint/no-restricted-imports': ['error', { patterns: CONSOLE_IMPORTS }],
    },
  },
  {
    // Route modules export React Router's hooks next to the component.
    files: ['src/root.tsx', 'src/routes/**/*.{ts,tsx}'],
    rules: {
      'react-refresh/only-export-components': [
        'error',
        { allowExportNames: ['loader', 'clientLoader', 'action', 'clientAction', 'middleware', 'clientMiddleware', 'headers', 'links', 'meta', 'handle', 'shouldRevalidate', 'ErrorBoundary', 'HydrateFallback', 'Layout'] },
      ],
    },
  },
  {
    // Node globals only in server modules and tests (the app's tsconfig has Node's types for them).
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/**/*.server.ts', 'src/**/*.server.tsx', 'src/**/*.test.ts'],
    rules: {
      'no-restricted-globals': ['error', { name: 'process', message: 'Server only: read it in a .server module.' }, { name: 'Buffer', message: 'Server only: use a .server module.' }],
    },
  },
])
