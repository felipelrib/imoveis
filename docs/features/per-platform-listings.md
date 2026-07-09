# Per-Platform Listings with Price Comparison

## Overview

Enhanced the Properties UI to display per-platform prices with attribution on property cards, and added a grouped listings table in the PropertyModal for easy cross-platform price comparison.

## Problem

The Properties page showed a single price per property card and simple "ALUGUEL"/"VENDA" tags. Users couldn't compare prices across platforms or see which platform offers the best deal for rent vs sale listings.

## What Changed

### Property Card (`Properties.jsx`)

- Cards now group listings by listing type (rent/sale)
- For each type, the **best price** (lowest) is displayed with the platform name
- When both rent and sale exist, both are shown with independent prices
- A "2 plataformas" badge appears when a property is listed on multiple platforms
- Falls back to `p.price` when no listings array is available

### Property Modal (`PropertyModal.jsx`)

- Added a **"Listings by Platform"** section grouped by listing type
- Each group shows a table with: Platform, Price, Condo Fee, IPTU, Furnished, Pets, Link
- Best price rows are highlighted with a green background
- Each listing links to the original platform URL

### CSS (`index.css`)

- New `.listings-table` styles for the comparison table
- `.best-price` row highlighting (subtle green)
- `.listing-link` button style for platform links

## Technical Details

- **Frontend-only change** — no backend modifications needed
- The API already returns `listings` array with per-platform data
- Backward compatible: properties without `listings` fall back to `p.price`

## Files Changed

- `frontend/src/pages/Properties.jsx` — Card redesign with per-listing-type prices
- `frontend/src/components/PropertyModal.jsx` — Listings table with links and best-price highlight
- `frontend/src/index.css` — New styles for listings table and price comparison

## Validation

- `validate.sh frontend` passed (build OK)
- `validate.sh all` passed (lint, unit, integration, contract, frontend)
- 134 unit tests passed, 22 integration tests passed, 6 contract tests passed
