# Implementation Plan — BIN-16: Toasts, error states & dynamic filters

## Goal
Replace blocking alert() calls with a toast system, drive neighbourhood filters from a new backend endpoint, and harden error states.

## Step-by-step
1. Create ToastProvider.jsx + useToast hook
2. Wire ToastProvider into App.jsx
3. Replace alert() in Dashboard.jsx with toasts
4. Add GET /neighborhoods backend endpoint
5. Wire dynamic neighbourhood filter in Properties.jsx + api.js
6. Harden error states in ScraperControl.jsx
7. Validate
