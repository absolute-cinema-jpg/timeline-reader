#!/usr/bin/env bash
# Create an isolated git worktree + branch for a parallel session.
#
# Each worktree is its own folder with its own checked-out branch and staging
# area, so parallel sessions never overwrite each other's edits or tangle their
# commits. They share this repo's history and — via a symlink — the installed
# virtualenv, so there's no multi-hundred-MB reinstall per worktree.
#
#   Usage:   ./new-worktree.sh <name> [base-branch]
#   Example: ./new-worktree.sh captions      # -> ../timeline-reader-captions (branch session/captions)
#
#   List:    git worktree list
#   Remove:  git worktree remove ../timeline-reader-<name>   # after merging its branch
set -euo pipefail
cd "$(dirname "$0")"

name="${1:-}"
if [ -z "$name" ]; then
  echo "usage: ./new-worktree.sh <name> [base-branch]" >&2
  exit 1
fi
base="${2:-main}"
slug="$(printf '%s' "$name" | tr ' /' '--')"
dir="../timeline-reader-${slug}"
branch="session/${slug}"

if [ -e "$dir" ]; then
  echo "Error: $dir already exists." >&2
  exit 1
fi

git worktree add -b "$branch" "$dir" "$base"

# Share the installed dependencies rather than reinstalling them per worktree.
# `python -m timeline_reader` run from the worktree still uses that worktree's
# own source (cwd wins), so only the packages are shared, never the code.
if [ -d .venv ] && [ ! -e "$dir/.venv" ]; then
  ln -s "$(cd .venv && pwd -P)" "$dir/.venv"
  echo "Linked shared .venv into the worktree."
fi

cat <<EOF

✓ Worktree ready
   folder:  $dir
   branch:  $branch  (off $base)

Point a session at it:   cd "$dir" && ./run.sh
Merge when done:         git switch main && git merge $branch
Remove the worktree:     git worktree remove "$dir"

Note: the shared .venv means 'pip install' in one worktree affects all of them.
If a session needs different dependencies, delete its .venv symlink and run
'./run.sh' there to build a dedicated one.
EOF
