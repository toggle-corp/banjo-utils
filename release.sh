#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR

function release_custom_hook {
    # shellcheck disable=SC2154
    echo "No custom hook for: \"${version_tag#v}\""
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
