# Features

Implementation notes for each shipped feature, generated during the feature pipeline. These docs are useful for:

- **Agentic validation** — Cline reads these to know how to test a feature
- **Reference** — how each feature was implemented and what it changed

## Shipped

- [config-yaml-loader](config-yaml-loader.md) — Wire `app_config.yaml` into runtime config

## How feature docs are generated

When a feature is merged via `finish-feature.sh`, `gen-docs.sh` scaffolds a doc in this directory. The agent fills in the prose (Problem, Approach, Changes, How to test), then commits it.
