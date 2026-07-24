import js from '@eslint/js'
import eslintReact from '@eslint-react/eslint-plugin'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

const reactRecommended = eslintReact.configs.recommended

export default [
  {
    ignores: ['dist', 'design-ref', 'coverage'],
  },
  {
    files: ['vite.config.js', '*.config.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.node,
    },
  },
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ...(reactRecommended.languageOptions || {}),
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.browser,
      parserOptions: {
        ...(reactRecommended.languageOptions?.parserOptions || {}),
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      ...(reactRecommended.plugins || {}),
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    settings: {
      ...(reactRecommended.settings || {}),
      'react-x': {
        ...(reactRecommended.settings?.['react-x'] || {}),
        version: 'detect',
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      ...(reactRecommended.rules || {}),
      ...reactHooks.configs.recommended.rules,
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]', argsIgnorePattern: '^_' }],
      'react-refresh/only-export-components': 'off',
    },
  },
]
