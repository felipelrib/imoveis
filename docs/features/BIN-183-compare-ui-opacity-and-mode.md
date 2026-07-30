# Compare UI opacity, activate mode, and watchlist icon

> Feature branch: `fix/ui-compare-opacity-icons` · Linear: `BIN-183` · Status: implemented

## Problem

The side-by-side compare overlay used an undefined CSS variable (`--bg-primary`), so the grid bled through the comparison page. The floating selection bar and saved-searches sidebar used near-transparent `--bg-card` (~4% white), so text was hard to read. Compare checkboxes were always visible on every card, cluttering browse mode. Favourites and “Watch for price drops” both used a star icon when inactive, so the actions were indistinguishable.

## Approach

- Give compare view, compare bar, and saved-searches sidebar solid `--bg-surface` / `--bg-base` backgrounds (opaque).
- Gate multi-select behind an explicit toolbar **Compare** mode toggle; hide checkboxes until activated; **Clear & exit** also leaves the mode.
- Use `📉` (inactive) / `🔔` (active) for price-drop watch so it never shares the favourites star.

## Changes

Files touched:

```
 frontend/src/index.css                                 | FIX — opaque compare view/bar/sidebar/modal
 frontend/src/pages/Properties.jsx                      | ADD compare mode toggle; hide checkboxes; watch icon
 frontend/src/components/PropertyModal.jsx              | FIX watchlist icon (📉/🔔)
 frontend/tests/e2e/compare-select.spec.js              | UPDATE mode gate + opacity + icon regression
 frontend/tests/e2e/compare-view.spec.js                | UPDATE mode gate + opaque compare-view assert
 docs/features/BIN-183-compare-ui-opacity-and-mode.md        | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Open Properties → confirm no checkboxes on cards.
2. Click **⇄ Compare** → select 2 cards → selection bar readable over the grid → **Compare**.
3. Confirm compare page fully covers the grid (no bleed-through).
4. Confirm favourites stays ★/☆ and watch uses 📉/🔔.
5. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Glassmorphic `--bg-card` remains intentional for dashboard cards; overlays and sticky chrome that sit on busy content should stay solid.
- Deep-link compare routes (if/when merged from BIN-82) should auto-enter compare mode when opening a share URL.
