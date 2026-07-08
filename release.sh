#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR

function release_custom_hook {
    # shellcheck disable=SC2154
    local version="${version_tag#v}"
    sed -i -E "s/^version = \".*\" # managed by release.sh$/version = \"${version}\" # managed by release.sh/" "$SCRIPT_DIR/pyproject.toml"
    git add "$SCRIPT_DIR/pyproject.toml"
    # Refresh the lockfile so it reflects the new version (no-op if already in sync)
    uv lock --project "$SCRIPT_DIR"
    git add "$SCRIPT_DIR/uv.lock"
}

export -f release_custom_hook
export START_COMMIT=755a25a85fbe50d0f359378d297b3e8cba801686
export RELEASE_CUSTOM_HOOK=release_custom_hook
export REPO_NAME=toggle-corp/banjo-utils
export DEFAULT_BRANCH=main

export GIT_CLIFF__REMOTE__GITHUB__OWNER=toggle-corp
export GIT_CLIFF__REMOTE__GITHUB__REPO=banjo-utils

# Forward the argument - used for pre-fill version
"$SCRIPT_DIR/fugit/scripts/release.sh" "${@:-}"
