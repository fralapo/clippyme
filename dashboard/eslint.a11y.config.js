// Canonical lint entrypoint. Source-level JSX accessibility rules are layered
// over the base React config, while redesign/accessibility.test.jsx uses Axe
// to verify semantic relationships in the rendered DOM.
import base from './eslint.config.js'
import jsxA11y from 'eslint-plugin-jsx-a11y'

export default [
  ...base,
  {
    files: ['**/*.{js,jsx}'],
    plugins: { 'jsx-a11y': jsxA11y },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
    },
  },
]
