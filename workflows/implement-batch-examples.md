# Implement Batch — synthetic walkthroughs

Domain: coding

These fixtures illustrate the [workflow](implement-batch.md), not executions in a business project. Issue IDs, paths, candidates, times, results and evidence descriptions below are invented inputs. They prove neither live routing nor product quality, reader access or reduced owner effort. Project-specific commands and artifacts must be discovered there. The rules remain in the linked Skill/references; these examples introduce no additional gates.

## 1. Goal and Issue → implementation handoff

Owner input: “Implement the selection editor in Issue DEMO-20.” No execution prompt is supplied.

Fixture sources available to the parent:

| Source | Relevant fact |
| --- | --- |
| DEMO-20 revision 3, criterion A1 | Switching custom → all → custom retains the effective selection; the next edit removes only the chosen item. Styling and sharing are excluded. |
| Repository rules and test guide at base `1111111111111111111111111111111111111111` | `SelectionPanel` owns the action path; `selectionState` and the existing `selection-roundtrip` browser case are the reuse points. The guide defines the targeted command and cleanup. |
| Existing checkpoint | No prior accepted children or active writers. Test dependencies are mocked. No real API access has been verified. |
| Plan P1, subsequently confirmed by the owner | Use one implementation worker and the existing independent review/integrator roles with the recorded models; local edits/tests allowed, publication and paid calls absent. Assign `/workspace/demo/selection` exclusively to worker W1. |

The parent prepares this brief from those sources before dispatch; work waits for P1 confirmation:

```text
Run demo / attempt W1; implement DEMO-20@3, A1.
Invariant: after custom -> all -> custom, removing B retains every other selection.
Scope and exclusions: DEMO-20@3. Rules/test guide: P1 source links at base 111...111.
Candidate/base: 1111111111111111111111111111111111111111, no starting patch.
Ownership: W1 alone writes /workspace/demo/selection, branch demo-selection.
Model/effort and permissions: P1 role assignment; local edit/test only.
Start at SelectionPanel's action caller; reuse selectionState and selection-roundtrip.
Checks: guide's targeted case, then any affected required gates; mocked API boundary.
Return candidate/complete patch, developer-self-test observations, command/time and
UI assertion/capture references to the parent via P1's recorded native return route.
Result writer: parent, docs/testing/spec-DEMO-20.md; attempt facts: existing run record.
Stop affected work on source conflict, unknown ownership, or required real API access;
ask only for the missing decision/access. No observed blocker at preparation time.
```

Walkthrough result: all handoff fields are recoverable from the sources and P1; the owner supplies only the plan decision. No long execution prompt is needed for this fixture. This is not a measured reduction in real owner work.

## 2. Continue an accepted baseline → review handoff and recovery

Owner input: “Continue the remaining work from the accepted baseline.”

Fixture sources: checkpoint C2 and the acceptance record identify accepted commit `2222222222222222222222222222222222222222`, already containing both prerequisite children. DEMO-21@4 has an unaccepted candidate `3333333333333333333333333333333333333333` based on that commit. Prior attempt D1 failed case R1 because retry chose current settings; D2 reports a repair and a new developer-self-test result. The actual Git ancestry matches C2. Plan P2 already authorizes local review/integration and names the models, independent reviewer Q1 and sole integration writer I1. No publication is authorized.

```text
Run demo-continue / attempt Q1; independently review DEMO-21@4, retry invariant R1.
Base 2222222222222222222222222222222222222222
Candidate 3333333333333333333333333333333333333333; complete committed diff only.
Prerequisites: C2 accepted-evidence links, already included; do not replay their patches.
Ownership: Q1 read-only at /workspace/demo/review; I1 owns integration per C2/P2.
Inspect the actual retry caller and captured outbound request after settings change;
use D1 failure and D2 self-test as leads, not independent QA proof.
Return finding disposition, candidate and evidence to the P2 parent route;
parent owns the run record. Models, checks and authority: unchanged P2 references.
Remaining work: reconcile R1, integrate only after review, then final case execution.
Stop acceptance if candidate/evidence/ownership disagrees with C2; keep other approved
work eligible. No new owner approval for the already-authorized local review.
```

