import { defineConfig } from 'vitest/config';

/** Unit tests of pure modules, no DOM (`npm test`). */
export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
});
