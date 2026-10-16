const path = require('path')

module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
  },
  plugins: ['@typescript-eslint', 'react-hooks', 'react-refresh', 'tailwindcss'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  settings: {
    // Absolute: the plugin resolves the tailwindcss package from the config's
    // directory, so a relative path resolves from '.' and fails.
    tailwindcss: { config: path.join(__dirname, 'tailwind.config.js') },
  },
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    // TypeScript compiler already enforces unused vars with noUnusedLocals —
    // disable the ESLint duplicate so we don't double-report.
    '@typescript-eslint/no-unused-vars': 'off',
    // Allow explicit `any` in places where typing is genuinely hard
    '@typescript-eslint/no-explicit-any': 'warn',
    // Empty catch blocks are flagged by the pre-commit code_rules hook
    '@typescript-eslint/no-empty-function': 'off',
    // Plan 87: Tailwind drops unknown classes silently, so a typo or an
    // undefined token renders nothing. Fail the lint instead. Only this rule
    // is on: the plugin's class-ordering rules would reformat every file.
    'tailwindcss/no-custom-classname': 'error',
  },
  ignorePatterns: ['dist/', 'node_modules/'],
}
