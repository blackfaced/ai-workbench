Set up or maintain the target project's agent context and integration-test guide. Use the project's actual rules, tools and entry points. This is a Skill, not the retired `aiwb setup` CLI; the selected client continues to own planning and execution.

## Establish the engineering baseline

For project onboarding or full project setup, resolve, validate and read the passive upstream dependency through [Matt project baseline](references/matt-project-baseline.md) first. Do not invoke it by Skill name: its upstream metadata disables model invocation, and name-based resolution can select a user-global copy. The validated project package owns the repository's issue-tracker choice, triage vocabulary when applicable, Domain Docs layout, and the corresponding `AGENTS.md` or `CLAUDE.md` pointers. Let that package explore, confirm and update its own outputs; do not reproduce its templates or maintain a second definition here.

If its maintained outputs already match the current repository and the tracker/domain choices have not changed, reuse them without restarting setup. No workspace manager or activation registry is required. Use the read-only package check and, when needed and authorized, the standalone preparation steps in [Matt project baseline](references/matt-project-baseline.md). If the project package, one of its required resources or its fixed identity is unavailable, report the concrete dependency gap and stop the baseline-dependent part of project setup. Continue only independent requests such as a guide-only update. Preserve an existing installation owner's control over updates; never search/fall back to a user-global copy or ask the user to choose a manager as a setup prerequisite.

After the baseline is established, read [project context setup](references/project-context.md) and extend those project-owned facts with AIWB's client loading, private context, worktree/Botmux, error/observability and integration-test guidance. Preserve the upstream ownership boundary and link to its outputs instead of copying them.

## Choose the requested setup

- For project onboarding, private project rules, client loading, or worktree/Botmux context, read [project context setup](references/project-context.md). Establish the project boundary before configuring its workflow.
- For an integration-test guide, including `deliver-spec` requests for missing test methods, read [integration setup](references/integration-setup.md) and use [the guide outline](references/integration-guide.md). This remains independently usable; a guide-only request does not require changing client configuration.
- For project error handling and observability conventions, read [error and observability setup](references/error-observability.md). Inspect current call paths and relevant recent fixes before recording project-owned reuse points and verification methods. Include this analysis in project onboarding/maintenance when runtime behavior is in scope; a configuration-only repair can reuse valid evidence or state why it is unaffected.
- For full project setup, cover the applicable context, engineering conventions and integration guide. Reuse maintained project documents and link them from the effective context rather than copying their contents.

## Ownership and completion

Discover the repository's actual tracker, commit conventions, required skills, testing and deployment sources. Personal and team repositories can use different conventions; a machine-wide work policy is not evidence that a project requires a particular tracker or work-item ID. Resolve conflicts with the project's owner and applicable rules. Never invent a missing ID or silently relax a team requirement.

Show a bounded plan with target files, owners, effective client entry points and validation before applying configuration. Existing authorization covers its stated scope; ask only for an unresolved choice or an action outside that scope. Preserve team-owned `AGENTS.md`, unrelated configuration, hooks and trust records. Back up affected owned content before changes; recognize existing managed content and update it in place so repeated setup is idempotent. Do not replace a whole client config to install one instruction field.

Report changed paths, source revisions, backup/recovery paths and observed versus unverified results. Separate client context loading, environment readiness and behavior acceptance. A configured file, successful installation, or an agent's assertion that it read the rules is not proof of the corresponding outcome. Project setup does not authorize global-rule removal, client installation, deployment or shared access changes unless those actions were included in the user's request.
