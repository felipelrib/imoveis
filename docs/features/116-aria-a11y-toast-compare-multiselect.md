# ARIA Live Region + Keyboard Handling — ToastProvider, CompareView, SearchableMultiSelect

> Feature branch: `feat/aria-a11y-toast-compare-multiselect` · Linear: `BIN-157` · Status: implemented

## Problem

Three small, independent a11y gaps from the 2026-07-29 technical debt audit follow-up pass (epic BIN-128), bundled into one ticket — the same low-effort-bundle pattern as BIN-143's reliability bundle:

1. **`ToastProvider.jsx`**: toasts (including credential-invalid and save/enrichment error messages) rendered as plain `<div onClick>` — no `role`/`aria-live`, not focusable, no keyboard dismiss. Screen-reader users got no announcement at all when a toast appeared, and keyboard-only users could not dismiss one early.
2. **`CompareView.jsx`**: had `role="dialog" aria-modal="true"` but no focus trap, no initial-focus management, and no `Escape`-to-close — inconsistent with `PropertyModal.jsx` (which already handles `Escape` via a `window` keydown listener).
3. **`SearchableMultiSelect.jsx`**: closed only on outside-mousedown; no `Escape`-to-close and no arrow-key roving within the open listbox.

## Approach

1. **Toasts** — each toast `<div>` gained `role="status"` + `aria-live="polite"` (redundant but explicit, matching the ticket's ask) so screen readers announce new toasts as they mount. Made each toast focusable (`tabIndex={0}`) and keyboard-dismissible: `Enter`, `Space`, or `Escape` calls the existing `removeToast(id)`, same function the mouse `onClick` already used — no behavior change for mouse users. The decorative icon span got `aria-hidden="true"` so only the message text is announced. `ToastProvider` sits **above** `LocaleProvider` in `App.jsx` (so its own toast container can't call `useT()`), so the new `aria-label` hint text is a plain hardcoded string rather than a translation key.
2. **CompareView** — mirrored `PropertyModal.jsx`'s existing `window`-level `keydown` + `Escape` pattern (a `useEffect` with `window.addEventListener('keydown', ...)`), wired to the same `onClose` prop the "Back to Grid" button already calls — pressing Escape now behaves identically to clicking that button (keeps the compare selection, just closes the dialog). Added a standard Tab focus trap: a `dialogRef` on the dialog root, and the same keydown handler recomputes the dialog's focusable elements (`a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])`) on every `Tab` press and wraps `Shift+Tab` from the first element to the last (and `Tab` from the last back to the first). A second, mount-only effect moves initial focus onto the first focusable element in the dialog (the "Back to Grid" button) when it opens, satisfying "no initial-focus management" from the ticket.
3. **SearchableMultiSelect** — added an `onKeyDown` handler on the component root (bubling handles input + option buttons without per-element wiring): `Escape` closes the dropdown, clears the search text, and returns focus to the trigger button (new `triggerRef`); `ArrowDown`/`ArrowUp` (only while open) move a roving `activeIndex` over the flattened, group-order-preserving option list (`grouped.flatMap(g => g.items)`), wrapping at both ends; `Enter` toggles the currently active option. The active option gets a visible `.sms-option--active` outline and an `id`; the search `<input>` gained `role="combobox"` + `aria-expanded` + `aria-activedescendant` pointing at that id, so assistive tech tracks the roving highlight. `activeIndex` resets to `-1` at every point that changes `search`/`open` (trigger click, search `onChange`, outside-click, `Escape`) rather than in a `useEffect` — an initial implementation used a `useEffect` keyed on `[search, open]` to reset it, which tripped the `react-hooks/set-state-in-effect` ESLint rule (`Calling setState synchronously within an effect can trigger cascading renders`); resetting inline at the actual state-changing call sites is the recommended fix and avoids an extra render pass.

## Changes

Files touched:

```
frontend/src/components/ToastProvider.jsx                          | role="status" + aria-live="polite" + tabIndex + Enter/Space/Escape keyboard dismiss on each toast
frontend/src/components/CompareView.jsx                            | dialogRef + initial-focus effect + Escape-to-close/Tab focus-trap effect (mirrors PropertyModal.jsx)
frontend/src/components/SearchableMultiSelect.jsx                  | Escape-to-close (+ refocus trigger), ArrowUp/ArrowDown roving highlight, Enter-to-toggle, aria-activedescendant/role=combobox on the search input
frontend/src/index.css                                             | NEW .sms-option--active outline style for the roving keyboard highlight
frontend/tests/e2e/compare-view.spec.js                            | NEW — Escape closes the compare dialog and keeps selection; opening the dialog moves focus in and Tab wraps within it
frontend/tests/e2e/properties-city-neighborhood-filters.spec.js    | NEW — Escape closes the neighborhood dropdown and refocuses its trigger; ArrowDown highlights + Enter toggles the option
frontend/tests/e2e/credential-gate.spec.js                         | NEW — the credential-invalid error toast is a role=status/aria-live=polite region and is dismissible via Escape after focusing it
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

- `frontend/tests/e2e/compare-view.spec.js` — "Escape closes the compare dialog and keeps selection" and "opening the compare dialog moves focus inside it and traps Tab" are new regression specs for items 2's Escape handling and focus trap/initial focus.
- `frontend/tests/e2e/properties-city-neighborhood-filters.spec.js` — "Escape closes the dropdown and returns focus to the trigger" and "ArrowDown/ArrowUp roves the listbox and Enter toggles the highlighted option" cover item 3.
- `frontend/tests/e2e/credential-gate.spec.js` — "error toast is announced and keyboard-dismissible" covers item 1 (`role="status"`/`aria-live="polite"` + `Escape` dismiss) using the existing credential-invalid toast flow.
- Full existing Playwright suite (75 specs) re-run unchanged and green — no existing spec asserted on the previous absence of Escape/arrow-key handling, so no test needed to be modified, only extended.

## Notes / Follow-ups

- `ToastProvider` is intentionally mounted outside `LocaleProvider` in `App.jsx` (so toasts can be shown even if locale/i18n setup ever fails); the new keyboard-dismiss `aria-label` hint is therefore a hardcoded English string rather than a translated key. If `ToastProvider` is ever moved inside `LocaleProvider`, that string should move into the i18n catalog.
- The `SearchableMultiSelect` focus/highlight code does not attempt full ARIA `listbox`/`combobox` spec compliance (e.g. it does not manage `aria-owns` or type-ahead beyond the existing text filter) — scoped to the ticket's explicit ask (Escape + arrow-key roving), matching the "low individual effort" framing shared with BIN-143.
- Related: BIN-143 (reliability quick-fixes bundle, same audit pass, same bundling pattern).
