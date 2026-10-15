# Anatomy

- Type: skill
- Domain: learning
- Source: https://github.com/wheresryan22/anatomy
- Status: installed to DoubaoWork `.user_skills/anatomy` (2026-10-15, 12M, Node v22.23.2); client native-discovery and manual enable pending.
- Use when: a mechanical, physical or computational principle needs an interactive 3D cutaway model or a narrated explainer, rather than another wall of text.

## Notes

Design thesis: "The object is the explanation" — instead of prose, the agent builds a working, explorable model: isometric line-frame parts that rotate, disassemble, and animate real kinematics, with WebGL shaders for flame, water and plasma.

- Invocation (Claude Code): `/anatomy explain how a mechanical watch keeps time, interactive`.
- Step-up: on top of the interactive model, ask for a narrated walkthrough — parts, roles, sequence, and why. Article-tested examples: mechanical watch movement, GPU pipeline, TCP three-way handshake, brake construction.
- Cost and effort (article-reported, Claude Max): a ~5-minute video ≈ 1% of the weekly quota; Opus 5.5 at Ultra reasoning takes ~1.5 h. Sonnet 5.5 at high reasoning suffices for personal-study versions.
- The author deliberately keeps generation slow for real detail; extreme requests (e.g. "train a small model to explain Transformer") can trip safety filters.
- Limits: polished does not mean correct. Verify parameters and key mechanisms before learning professional content from it; the article flags this explicitly.

Origin: https://mp.weixin.qq.com/s/VuJsVTvyNIK8GRTL95n-Qw (数字生命卡兹克, 2026-10-15).
