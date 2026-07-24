// Canonical lint entrypoint. Accessibility is additionally enforced against
// rendered DOM in redesign/accessibility.test.jsx using Axe, which catches
// semantic relationships that source-only JSX rules cannot observe.
import base from './eslint.config.js'

export default base
