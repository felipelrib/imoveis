#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# docker-cleanup-lib.sh — pure helpers for temporary vs primary Compose images.
# Sourced by docker-cleanup.sh and unit tests. No Docker calls here.
# ---------------------------------------------------------------------------

# Override in tests or the environment; default matches scripts/lib.sh.
PRIMARY_COMPOSE_PROJECT="${PRIMARY_COMPOSE_PROJECT:-imoveis}"

# True when REPOSITORY looks like a disposable feature/worktree Compose image.
is_temporary_compose_image_repo() {
  local repo="$1"
  case "$repo" in
    "${PRIMARY_COMPOSE_PROJECT}-wt-"*) return 0 ;;
    feat-*|feature-*|fix-*|chore-*|test-*|refactor-*|docs-*|ci-*|build-*) return 0 ;;
    *) return 1 ;;
  esac
}

# True when REPOSITORY is a primary local stack image we always keep.
is_primary_compose_image_repo() {
  local repo="$1"
  case "$repo" in
    "${PRIMARY_COMPOSE_PROJECT}-wt-"*) return 1 ;;
    "${PRIMARY_COMPOSE_PROJECT}"|"${PRIMARY_COMPOSE_PROJECT}-"*) return 0 ;;
    *) return 1 ;;
  esac
}

# True when REPO is exactly PROJECT or PROJECT-<service> (one service segment).
# Avoids treating imoveis-wt-* as belonging to the primary project "imoveis".
repo_belongs_to_compose_project() {
  local repo="$1"
  local proj="$2"
  local rest

  [ -n "$proj" ] || return 1
  if [ "$repo" = "$proj" ]; then
    return 0
  fi
  case "$repo" in
    "${proj}-"*)
      rest="${repo#"${proj}-"}"
      # Compose image names are {project}-{service}; service is a single segment.
      case "$rest" in
        *[!a-zA-Z0-9_]*|"") return 1 ;;
        *) return 0 ;;
      esac
      ;;
    *) return 1 ;;
  esac
}

# True when a temporary image should be removed (temp, not primary, not active).
# active_projects_newline_list: newline-separated compose project names.
should_remove_temporary_image_repo() {
  local repo="$1"
  local active_projects="${2:-}"
  local proj

  is_temporary_compose_image_repo "$repo" || return 1
  is_primary_compose_image_repo "$repo" && return 1

  while IFS= read -r proj; do
    [ -n "$proj" ] || continue
    if repo_belongs_to_compose_project "$repo" "$proj"; then
      return 1
    fi
  done <<< "$active_projects"

  return 0
}
