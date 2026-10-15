# On-demand explainer

- Domain: learning
- Status: opt-in
- Use when: facing a completely unfamiliar concept and existing materials are too shallow, too specialized, or do not exist; the goal is a first mental model, not mastery.

## Pick a delivery form

Per Karpathy's ladder (as discussed in the Anatomy article): escalate the form only as far as the learner actually needs.

| Form | When it fits |
| --- | --- |
| Clear, simple language | Fast lookup, conceptual gist. Ask the model to write against ASD-STE100-style rules: short sentences, active voice, one term per meaning, structured layout, minimal ambiguity. |
| Diagram / sketch | Relationships and structure that text keeps garbling. |
| Interactive HTML page | The learner wants to poke, rotate, disassemble and explore by themselves. [Anatomy](../skills/anatomy.md) is built exactly for this. |
| Dedicated narrated video | A sequential process that must be watched step by step; friendliest for total beginners. Anatomy plus a walkthrough narration, then swap the default OS TTS for a proper voice. |

These are not replacements for one another: text for lookup, diagram for
structure, page for exploration, video for ordered process. Match the form to
the knowledge, the audience and their learning stage.

## Verify before trusting

- AI-generated animation and narration look authoritative but can get parameters, mechanisms and pronunciation wrong. Treat as orientation; cross-check key facts against a real source before relying on it.
- Cost scales with desired fidelity: publishable, every-part-detailed versions need top models at high reasoning; personal-study versions work with cheaper configs.
