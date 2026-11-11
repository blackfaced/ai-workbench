# Repository thread coordination

- Type: collaboration workflow
- Domain: coding, ops
- Status: six single-machine routes exercised, including a human-assisted recovery
- Agent procedure: [repository thread transport](../skills/deliver-spec/references/threads.md)

Use a coordination repository's thread as the entry point for a cross-repository task. Resolve named keeper threads from a workspace-owned matrix, send bounded requests through the client's native messaging, then collect evidence in the original coordinator. Cover Codex, Trae CLI and Claude Code through [their own adapters](../skills/deliver-spec/references/thread-harnesses.md). The same arrangement works on one machine when the selected routes are reachable, including mixed harnesses after each direction is verified.

AIWB owns the reusable naming, binding, handoff and recovery procedure. The workspace hub owns the repository/application matrix and role boundaries. Source repositories retain implementation and test evidence; the coordination repository retains only the cross-repository records it already owns. The issue tracker remains the task-state authority.

## Start from a matrix

The workspace matrix provides a namespace, supported harness adapters, one coordinator route, and repository/application entries with permitted roles and responsibilities. Names follow `<namespace>::<harness>::<route>::<role>`; the [agent procedure](../skills/deliver-spec/references/threads.md#discover-and-bind) defines discovery and runtime binding. Each route/role selects one active harness in the run. Actual session addresses, host IDs, worktrees and attempts belong to the run record rather than the durable matrix.

For example:

> 按本工作区仓库矩阵，以集成仓的 coordinator thread 为入口，核验现有 keeper thread 的身份。先做一次只读跨仓核查，在已有授权内发出请求并读取结果；给出涉及的仓库、候选证据和缺口。需要实现时沿用目标仓流程。

This selects a communication pattern. It does not require decomposing a small consultation into a spec delivery. For work already using `deliver-spec`, select native threads as its transport while keeping the existing plan and acceptance policy. Retain the original coordinator across the task; the hub configuration repository is not automatically the runtime coordinator.

## Adoption

Review the matrix and discover existing threads first. Create or rename chats only within explicit user intent. Record messaging authority, including whether recipients may send back or the coordinator will read their results. Keep unbound, ambiguous or unreachable entries visible and continue independent work.

Use the project's selected fixed AIWB revision when activating the guide; the complete transport reference ships with `deliver-spec`. No installation or activation is implied by writing a matrix. Use the [six-direction procedure](../skills/deliver-spec/references/thread-harnesses.md#six-read-only-routes) for queue, terminal attachment, one-time approval and target-session readback. The Claude Code → Codex route includes recovery by continuing the receiving conversation. Complete the [first-use check](../skills/deliver-spec/references/threads.md#first-use-evidence) before claiming live operation; verify each client and host separately.
