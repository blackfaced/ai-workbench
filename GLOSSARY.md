# Personal Development Environments

AI Workbench maintains the tools, managed configuration, and selected Skills used on personal development machines.

The current verified scope is maintenance of the work Mac, home Mac mini, and two Linux development machines (`dev-a`, `dev-b`). Home Mac validation covers installed-tool identity, managed Skill installation and native discovery; model-driven task acceptance remains separate. Complete fresh-machine bootstrap remains a goal: initial installation channels are incomplete.

## Language

- **Profile**: the desired components and client discovery settings for a machine class (`work-mac`, `home-mac` or `work-linux`). A profile is configuration, not a machine inventory or proof of installation. When multiple Mac profiles could match, select one explicitly.
- **Component**: one managed configuration block, tool, Skill, or existing installer declared by a profile.
- **Owner**: the installer or repository responsible for a component. Preserve that authority rather than introducing another writer.
- **Plan**: observations and proposed actions, without configuration writes.
- **Apply**: execute eligible actions after ownership and drift checks, backing up managed file changes.
- **Check**: read-only comparison with the profile plus client discovery and conflict checks. A successful check does not prove fresh-machine installation works.
- **Managed state**: installation records used to prove ownership before modifying a target. It excludes credentials and client session data.
- **Backup / restore**: before-and-after records and guarded reversal of managed file changes. External package downgrades are outside this guarantee.
- **Skill source**: the maintained first-party body/resources or upstream package at a fixed revision. A catalog entry alone does not authorize installation.
- **Skill activation**: the project owner's explicit selection of projects and client discovery entries, performed directly or through an optional workspace manager. A manager-specific registry is not a prerequisite. Project-scoped activation is the default recommendation; existing user-global Profile targets remain a legacy maintenance capability, not the project manifest.
- **Client discovery**: the Skills a client actually exposes; different paths to the same real target may be aliases, while independent same-name copies are conflicts.

The former unattended agent orchestrator is retired; see [decision 0010](decisions/0010-environment-first-repository-scope.md). Its Contract, Run, and Admission concepts do not apply to environment maintenance.
