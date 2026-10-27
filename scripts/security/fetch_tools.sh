#!/usr/bin/env bash
# Download the pinned security scanners into DIR and check each SHA-256 before use.
# Nothing is installed system-wide: DIR is a cache (CI: under $RUNNER_TEMP; locally
# ~/.cache/nulavio-security-tools, see scan.sh). Linux x86_64 only.
#
#   scripts/security/fetch_tools.sh DIR [tool ...]     (default: every tool)
#
# Each run checks the cached download against the pinned SHA-256 again and
# re-extracts the executable from it, so a changed cache is never executed.
#
# Bump a tool: change its version, URL and SHA-256 together, in one commit that
# says why. Take the SHA-256 from the release's checksum file (actionlint,
# gitleaks) and compare it with the digest GitHub shows for the asset; for
# Opengrep, also check the cosign signature (the asset's .sig and .cert; identity
# https://github.com/opengrep/opengrep/.github/workflows/rolling-release.yml@refs/heads/release-vX.Y.Z,
# issuer https://token.actions.githubusercontent.com).
# Read the release notes: new checks can bring new findings.
set -euo pipefail

dir=${1:?usage: fetch_tools.sh DIR [tool ...]}
shift

declare -A url sha member
# actionlint 1.7.12 (MIT): GitHub Actions workflow linter; runs ShellCheck on run: blocks.
url[actionlint]=https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz
sha[actionlint]=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
member[actionlint]=actionlint
# gitleaks 8.30.1 (MIT): secrets in every commit of the history.
url[gitleaks]=https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz
sha[gitleaks]=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
member[gitleaks]=gitleaks
# Opengrep 1.32.0 (LGPL-2.1): runs only this project's rules (ci/sast/nulavio-rules.yml).
url[opengrep]=https://github.com/opengrep/opengrep/releases/download/v1.32.0/opengrep_manylinux_x86
sha[opengrep]=7360d60174880bd9214f2dfbe439b7bce82b7a3d44cfe945ba833c85cc8bda75
member[opengrep]=
# ShellCheck 0.11.0 (GPL-3.0, run as a separate program): every shell script.
url[shellcheck]=https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.x86_64.tar.gz
sha[shellcheck]=b7af85e41cc99489dcc21d66c6d5f3685138f06d34651e6d34b42ec6d54fe6f6
member[shellcheck]=shellcheck-v0.11.0/shellcheck
# zizmor 1.31.1 (MIT): security audits of the GitHub Actions workflows.
url[zizmor]=https://github.com/zizmorcore/zizmor/releases/download/v1.31.1/zizmor-x86_64-unknown-linux-gnu.tar.gz
sha[zizmor]=d185f726bdaf92df78273217dfdd24ebcd6b0ef48cf3ce776ff5762b6e138c99
member[zizmor]=zizmor

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    echo "fetch_tools: the pinned scanners are Linux x86_64 builds" >&2
    exit 2
fi

tools=("$@")
if ((${#tools[@]} == 0)); then
    tools=(actionlint gitleaks opengrep shellcheck zizmor)
fi
for tool in "${tools[@]}"; do
    [[ -n ${url[$tool]+set} ]] || {
        echo "fetch_tools: unknown tool $tool (known: ${!url[*]})" >&2
        exit 2
    }
done

mkdir -p "$dir/downloads"
work=$(mktemp -d "$dir/.fetch-XXXXXX")
trap 'rm -rf "$work"' EXIT

verified() { # FILE SHA256
    [[ -f $1 ]] && printf '%s  %s\n' "$2" "$1" | sha256sum --check --strict --quiet >/dev/null 2>&1
}

for tool in "${tools[@]}"; do
    file="$dir/downloads/${url[$tool]##*/}"
    if ! verified "$file" "${sha[$tool]}"; then
        rm -f "$file"
        curl -fsSL --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 3 -o "$work/download" "${url[$tool]}"
        if ! verified "$work/download" "${sha[$tool]}"; then
            echo "fetch_tools: SHA-256 mismatch for ${url[$tool]} (expected ${sha[$tool]}); not using it" >&2
            exit 1
        fi
        mv "$work/download" "$file"
    fi
    if [[ -n ${member[$tool]} ]]; then
        tar -xzf "$file" -C "$work" "${member[$tool]}"
        install -m 0755 "$work/${member[$tool]}" "$dir/$tool"
    else
        install -m 0755 "$file" "$dir/$tool"
    fi
done
