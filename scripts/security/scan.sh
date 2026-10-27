#!/usr/bin/env bash
# Run Nulavio's security scanners. They are pinned by version and SHA-256 and
# fetched by fetch_tools.sh; nothing is installed system-wide.
# docs/security/code-scanning.md explains each check and what to do with a finding.
#
#   scripts/security/scan.sh [check ...]      (default: every check, in this order)
#
#   - actionlint      GitHub Actions workflows: syntax, expressions, ShellCheck on run: blocks
#   - zizmor          GitHub Actions security audits (online audits too when GH_TOKEN is set)
#   - gitleaks        secrets in every commit of the history (.gitleaks.toml, .gitleaksignore)
#   - shellcheck      every shell script in the repository (tracked, or new and not ignored)
#   - opengrep        Nulavio's rules (ci/sast/nulavio-rules.yml) on the repository
#   - opengrep-rules  the same rules on their test cases (tests/fixtures/sast/)
#
#   scripts/security/scan.sh shell-files      list the files the shellcheck check reads
#
# Tools live in $NULAVIO_SECURITY_TOOLS, else $RUNNER_TEMP/nulavio-security-tools in
# GitHub Actions, else ~/.cache/nulavio-security-tools. Every check runs even when an
# earlier one fails. Exit status: 0 all passed, 1 a check failed, 2 usage error.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
all_checks=(actionlint zizmor gitleaks shellcheck opengrep opengrep-rules)

# Shell scripts in the repository (tracked, or new and not ignored by git): *.sh, or a
# sh/bash/dash/ksh "#!" line.
shell_files() {
    local file first
    while IFS= read -r -d '' file; do
        [[ -f $repo/$file && ! -L $repo/$file ]] || continue
        if [[ $file == *.sh ]]; then
            printf '%s\n' "$file"
            continue
        fi
        first=
        IFS= read -r -n 128 first <"$repo/$file" 2>/dev/null || true
        if [[ $first =~ ^#![[:space:]]*(/usr)?/bin/(env[[:space:]]+)?(ba|da|k)?sh([[:space:]]|$) ]]; then
            printf '%s\n' "$file"
        fi
    done < <(git -C "$repo" ls-files -z --cached --others --exclude-standard | sort -zu)
}

if [[ ${1-} == shell-files ]]; then
    shell_files
    exit 0
fi

checks=("$@")
if ((${#checks[@]} == 0)); then
    checks=("${all_checks[@]}")
fi
needed=()
for check in "${checks[@]}"; do
    case $check in
        actionlint) needed+=(actionlint shellcheck) ;;
        zizmor | gitleaks | shellcheck) needed+=("$check") ;;
        opengrep | opengrep-rules) needed+=(opengrep) ;;
        *)
            echo "scan: unknown check $check (known: ${all_checks[*]} shell-files)" >&2
            exit 2
            ;;
    esac
done

if [[ -n ${NULAVIO_SECURITY_TOOLS-} ]]; then
    tools=$NULAVIO_SECURITY_TOOLS
elif [[ -n ${RUNNER_TEMP-} ]]; then
    tools=$RUNNER_TEMP/nulavio-security-tools
else
    tools=${XDG_CACHE_HOME:-$HOME/.cache}/nulavio-security-tools
fi
mkdir -p "$tools"
tools=$(cd -- "$tools" && pwd)
mapfile -t needed < <(printf '%s\n' "${needed[@]}" | sort -u)
"$repo/scripts/security/fetch_tools.sh" "$tools" "${needed[@]}"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

run_opengrep() {
    # Opengrep unpacks its own libraries into XDG_CACHE_HOME: a fresh directory per run,
    # so it never loads files from an earlier run. No version check; it needs no network.
    mkdir -p "$scratch/opengrep/config" "$scratch/opengrep/cache"
    XDG_CONFIG_HOME=$scratch/opengrep/config XDG_CACHE_HOME=$scratch/opengrep/cache \
        "$tools/opengrep" "$@"
}

check_actionlint() {
    "$tools/actionlint" -shellcheck "$tools/shellcheck" -pyflakes ""
}

check_zizmor() {
    local mode=--offline
    if [[ -n ${GH_TOKEN-} ]]; then
        mode=  # online audits: impostor commits behind pinned SHAs, known-vulnerable actions
    fi
    "$tools/zizmor" ${mode:+"$mode"} --cache-dir "$scratch/zizmor" --no-progress --format plain .github/workflows
}

check_gitleaks() {
    if [[ $(git rev-parse --is-shallow-repository) == true ]]; then
        echo "gitleaks: this clone is shallow; the check needs every commit (actions/checkout: fetch-depth: 0)" >&2
        return 1
    fi
    "$tools/gitleaks" git --no-banner --redact --verbose \
        --config .gitleaks.toml --gitleaks-ignore-path .gitleaksignore .
}

check_shellcheck() {
    local files
    mapfile -t files < <(shell_files)
    echo "shellcheck: ${#files[@]} files"
    "$tools/shellcheck" -- "${files[@]}"
}

check_opengrep() {
    run_opengrep scan --config ci/sast/nulavio-rules.yml --disable-version-check \
        --error --strict --quiet .
}

check_opengrep_rules() {
    run_opengrep test --strict --config ci/sast/ tests/fixtures/sast/
}

cd "$repo"
failed=()
for check in "${checks[@]}"; do
    echo "== $check"
    if ! "check_${check//-/_}"; then
        failed+=("$check")
    fi
done
if ((${#failed[@]})); then
    echo "scan: failed: ${failed[*]} (see docs/security/code-scanning.md)" >&2
    exit 1
fi
echo "scan: passed: ${checks[*]}"
