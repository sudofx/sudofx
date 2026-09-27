#!/usr/bin/env bash
# SUDOFX LOCAL CONTINUOUS RUNNER
# ==============================
#
# This Mac-side operator repeatedly dispatches the bounded GitHub continuation
# workflow. GitHub remains the authenticated execution surface, SQLite remains
# the durable authority, and the downloaded Pages artifact supplies the verified
# decision about whether another cycle is safe.
#
# The runner never guesses from a green checkmark. It continues only from an
# artifact-bound CONTINUE decision and stops visibly on failure or exhaustion.
set -uo pipefail

readonly REPOSITORY="sudofx/sudofx"
readonly WORKFLOW="prove-model.yml"
readonly POLL_SECONDS=5
readonly RETRY_SECONDS=15
readonly DISCOVERY_TIMEOUT_SECONDS=600
readonly QUEUE_TIMEOUT_SECONDS=1800
readonly EXECUTION_TIMEOUT_SECONDS=420
readonly ARTIFACT_TIMEOUT_SECONDS=120

usage() {
  echo "Usage: $0 [N]" >&2
  echo "Without N, continue until the verified observer reaches a terminal state." >&2
  echo "With N, stop after at most N successful cycles." >&2
  exit 64
}

[[ $# -le 1 ]] || usage
max_cycles=0
if [[ $# -eq 1 ]]; then
  [[ "$1" =~ ^[0-9]+$ ]] || usage
  max_cycles=$((10#$1))
  (( max_cycles >= 1 )) || usage
fi

root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "FAILED — run-sudofx-cycles.sh must run inside the sudofx checkout." >&2
  exit 69
}
cd "$root"

# Continuous operation begins only from a known implementation. Fast-forward
# update plus a clean-tree gate prevents the runner from executing a different
# workflow than the source the operator can inspect locally.
branch="$(git branch --show-current)"
[[ "$branch" == "master" ]] || {
  echo "FAILED — local runner requires master; current branch is '$branch'." >&2
  exit 65
}
changes="$(git status --porcelain --untracked-files=all)"
[[ -z "$changes" ]] || {
  echo "FAILED — local checkout has uncommitted files; no workflow was dispatched." >&2
  echo "$changes" >&2
  exit 65
}
git pull --ff-only origin master || {
  echo "FAILED — master could not be updated by fast-forward; no workflow was dispatched." >&2
  exit 1
}

command -v gh >/dev/null 2>&1 || { echo "FAILED — GitHub CLI is not installed." >&2; exit 69; }
command -v python3 >/dev/null 2>&1 || { echo "FAILED — Python 3 is not installed." >&2; exit 69; }
gh auth status >/dev/null 2>&1 || { echo "FAILED — GitHub CLI is not authenticated." >&2; exit 77; }

read_json_field() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1], ""))' "$1"
}

echo "sudofx: local recovery runner active; the cloud workflow normally owns continuous operation."
cycle=0
while true; do
  if (( max_cycles > 0 && cycle >= max_cycles )); then
    echo "NO MORE SAFE WORK — requested cycle limit ($max_cycles) reached."
    exit 0
  fi
  cycle=$((cycle + 1))
  token="local-$(hostname 2>/dev/null | tr -cd '[:alnum:]._-' | cut -c1-24)-$$-$cycle-$(date -u +%s)-$RANDOM"
  title="sudofx continue · $token"
  echo "[cycle $cycle] Dispatching one bounded continuation..."
  gh workflow run "$WORKFLOW" --repo "$REPOSITORY" --ref master -f "dispatch_token=$token" || {
    echo "FAILED — GitHub rejected cycle $cycle dispatch." >&2
    exit 1
  }

  # The optional workflow token prevents a concurrent Shortcut or scheduled
  # heartbeat from being mistaken for this runner's work.
  run_id=""
  discovery_started=$SECONDS
  while [[ -z "$run_id" ]]; do
    run_id="$(gh run list --repo "$REPOSITORY" --workflow "$WORKFLOW" --event workflow_dispatch --branch master --limit 100 --json databaseId,displayTitle --jq ".[] | select(.displayTitle == \"$title\") | .databaseId" 2>/dev/null | head -n 1 || true)"
    if (( SECONDS - discovery_started >= DISCOVERY_TIMEOUT_SECONDS )); then
      echo "FAILED — GitHub did not expose the tokenized run within 10 minutes." >&2
      exit 1
    fi
    [[ -n "$run_id" ]] || sleep "$POLL_SECONDS"
  done

  echo "[cycle $cycle] Watching GitHub run $run_id..."
  queue_started=$SECONDS
  execution_started=0
  unreachable_started=0
  while true; do
    status="$(gh run view "$run_id" --repo "$REPOSITORY" --json status --jq '.status' 2>/dev/null || true)"
    if [[ -z "$status" ]]; then
      (( unreachable_started > 0 )) || unreachable_started=$SECONDS
      if (( SECONDS - unreachable_started >= EXECUTION_TIMEOUT_SECONDS )); then
        echo "FAILED — GitHub remained unreachable while watching run $run_id." >&2
        exit 1
      fi
      sleep "$RETRY_SECONDS"
      continue
    fi
    unreachable_started=0
    [[ "$status" == "completed" ]] && break
    if [[ "$status" == "in_progress" ]]; then
      (( execution_started > 0 )) || execution_started=$SECONDS
      if (( SECONDS - execution_started >= EXECUTION_TIMEOUT_SECONDS )); then
        echo "FAILED — run $run_id exceeded the seven-minute execution guard." >&2
        exit 1
      fi
    elif (( SECONDS - queue_started >= QUEUE_TIMEOUT_SECONDS )); then
      echo "FAILED — run $run_id remained queued for 30 minutes." >&2
      exit 1
    fi
    sleep "$POLL_SECONDS"
  done

  conclusion="$(gh run view "$run_id" --repo "$REPOSITORY" --json conclusion --jq '.conclusion' 2>/dev/null || true)"
  [[ "$conclusion" == "success" ]] || {
    echo "FAILED — run $run_id ended with '${conclusion:-unknown}'." >&2
    exit 1
  }

  # Download the exact artifact produced by this run. Pages deployment can lag,
  # so polling the public URL would risk reading a previous cycle's decision.
  artifact_dir="$(mktemp -d)"
  artifact_started=$SECONDS
  downloaded=false
  while [[ "$downloaded" == false ]]; do
    if gh run download "$run_id" --repo "$REPOSITORY" --name github-pages --dir "$artifact_dir" >/dev/null 2>&1; then
      downloaded=true
      break
    fi
    if (( SECONDS - artifact_started >= ARTIFACT_TIMEOUT_SECONDS )); then
      rm -rf "$artifact_dir"
      echo "FAILED — verified artifact for run $run_id was unavailable for two minutes." >&2
      exit 1
    fi
    sleep "$POLL_SECONDS"
  done
  tar -xf "$artifact_dir/artifact.tar" -C "$artifact_dir" runner-state.json 2>/dev/null || {
    rm -rf "$artifact_dir"
    echo "FAILED — run $run_id did not contain a valid runner decision." >&2
    exit 1
  }
  decision="$(read_json_field disposition < "$artifact_dir/runner-state.json" 2>/dev/null || true)"
  reason="$(read_json_field reason < "$artifact_dir/runner-state.json" 2>/dev/null || true)"
  artifact_run_id="$(read_json_field artifact_run_id < "$artifact_dir/runner-state.json" 2>/dev/null || true)"
  rm -rf "$artifact_dir"

  # Binding the decision back to the current Actions run prevents a stale or
  # malformed artifact from authorizing an additional model invocation.
  [[ "$artifact_run_id" == "$run_id" ]] || {
    echo "FAILED — artifact/run identity mismatch for run $run_id." >&2
    exit 1
  }
  case "$decision" in
    CONTINUE)
      echo "[cycle $cycle] CONTINUE — $reason"
      ;;
    "NO MORE SAFE WORK")
      echo "$decision — $reason"
      exit 0
      ;;
    FAILED)
      echo "FAILED — $reason" >&2
      exit 1
      ;;
    *)
      echo "FAILED — unknown runner decision '${decision:-empty}'." >&2
      exit 1
      ;;
  esac
done
