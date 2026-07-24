// Lint entrypoint = base config + the JSX accessibility guardrail.
//
// The maintained HTML Academy fork mirrors upstream jsx-a11y rules while
// supporting ESLint 10 and Node 24. Flat-config composition keeps every base
// rule and layers the recommended accessibility set on top.
import base from './eslint.config.js'
import jsxA11y from '@htmlacademy/eslint-plugin-jsx-a11y'

export default [
  ...base,
  { ignores: ['coverage'] },
  {
    files: ['**/*.{js,jsx}'],
    plugins: { 'jsx-a11y': jsxA11y },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
    },
  },
]
