# REACT / FRONTEND RULES — Portable to Any React + Vite Project

## Component Architecture

- Hooks-first design: extract reusable logic into custom hooks (`useSystemStatus`, `useProperties`) before adding to components.
- Components should be < 200 lines. Split larger components into sub-components.
- Use PropTypes or TypeScript for all component props. Prefer TypeScript for new projects.
- Pages live in `pages/`, shared components in `components/`, custom hooks in `hooks/`.
- Avoid prop drilling beyond 2 levels — use context or state management if needed.

## State Management & Data Fetching

- API calls go through a shared API module (`src/api.js`), never raw `fetch()` in components.
- NEVER hardcode API URLs or keys in components. Use environment variables (`VITE_*` prefix for Vite).
- Loading and error states must be handled for every async operation.
- Empty states ("no properties found", "no results") must render meaningful UI, not blank pages.

## Security

- NEVER use `dangerouslySetInnerHTML` without sanitizing input through DOMPurify.
- User-facing messages must not expose internal errors or stack traces.
- All external links should use `rel="noopener noreferrer"` for `target="_blank"`.
- API keys exposed to the frontend via `VITE_*` prefixed env vars should be treated as **public** — they ship to the browser. Use admin API keys only behind a reverse proxy in production.

## CSS / Styling

- Use project-level CSS (`index.css`) for global resets and theme tokens (colors, typography, spacing).
- Component-specific styles may use CSS modules or inline styles via object literals.
- Mobile-responsive layout: all pages should be usable at 375px width.
- Dark mode support should be designed with CSS custom properties (variables), even if not yet implemented.

## Testing (Playwright + Vitest)

### E2E Tests (Playwright)
- Critical user flows covered: browse → filter → view property → trigger scrape.
- Mock API responses for deterministic tests; use real backend for full-stack integration tests.
- Use `page.route()` to intercept API calls and return fixture data.
- Screenshot comparison for visual regression on key pages.

### Component Tests (Vitest + React Testing Library)
- Test user interactions: clicking, typing, form submission.
- Test error and loading states explicitly.
- Avoid testing implementation details; test from the user's perspective.