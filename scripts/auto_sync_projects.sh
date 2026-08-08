#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
project_dir="${script_dir:h}"
runtime_dir="$project_dir/runtime"
repo_list="$runtime_dir/auto-sync-repos.txt"
log_file="$runtime_dir/auto-sync.log"

mkdir -p "$runtime_dir"
touch "$log_file"

if [[ ! -f "$repo_list" ]]; then
  print -r -- "No allowlisted repositories: $repo_list" >>"$log_file"
  exit 0
fi

sync_repo() {
  local repo="$1"
  local stamp
  stamp="$(TZ=Asia/Shanghai date '+%F %H:%M')"

  if [[ ! -d "$repo/.git" ]]; then
    print -r -- "[$stamp] skipped (not an independent repository): $repo" >>"$log_file"
    return
  fi

  git -C "$repo" add -A
  if git -C "$repo" diff --cached --quiet; then
    print -r -- "[$stamp] no changes: ${repo:t}" >>"$log_file"
    return
  fi

  local staged_names
  staged_names="$(git -C "$repo" diff --cached --name-only)"
  if print -r -- "$staged_names" | /usr/bin/grep -Eiq '(^|/)(\.env($|\.)|auth\.json$|id_(rsa|ed25519)$|.*credentials.*|.*secret.*|.*cookie.*)' ; then
    print -r -- "[$stamp] BLOCKED sensitive filename: ${repo:t}" >>"$log_file"
    return 1
  fi

  local file size
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    size="$(git -C "$repo" cat-file -s ":$file" 2>/dev/null || print 0)"
    if (( size > 10485760 )); then
      print -r -- "[$stamp] BLOCKED file larger than 10 MiB: ${repo:t}/$file" >>"$log_file"
      return 1
    fi
  done <<< "$staged_names"

  if git -C "$repo" diff --cached -U0 | /usr/bin/grep -Eiq '(gho_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)' ; then
    print -r -- "[$stamp] BLOCKED possible credential in staged content: ${repo:t}" >>"$log_file"
    return 1
  fi

  git -C "$repo" diff --cached --check
  git -C "$repo" commit -m "sync: $stamp"
  git -C "$repo" push origin HEAD
  print -r -- "[$stamp] pushed: ${repo:t}" >>"$log_file"
}

while IFS= read -r repo; do
  [[ -z "$repo" || "$repo" == \#* ]] && continue
  sync_repo "${repo/#\~/$HOME}" || true
done < "$repo_list"