Recovery replay: reload C2, P2 and the evidence, verify actual Git/session state, then resume Q1's pending assignment. If the old writer may still be active, reconcile ownership before replacing it. If the candidate artifact is missing, mark the affected review blocked with that resume condition. If DEMO-21 changes to revision 5 with different retry semantics, expose the conflict, resolve the changed contract and regenerate the affected brief; retain unrelated authorization. A chat summary alone cannot restore acceptance.

## 3. Behavior coverage counterexamples

Apply the [case outline](../skills/implement-batch/references/spec-acceptance.md#behavior-sequence-coverage) to each fixture. The “required addition” is the resulting case design, not an observed passing test.

| Fixture / old evidence | Invariant and required action sequence | Observable assertion / evidence boundary | Walkthrough outcome |
| --- | --- | --- | --- |
| Every selection mode renders; custom → all → custom silently restores a stale list | A1: select A/B, switch to all A/B/C, return to custom, remove B | UI and submitted selection are A/C; browser assertion plus interaction capture, mock API disclosed | Static render tests miss the next edit; add the roundtrip case. |
| Snapshot helper copies model M1; retry caller reads newly selected M2 | R1: start with M1, fail, change setting to M2, retry from the production action | Actual outbound retry payload still uses M1 under this fixture's frozen-input contract; production caller capture or browser request assertion | Helper evidence does not cover the caller; add the request assertion. Mock response still leaves live API integration unverified. |
| Non-empty human edits survive; empty string is treated as uninitialized | E1: separately clear text and replace it with custom text, then reload/re-adopt upstream text | Both persisted and displayed values obey the edit contract; a first-time uninitialized value may adopt upstream text | Add explicit-empty, non-empty and uninitialized assertions. A production-function result covers only that function; persistence/re-entry needs its own case. |
| One navigation action changes both document and user | I1: independently change document, then independently change user with other factors fixed | Observe each identity's specified reset/retention boundary | Existing combined navigation evidence cannot claim either isolated boundary. |
| Static help-text correction | Render the corrected copy at its existing entrypoint | Expected text and existing relevant checks | State, retry and synchronization categories N/A: no state or input ownership changes. No extra matrix or review round. |

Source inspection locates these paths; it does not establish runtime behavior. Production-function tests, browser mocks and real integration each keep their boundary in the case record. An escaped defect is appended to the existing run record with the affected candidate and regression; earlier PASS observations remain historical facts.

## 4. Decision and notification replay

Fixture: five of eight paid generation requests succeeded and their valid outputs can be reused; three failed. The next step's choice of cost/behavior is not already authorized. Prices and latency are unavailable, so this question gives request counts, not invented currency totals:

> 建议只重试失败的 3 项：保留已成功的 5 项，本轮新增 3 次付费请求。另一项是全部重跑，会新增 8 次付费请求，并替换已成功的结果。当前逐次价格和耗时未知。你选“只重试失败项”还是“全部重跑”？

| Input / observed capability | Result under the guide |
| --- | --- |
| Installed `ask` help exposes a response window | Use its verified syntax/units for an appropriate window, ordinarily about ten minutes; checkpoint decision D1, plan revision and actual delivery/window. This fixture supplies no real CLI flags. |
| Window option absent or unknown | Disclose the real limit; retain D1 in the existing authorized conversation. Do not claim the window was extended. |
| `ask` unavailable or delivery fails | Use an available authorized client question mechanism, or record reporting blocked; no fictitious delivered status. |
| D1 times out | D1 remains pending; dependent paid requests do not start. Independent approved work continues, without repeating D1 every minute. |
| Late “retry failed only” arrives for unchanged D1 | Record the answer against D1, update affected contract/brief and proceed within that authority. |
| Late reply refers to superseded D1 | Retain it as history; explain the changed scope and request only the unresolved current decision. |
| A previously authorized dependency recovers | Resume the recorded work and checks without another approval. |

Notification replay, absent a user/client cadence override: `running → running → running → failed → repaired and verified → delivered` produces the meaningful failure, verification milestone and delivery updates; identical running states produce no additional proactive message. The failure names the affected case and next action; delivery links the report and remaining limitations. Required client updates or user-requested cadence still apply. This replay does not imply a background monitor.

## 5. UI self-test delivery example

This is an illustrative report projected from a synthetic acceptance record, not an actual test report. The evidence index below describes fixture artifacts; no browser execution, screenshots, publication or access check was performed for this example.

**Requirement:** DEMO-30@2; acceptance design v2. **Candidate:** branch demo-ui, `5555555555555555555555555555555555555555` (S2); previous `4444444444444444444444444444444444444444` (S1). **Environment:** local UI served at S2; browser API responses mocked; live deployment identity unavailable. **Verdict:** partial validation; acceptance incomplete.

### Attempts and evidence index

In a real report these entries link to original project records/artifacts; they are not copied into another results database.

| Attempt / identity | Command or action; synthetic time | Evidence in fixture |
| --- | --- | --- |
| D1 / developer / S1 | Project test guide's selection and retry cases; 2026-01-01 09:00–09:02 +08:00 | E1: selection assertion and sequence capture pass; E2: failed retry payload shows M2 instead of frozen M1. |
| D2 / same developer / S2 | Affected retry case after repair; 09:10–09:12 +08:00 | E3: request payload M1, passing assertion and retry sequence capture. Repair touches retry only; E1 reuse justified by unchanged selection code/config/environment and expectations. |
| Q1 / independent reviewer / S2 | Review actual caller and D2 evidence; 09:15–09:18 +08:00 | E4: no remaining caller finding in assigned scope. Review only; no new execution claimed. |
| F1 / fresh final acceptance executor / S2 | Reuse applicable E1/E3; inspect live-test prerequisite; 09:20–09:22 +08:00 | E5: live service unavailable, deployment identity unverified; resume when the authorized service/candidate can be verified. Human observation not attempted. |

### Requirement-to-result index

| Requirement / case | Developer self-test | Independent QA | Final integration acceptance | Evidence / remaining boundary |
| --- | --- | --- | --- | --- |
| A1 / selection roundtrip | D1 PASS on S1; explicit reuse on S2 | Q1 reviewed existing evidence, no new execution | F1 reuses E1 for mocked case | E1 assertion + sequence capture; does not prove live persistence. |
| R1 / frozen retry | D1 FAIL on S1 → D2 PASS on S2 | Q1 review resolved the caller finding | F1 reuses E3 for mocked case | E2 original failure retained; E3 retest + capture; E4 review. |
| L1 / real API persistence | NOT_RUN | NOT_RUN | F1 BLOCKED | E5; restore service and verify deployed candidate, then execute. Mock evidence cannot close L1. |
| U1 / agreed human browser check | NOT_RUN | NOT_RUN | NOT_RUN | No observed result; awaiting the agreed human check. |

Current final-executor coverage: **2 PASS by justified reuse, 1 BLOCKED, 1 NOT_RUN**. The historical FAIL remains visible. Independent review is not relabeled as developer self-test or final execution. No required real-integration scope was waived. A subsequent retry-code or environment change invalidates affected E3 coverage until reviewed/retested; it does not retroactively erase D2's result.

### Delivery and access

Fixture delivery text: “本地自测报告已整理到项目约定的 acceptance document。选择往返与冻结重试的 Mock 用例通过；真实保存链路阻塞，人工体验未执行，尚未完成需求验收。报告及证据目前仅在执行机，目标读者访问未验证；发布权限尚未授予，待按已约定的项目制品入口发布。” The actual reply must include the concrete local report link and intended destination obtained from the plan.

| Gap injected into fixture | Required handling |
| --- | --- |
| Only chat says PASS | Assemble persistent report from available observations; unavailable evidence stays missing. |
| Only `/remote/workspace/report.md` is returned | Retain it, identify the agreed reader-accessible route and use existing publication authority; otherwise explicitly leave publication pending. |
| Linked report only covers S1 | Preserve S1 record, assess applicability to S2 and rerun affected cases; no automatic current PASS. |
| Reader gets access denied | Mark delivery access unresolved; fix within authority or request the needed grant. Author access/HTTP success alone is insufficient. |
| Report absent despite green tests | Delivery materials incomplete; prepare it from existing results without adding an agent or blindly rerunning tests. |

## Field follow-up

The live follow-up remains in [#107](https://github.com/blackfaced/ai-workbench/issues/107): retain comparable before/after run references for externally prepared prompts and context requests, including unavailable history and failures; on a later real requirement, deliver the report entry and record whether the owner had to ask again. This walkthrough supplies no live cost, access or friction measurements.
