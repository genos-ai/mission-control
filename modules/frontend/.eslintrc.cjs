module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
  },
  plugins: ['@typescript-eslint', 'react-hooks', 'react-refresh'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    // TypeScript compiler already enforces unused vars with noUnusedLocals —
    // disable the ESLint duplicate so we don't double-report.
    '@typescript-eslint/no-unused-vars': 'off',
    // Allow explicit `any` in places where typing is genuinely hard
    '@typescript-eslint/no-explicit-any': 'warn',
    // Empty catch blocks are flagged by the pre-commit code_rules hook
    '@typescript-eslint/no-empty-function': 'off',
  },
  ignorePatterns: ['dist/', 'node_modules/'],
}
