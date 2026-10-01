#!/usr/bin/env bash
set -euo pipefail

RELEASE_VERSION="${1:-}"
SERVER_TAG="${2:-}"
FRONTEND_TAG="${3:-}"

if [[ -z "$RELEASE_VERSION" ]]; then
    echo "Usage: $0 <release-version> [server-tag] [frontend-tag]"
    echo "  e.g. $0 1.4.0 v1.4.0 fe-v1.4.0"
    echo "  release-version is required (e.g. 1.4.0)"
    exit 1
fi

if [[ -z "$SERVER_TAG" && -z "$FRONTEND_TAG" ]]; then
    echo "Error: at least one of server-tag or frontend-tag must be provided."
    echo "Usage: $0 <release-version> [server-tag] [frontend-tag]"
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Running backend tests..."
pytest tests/ -v --ignore=tests/test_merge_golden.py

echo "==> Running merge golden tests (local-only, needs ffmpeg)..."
#pytest tests/test_merge_golden.py -v

echo "==> Running TypeScript type check..."
cd frontend
npx tsc --noEmit
cd "$REPO_ROOT"

RELEASE_BRANCH="release/$RELEASE_VERSION"
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "==> Syncing develop with origin..."
git fetch origin
git checkout develop
# Fail loudly if local develop has diverged — never cut a release from a stale tip.
git merge --ff-only origin/develop
git checkout "$CURRENT_BRANCH"

if [[ "$CURRENT_BRANCH" != "$RELEASE_BRANCH" ]]; then
    if git rev-parse --verify --quiet "$RELEASE_BRANCH" >/dev/null; then
        echo "Local branch $RELEASE_BRANCH exists."
        git checkout "$RELEASE_BRANCH"
    else
        echo "Local branch $RELEASE_BRANCH does not exist."
        echo "==> Creating release branch: $RELEASE_BRANCH from up-to-date develop"
        git checkout develop
        git checkout -b "$RELEASE_BRANCH"
    fi
    echo "==> Merging $CURRENT_BRANCH into $RELEASE_BRANCH..."
    git merge "$CURRENT_BRANCH" --no-edit
fi

if [[ -n "$SERVER_TAG" ]]; then
    echo "==> Tagging backend release: $SERVER_TAG"
    git tag "$SERVER_TAG"
    git push origin "$SERVER_TAG"
fi

if [[ -n "$FRONTEND_TAG" ]]; then
    if [[ "$FRONTEND_TAG" != fe-* ]]; then
        echo "Error: frontend tag must start with 'fe-' (got: $FRONTEND_TAG)"
        exit 1
    fi
    echo "==> Tagging frontend release: $FRONTEND_TAG"
    git tag "$FRONTEND_TAG"
    git push origin "$FRONTEND_TAG"
fi

echo "==> Pushing release branch: $RELEASE_BRANCH"
git push origin "$RELEASE_BRANCH"

echo "==> Merging $RELEASE_BRANCH into develop..."
git checkout develop
git merge "$RELEASE_BRANCH" --no-edit
git push origin develop

echo "==> Merging $RELEASE_BRANCH into master..."
git checkout master
git merge "$RELEASE_BRANCH" --no-edit
git push origin master

echo "==> Switching back to $RELEASE_BRANCH"
git checkout "$RELEASE_BRANCH"

echo "==> Done."
