# Unattended Agent Development

This context describes the language used to plan, execute, and verify long-running agent-assisted development without relying on a chat session remaining open.

## Language

**Goal**:
A durable development objective with an agreed requirement and acceptance boundary. A Goal can outlive conversations and have more than one Contract version or Run.
_Avoid_: Task, workflow, chat

**Contract**:
An approved, immutable version of a Goal's scope, acceptance tests, Todo graph, permissions, Harness profiles, and run limits.
_Avoid_: Plan, prompt, brief

**Run**:
One resumable execution of one Contract using a fixed agent provider.
_Avoid_: Session, job, workflow

**Todo**:
A vertical, independently verifiable slice of a Contract. Todos form a dependency graph and each Todo owns its implementation worktree.
_Avoid_: Layer, phase, subtask

**Attempt**:
One bounded Agent effort on a Todo in a specific role. Repeated Attempts do not change the Todo's acceptance boundary.
_Avoid_: Retry, turn

**Checkpoint**:
A durable Run state from which execution can safely resume without trusting partially completed Agent work.
_Avoid_: Status, save point

**Evidence**:
An immutable observation supporting a Run decision, tied to the relevant commit, image digest, Harness profile, and environment identity.
_Avoid_: Log, output, claim

**Harness**:
The project-owned, repeatable mechanism that provisions a test target, seeds data, executes checks, collects Evidence, and cleans up resources.
_Avoid_: Test script, environment

**Candidate**:
The integrated branch and Evidence set that has satisfied its Contract but has not been merged into the project's target branch.
_Avoid_: Release, completed work
