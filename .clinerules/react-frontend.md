---
paths:
  - "frontend/**"
---

# React / Frontend Rules

## Component Architecture

- Hooks-first: extract reusable logic into custom hooks (`useSystemStatus`, `useProperties`) before adding to components.
- Components < 200 lines. Split larger ones into sub-components.
- Use PropTypes or TypeScript for all component props.
- Pages in `pages/`, shared components in `components/`, hooks in `hooks/`.
- Avoid prop drilling beyond 2 levels — use context or state management.

## State Management & Data Fetching

- API calls through `src/api.js`, never raw `fetch()` in components.
- NEVER hardcode API URLs or keys. Use `VITE_*` env vars.
- Loading and error states for every async operation.
- Empty states must render meaningful UI, not blank pages.

## Security

- NEVER use `dangerouslySetInnerHTML` without DOMPurify sanitization.
- User-facing messages must not expose internal errors or stack traces.
- All external links: `rel="noopener noreferrer"` for `target="_blank"`.
- `VITE_*` env vars are **public** (ship to browser). Admin keys behind reverse proxy only.

## CSS / Styling

- Global resets and theme tokens in `index.css`.
- Component-specific styles via CSS modules or inline style objects.
- Mobile-responsive: usable at 375px width.
- Dark mode via CSS custom properties.

## Playwright E2E

- Critical user flows: browse → filter → view property → trigger scrape.
- Mock API responses via `page.route()` for deterministic tests.
- Screenshot comparison for visual regression.
- Run: `npm run test:e2e --prefix frontend`.

## Vitest Component Tests

- Test user interactions: click, type, submit.
- Test error and loading states explicitly.
- Avoid testing implementation details — test from user's perspective.
