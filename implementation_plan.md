# Implementation Plan: Docs & Linear Workflow Restructure

## Goal

Restructure the project's documentation and workflow to make Linear the single source of truth for feature tracking, while keeping useful docs in the repo for Cline's agentic validation and publishing them via GitHub Pages with MkDocs Material.

## Affected Areas

- `FEATURES.md` — slim down to dispatch-only pointer
- `docs/` — reorganize into MkDocs structure
- `mkdocs.yml` — new file, MkDocs Material config
- `.github/workflows/docs.yml` — new file, GitHub Actions docs deployment
- `.clinerules/workflow.md` — update to reference Linear instead of FEATURES.md
- `docs/local_agent_architecture.md` — rewrite for Cline (not Goose)
- `scripts/agent/gen-docs.sh` — update for MkDocs nav
- `README.md` — update docs section

## Step-by-step Implementation

### Step 1: Create `mkdocs.yml` at repo root
MkDocs Material configuration with nav structure pointing to existing docs.

### Step 2: Reorganize `docs/` directory
- `docs/index.md` — new landing page (moved from README content)
- `docs/setup.md` — slimmed down SETUP_GUIDE.md
- `docs/architecture.md` — rewritten from local_agent_architecture.md
- `docs/features/` — keep existing pattern (implementation notes per feature)
- Archive DEPLOYMENT_GUIDE.md, MODEL_QUANTIZATION.md, rocm_directml_setup.md content to Linear issues (BIN-27/28/29)

### Step 3: Slim down `FEATURES.md`
- Remove feature table and all specs (they're in Linear)
- Keep: dispatch instructions, tier reference, link to Linear board
- ~363 lines → ~50 lines

### Step 4: Update `.clinerules/workflow.md`
- Change "Read FEATURES.md" to "Read Linear board via MCP"
- Update planning workflow to reference Linear issues
- Update finish-feature to mention Linear status updates

### Step 5: Update `.clinerules/project.md`
- Update feature tracking section to reference Linear as primary

### Step 6: Add GitHub Actions workflow for docs deployment
- `.github/workflows/docs.yml` — build and deploy MkDocs Material to GitHub Pages

### Step 7: Update `scripts/agent/gen-docs.sh`
- Update to work with MkDocs nav structure
- Auto-add new feature docs to mkdocs.yml nav

### Step 8: Update `README.md`
- Update documentation section to reference MkDocs site
- Keep quickstart and architecture pointers

## Validation

- `mkdocs build` should succeed
- All existing docs should be accessible
- FEATURES.md should be concise and point to Linear
- .clinerules should reference Linear consistently
</parameter>
</write_to_file>