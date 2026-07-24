// Canonical lint entrypoint. Accessibility is enforced against rendered DOM
// in redesign/accessibility.test.jsx using Axe, which observes semantic
// relationships and ARIA behavior beyond source-only JSX inspection.
import base from './eslint.config.js'

export default base
