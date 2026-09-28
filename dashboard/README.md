# ClippyMe dashboard

The web UI: React 18, Vite 6, Tailwind CSS v4. It runs in the `frontend`
container started by `docker compose up` (Vite dev server on port 5175,
proxying `/api`, `/videos`, `/thumbnails` and `/fonts` to the backend).

| Path | Contents |
|------|----------|
| `src/main.jsx` | Entry point |
| `src/app/` | `App.jsx` wires top-level state and navigation; error boundary; the Axe accessibility test |
| `src/features/` | One folder per screen or flow: `create`, `processing`, `results`, `clip-editor`, `publishing`, `live-monitor`, `history-settings`. Each holds its components, feature-only logic and tests |
| `src/components/` | UI shared across features: `primitives.jsx`, `icon.jsx`, `LazyVideo.jsx`, `chrome.jsx` (top nav); `controls/` holds the subtitle, logo, grade, banner and hook controls shared by Create, the clip editor and Live |
| `src/api/` | Backend client: `client.js` (most endpoints), `jobs.js` (submit and poll), `apiToken.js`, `config.js` (API base URL) |
| `src/hooks/` | Cross-feature side effects: job submission and polling, history, session, clip states, backend status, fonts, modal focus trap |
| `src/lib/` | Cross-feature pure logic, unit-tested; `data.js` holds the option catalogs and defaults mirrored by the backend |
| `src/styles/` | `index.css` (Tailwind entry), `tokens.css` (design tokens, fonts), `app.css` (the visual system) |
| `src/assets/` | Images bundled by Vite |
| `Dockerfile` / `Dockerfile.prod` + `nginx.conf` | Dev server image / static production build served by nginx |

```bash
npm ci
npm run lint    # ESLint (entrypoint eslint.a11y.config.js)
npm test        # Vitest + jsdom, including an Axe accessibility test
npm run build
```

Project-wide setup, testing and rules: [CONTRIBUTING.md](../CONTRIBUTING.md).
