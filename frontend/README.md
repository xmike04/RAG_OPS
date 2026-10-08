# RAGOps operator console

React + TypeScript console for the RAGOps `/v1` API. The production default is
same-origin (`VITE_API_BASE_URL` is empty), while Vite proxies API requests to
`http://localhost:8000` during local development.

```bash
npm install
npm run dev
```

Optional build-time configuration:

- `VITE_API_BASE_URL`: API origin when it is not same-origin.
- `VITE_WORKSPACE_ID`: active workspace UUID. Defaults to
  `00000000-0000-0000-0000-000000000001`.
- `VITE_API_KEY`: API key when backend authentication is enabled.

Quality gates are `npm run lint`, `npm run typecheck`, `npm test`, and
`npm run build`. If the API cannot be reached, the UI uses an explicit,
prominently labeled demo fallback so sample telemetry cannot be mistaken for
live operational data.
