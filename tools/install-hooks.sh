#!/usr/bin/env bash
# Installs the git hooks that keep personal data out of commits: before each commit the staged files go through
# tools/leakscan.py, and each commit message too (no personal values, no private tracker ids). CI runs the same
# scan on every push and pull request; these hooks catch it before it is even committed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS="$(git -C "$ROOT" rev-parse --git-path hooks)"
mkdir -p "$HOOKS"
cat > "$HOOKS/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# bobina: personal-data scan of the staged files (tools/install-hooks.sh)
set -euo pipefail
files=()
while IFS= read -r f; do [ -f "$f" ] && files+=("$f"); done < <(git diff --cached --name-only --diff-filter=ACMR)
[ ${#files[@]} -eq 0 ] && exit 0
exec python3 tools/leakscan.py "${files[@]}"
HOOK
cat > "$HOOKS/commit-msg" <<'HOOK'
#!/usr/bin/env bash
# bobina: personal-data scan of the commit message (tools/install-hooks.sh)
exec python3 tools/leakscan.py "$1"
HOOK
chmod +x "$HOOKS/pre-commit" "$HOOKS/commit-msg"
echo "hooks installed in $HOOKS (pre-commit, commit-msg)"
