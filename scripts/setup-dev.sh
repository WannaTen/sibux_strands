#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Initialize the local development environment for this repository.

Usage:
  ./scripts/setup-dev.sh [options]

Options:
  --git-user-name <name>    Set git user.name in this repository only
  --git-user-email <email>  Set git user.email in this repository only
  --verify                  Run pre-commit checks on all files after setup
  -h, --help                Show this help message

Examples:
  ./scripts/setup-dev.sh
  ./scripts/setup-dev.sh --verify
  ./scripts/setup-dev.sh --git-user-name "Jane Doe" --git-user-email "jane@example.com"
EOF
}

require_command() {
    local command_name="$1"

    if ! command -v "${command_name}" >/dev/null 2>&1; then
        printf 'error: required command not found: %s\n' "${command_name}" >&2
        exit 1
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GIT_USER_NAME=""
GIT_USER_EMAIL=""
RUN_VERIFY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --git-user-name)
            if [[ $# -lt 2 ]]; then
                printf 'error: %s requires a value\n' "$1" >&2
                exit 1
            fi
            GIT_USER_NAME="$2"
            shift 2
            ;;
        --git-user-email)
            if [[ $# -lt 2 ]]; then
                printf 'error: %s requires a value\n' "$1" >&2
                exit 1
            fi
            GIT_USER_EMAIL="$2"
            shift 2
            ;;
        --verify)
            RUN_VERIFY=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'error: unknown option: %s\n' "$1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

require_command git
require_command uv

cd "${REPO_ROOT}"

printf '[1/4] syncing development dependencies\n'
uv sync --frozen --group dev

printf '[2/4] installing git hooks\n'
uv run pre-commit install -t pre-commit -t commit-msg

printf '[3/4] configuring repository-local git settings\n'
git config --local pull.rebase true

if [[ -n "${GIT_USER_NAME}" ]]; then
    git config --local user.name "${GIT_USER_NAME}"
fi

if [[ -n "${GIT_USER_EMAIL}" ]]; then
    git config --local user.email "${GIT_USER_EMAIL}"
fi

CURRENT_GIT_USER_NAME="$(git config --get user.name || true)"
CURRENT_GIT_USER_EMAIL="$(git config --get user.email || true)"

if [[ -z "${CURRENT_GIT_USER_NAME}" || -z "${CURRENT_GIT_USER_EMAIL}" ]]; then
    printf 'warning: git user.name or user.email is not configured\n' >&2
    printf 'warning: rerun with --git-user-name/--git-user-email, or configure git manually\n' >&2
fi

printf '[4/4] setup complete\n'
printf 'repository: %s\n' "${REPO_ROOT}"
printf 'git hooks: pre-commit, commit-msg\n'

if [[ "${RUN_VERIFY}" -eq 1 ]]; then
    printf 'running pre-commit checks on all files\n'
    uv run pre-commit run --all-files
fi

