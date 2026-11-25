# Offline Codex Desktop follow-up drill

Replay the [Desktop entry](../skills/deliver-spec/references/codex-desktop-coordination.md) with two fictional chats. Treat the rows as simulated Desktop responses and record decisions in the same scratch checkpoint. Start each follow-up with only its event and that checkpoint. No native messages are sent.

The workspace matrix defines namespace `demo`, route `service`, repository `example/service`, keeper title `demo::codex::service::keeper`, and a coordinator route. An initial authorized discovery/read reports the original coordinator at `demo-host/coordinator-1` and one matching keeper at `demo-host/keeper-1`. Use the fixture's Git facts below to bind the keeper to the `keeper` worktree on branch `keeper-work`. The fictional user authorizes messages to that address for assignment `A1` and local keeper edits, checks and commits. Results stay in the keeper chat for coordinator readback.

| Turn or simulated response | Expected checkpoint and action |
| --- | --- |
| Initial implementation request | Read matrix and Git evidence, bind `A1`, record `A1/initial` and submit to `demo-host/keeper-1`. Record the acknowledgment as submission. Read the keeper's initial commit and check evidence after the wait. |
| Later MR comment asks for an owner in the status file | Reload the same checkpoint and read the stored address. Inspect the comment and initial candidate read-only. Send `A1/review-repair` with the comment and initial commit to the same keeper. Read back the MR repair commit and its actual checks. |
| After context recovery, CI rejects the MR repair because the owner line requires a format version | Reload the matrix and checkpoint, read the bound keeper, then submit `A1/ci-repair` to the same address with the failed job and its tested commit. Record the failed check against the MR repair commit. Read back the CI repair commit with fresh evidence, then inspect it independently. A late green result for the initial commit leaves the CI repair pending. |
| The next repair has no binding, the endpoint is unreachable, or send authority is missing | Replay each case separately. Record the specific blocker and resume condition. There is no send to a guessed address and no coordinator edit, commit or push in the target worktree. |

Each successful simulated return includes `A1`, attempt ID, full base and candidate SHAs, and candidate-specific command, exit status and evidence. A wait completion without these fields leaves review pending. During replay, the coordinator may use the fixture's `rev-parse`, `show`, `diff` and `status` observations. Only the keeper simulates repository writes.

Run this fixture from any checkout with a POSIX shell and Git. It creates three real local candidates under a temporary directory, checks the MR and CI examples and exercises read-only Git review. The printed candidates and exit statuses supply evidence for the simulated receipts. The native envelopes and blocker decisions above are walkthrough steps.

```sh
set -eu
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' 0
repo="$fixture/repo"
keeper="$fixture/keeper"
git init -q "$repo"
git -C "$repo" config user.name "Example Keeper"
git -C "$repo" config user.email keeper@example.invalid
git -C "$repo" remote add origin https://example.invalid/example/service.git
printf 'Draft\n' > "$repo/message.txt"
git -C "$repo" add message.txt
git -C "$repo" commit -qm base
base=$(git -C "$repo" rev-parse HEAD)
git -C "$repo" worktree add -qb keeper-work "$keeper" "$base"
git -C "$keeper" rev-parse --path-format=absolute --show-toplevel --git-common-dir
git -C "$keeper" branch --show-current
git -C "$keeper" remote get-url origin
printf 'base=%s\n' "$base"

keeper_commit() {
    message=$1
    shift
    printf '%s\n' "$@" > "$keeper/message.txt"
    git -C "$keeper" commit -qam "$message"
}
ci_check() {
    test "$(git -C "$keeper" show "$1:message.txt" | sed -n '3p')" = format=1
}
review() {
    before=$(git --no-optional-locks -C "$keeper" status --porcelain=v1 -b)
    index_before=$(cksum "$index")
    test "$(git -C "$keeper" rev-parse HEAD)" = "$1"
    git -C "$keeper" merge-base --is-ancestor "$base" "$1"
    git -C "$keeper" diff --check "$base" "$1"
    git -C "$keeper" show "$1:message.txt"
    test "$before" = "$(git --no-optional-locks -C "$keeper" status --porcelain=v1 -b)"
    test "$index_before" = "$(cksum "$index")"
    test "$(git -C "$keeper" rev-parse HEAD)" = "$1"
}
index=$(git -C "$keeper" rev-parse --path-format=absolute --git-path index)

keeper_commit initial Ready
initial=$(git -C "$keeper" rev-parse HEAD)
review "$initial"
printf 'initial %s diff --check=0\n' "$initial"

keeper_commit review-repair Ready owner=demo
mr=$(git -C "$keeper" rev-parse HEAD)
test "$(git -C "$keeper" show "$mr:message.txt" | sed -n '2p')" = owner=demo
review "$mr"
if ci_check "$mr"; then
    exit 1
else
    printf 'review-repair %s MR check=0 CI check=%s\n' "$mr" "$?"
fi

keeper_commit ci-repair Ready owner=demo format=1
ci=$(git -C "$keeper" rev-parse HEAD)
ci_check "$ci"
review "$ci"
printf 'ci-repair %s CI check=0 diff --check=0\n' "$ci"

# For each blocked route, the coordinator's only repository action is a read.
for blocker in unbound unreachable unauthorized; do
    review "$ci"
    printf '%s: review only, keeper HEAD and index unchanged\n' "$blocker"
done
```

Pass the drill when both follow-ups resolve to `demo-host/keeper-1`, each receipt identifies its own candidate and checks, and each blocker leaves the affected assignment pending without a substitute writer. Live client delivery and project activation require their own evidence.
