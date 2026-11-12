# Anatomy

- Type: skill
- Domain: learning
- Source: https://github.com/wheresryan22/anatomy
- Status: upgraded in the existing `.user_skills/anatomy` directory on 2026-11-12. Client UI discovery and activation remain unverified.
- Use when: a mechanical, physical or computational principle needs an interactive 3D cutaway model or a narrated explainer, rather than another wall of text.

## Notes

The old installation matched commit `bc943e40c59998be5da61f9d39c6a983b1116099`. The upgraded directory matches the complete Git tree `89299cdfce386a71723a7e57bb9fe219875582fc`. All 11 print-sheet tests passed from the installed package. [Installed commit 1482e8469b0a9e0d8cc18ea2740a01423d29ae80](https://github.com/wheresryan22/anatomy/commit/1482e8469b0a9e0d8cc18ea2740a01423d29ae80)

Design thesis: "The object is the explanation" — instead of prose, the agent builds a working, explorable model: isometric line-frame parts that rotate, disassemble, and animate real kinematics, with WebGL shaders for flame, water and plasma.

- Invocation (Claude Code): `/anatomy explain how a mechanical watch keeps time, interactive`.
- Step-up: on top of the interactive model, ask for a narrated walkthrough — parts, roles, sequence, and why. Article-tested examples: mechanical watch movement, GPU pipeline, TCP three-way handshake, brake construction.
- Cost and effort (article-reported, Claude Max): a ~5-minute video ≈ 1% of the weekly quota; Opus 5.5 at Ultra reasoning takes ~1.5 h. Sonnet 5.5 at high reasoning suffices for personal-study versions.
- The author deliberately keeps generation slow for real detail; extreme requests (e.g. "train a small model to explain Transformer") can trip safety filters.
- Limits: polished does not mean correct. Verify parameters and key mechanisms before learning professional content from it; the article flags this explicitly.

Origin: https://mp.weixin.qq.com/s/VuJsVTvyNIK8GRTL95n-Qw (数字生命卡兹克, 2026-10-15).
