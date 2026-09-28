# ClippyMe dashboard

The web UI: React 18, Vite 6, Tailwind CSS v4. It runs in the `frontend`
container started by `docker compose up` (Vite dev server on port 5175,
proxying `/api`, `/videos`, `/thumbnails` and `/fonts` to the backend).

| Path | Contents |
|------|----------|
| `src/redesign/` | All screens and components; `RedesignApp.jsx` wires top-level state |
| `src/hooks/` | Side effects: job submission and polling, manual trim, history, session |
| `src/lib/` | Pure logic, unit-tested |
| `Dockerfile` / `Dockerfile.prod` + `nginx.conf` | Dev server image / static production build served by nginx |

```bash
npm ci
npm run lint    # ESLint (entrypoint eslint.a11y.config.js)
npm test        # Vitest + jsdom, including an Axe accessibility test
npm run build
```

Project-wide setup, testing and rules: [CONTRIBUTING.md](../CONTRIBUTING.md).
