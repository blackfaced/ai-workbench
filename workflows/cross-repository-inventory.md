# Cross-repository inventory

- Type: workflow
- Domain: coding, ops
- Status: draft; real-task impact not yet measured.
- Use when: taking stock of changes, delivery status or evidence across repositories.

## Use in a project session

If the client already has the upstream `research` Skill, use it as the investigation entry and include the scope in the request. For example:

> /research 只读盘点本工作区中我负责的仓库，核对本次验收相关的工单、评审和测试证据。先从项目已有说明中确定范围并简要复述，只在关键信息缺失时问我。只把影响本次验收的未完成项列为阻塞，每项给出证据和下一步。本轮直接在会话返回清单；需要留档时沿用项目已有记录。

The upstream Skill supplies the investigation procedure and normally records findings in Markdown. State the required output in the request, such as returning a checklist in the conversation. Its installation and invocation are owned by the target project or existing installer.

For recurring inventories, a project owner can add a conditional pointer to this guide in the project's instructions through its existing setup procedure. The client can then reach the guide from a request such as “盘点本次验收还有哪些阻塞”. This guide itself does not register a slash command.

Reuse the existing [self-test-report](../skills/self-test-report/SKILL.md) Skill when the task is to audit test or acceptance evidence. Apply any project-provided delivery closeout or long-requirement tracking Skill only within its declared trigger and scope. An inventory request supplies the scope for the investigation; each selected Skill retains its own authority and output contract.

## Establish the inventory

Start with the repositories, owners and period the request identifies. Confirm missing boundaries when they affect the result. For each repository, resolve the actual tracker and review system, then inspect the requested evidence sources. A commit author alone does not establish task ownership.

For a more specific request, use this prompt and fill only the fields relevant to the task:

> Inventory `<repositories>` for `<owners or ownership rule>` during `<period>` against `<acceptance goal>`. Check `<required sources, such as issues, reviews, commits and test results>`. Treat `<blocking criterion>` as a blocker. Report other findings separately. Give an evidence link and current state for each item, identify missing or inaccessible sources as unknown, and state the scope used.

Use the project's own evidence and ownership rules. Keep out-of-scope items as context only when they help explain a dependency; distinguish a missing check from a failed check and a suggestion from an acceptance blocker.

Summarize each in-scope item with its owner or ownership evidence, issue, linked review and current merge state, verification result and tested revision, acceptance impact, and next action. Required sources that cannot be checked remain explicit gaps. Reuse the project's existing report format where available.

## Check assumptions when they matter

Before a longer investigation or an authorized write, check only the relevant assumptions. For example, verify a target branch and worktree status before changing a checkout, the active identity and target before a remote write, or input reachability from the actual execution environment before integration testing. When sessions overlap, establish who is writing to the checkout and identify the snapshot used for the inventory.

Apply the project's existing plan and confirmation policy when follow-up work needs edits or external effects. Carry existing authorization forward and surface any scope change before acting on it.

To evaluate the workflow, use the next real inventory and record any owner corrections to scope, required evidence that was missed, or unrelated findings classified as blockers. Task evidence and observations belong in the owning project's established location.

When a task also needs cross-client thread coordination, use [repository thread coordination](repository-thread-coordination.md). Record the actual inventory and evidence in the owning project's established location.
