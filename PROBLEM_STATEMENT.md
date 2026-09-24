<!-- Page 1 -->

<div align="center">

**বিকাশ PRESENTS**

# SUST CSE CARNIVAL 2026

## Codex Community

# HACKATHON

<br>

# Super Agent Liquidity & Risk Intelligence Platform

*Unify multi-provider liquidity visibility and surface unusual activity across a shared agent operation.*

<br>

*Design a practical, measurable, and responsible prototype that improves operational decision-making without executing real financial transactions.*

</div>

---

<!-- Page 2 -->

| Codex Community Hackathon | bKash presents SUST CSE Carnival 2026 |
|:--|--:|

# 1. Executive Summary

Many mobile financial service agents serve customers through more than one provider, such as bKash, Nagad, and Rocket. They use one pool of physical cash, but each provider has a separate e-money balance. This makes it hard to see the full situation. An agent may have enough total value but still be unable to serve customers because one provider balance or the shared cash reserve is running low. The challenge is to build a working prototype that gives a clear combined view, warns about possible shortages, highlights unusual activity, and helps the right people coordinate a safe response.

Build a safe decision-support prototype that helps a multi-provider “super agent” and the relevant provider teams understand liquidity pressure, cross-provider imbalance, unusual transaction behavior, and who should coordinate the response - without claiming fraud, merging real wallets, or executing financial actions.

# 2. Background and Context

Imagine an agent shop in a busy market on the afternoon before Eid. The shop serves bKash, Nagad, and Rocket customers. It has one physical cash drawer, but three separate e-money balances. Cash-out requests suddenly increase. The agent can see each provider separately, but cannot easily answer a simple question: will the shop have enough cash and provider balance to continue serving customers for the next few hours?

Now the situation becomes more difficult. Most of the pressure is coming from one provider. Several transactions have almost the same amount and come from a small group of accounts. This may be normal Eid demand, a data problem, or activity that needs review. At the same time, the agent, field officer, provider operations team, and risk reviewer may not know who should act first or how the issue should be followed until it is resolved.

# 3. Problem Statement

Build and demonstrate a prototype that helps multi-provider agents and the relevant provider teams understand three connected problems: upcoming liquidity shortage, unusual transaction or balance behavior, and operational coordination. The prototype should make the situation easy to understand, show the evidence behind important alerts, identify the responsible stakeholder, and support safe human decisions. It must not execute real transactions or make a final fraud decision.

# 4. Challenge Objectives

## Primary objectives

- Provide a unified operational view of physical cash and separate provider-specific e-money positions.
- Identify provider-level and aggregate liquidity pressure before service is disrupted.
- Surface unusual transaction or balance behavior with understandable evidence and uncertainty.
- Support clear coordination by identifying the responsible stakeholder, escalation path, case owner, and resolution status for important liquidity or anomaly alerts.
- Help users distinguish operational demand spikes, data-quality problems, and patterns requiring review.
- Demonstrate measurable analytical and engineering quality through a working prototype.

## Secondary objectives

- Support multi-agent, area-wise, provider-wise, or time-wise prioritization.
- Provide clear Bengali, Banglish, or English explanations for different stakeholders.
- Show safe fallback behavior when provider data is incomplete, inconsistent, or delayed.
- Preserve provider separation and avoid implying unauthorized conversion between provider balances.

<div align="right">Page 2</div>

---

<!-- Page 3 -->

| Codex Community Hackathon | bKash presents SUST CSE Carnival 2026 |
|:--|--:|

## Optional advanced objectives

- Explore cross-provider pattern insight or network relationships using simulated identifiers.
- Support what-if scenarios for provider demand, local events, or agent unavailability.
- Show human review, case notes, feedback, or audit trails.
- Explore advanced coordination such as nearby-agent support discovery, alert assignment, acknowledgement, escalation timelines, case notes, resolution tracking, hotspot mapping, or graph-based relationship insight.

# 5. Intended Users and Stakeholders

## Operations role definition for this challenge

In this challenge, “Operations Team” means the people who help agents continue serving customers. This is a general challenge role, not the official organization structure of any provider.

A simple example of the hierarchy is: agent or outlet → field or territory officer → area, thana, or district manager → central provider operations team. Actual structures may be different.

Their daily work may include checking agent service status, reviewing low-balance or unusual-activity alerts, contacting agents, arranging support through approved channels, assigning cases, recording updates, and escalating suspicious cases to a risk or compliance team.

For a Super Agent, each provider keeps its own operations process, rules, and data boundary. A prototype may show one combined outlet view, but it must not suggest that one provider can control another provider’s balance, data, or decisions.

| Stakeholder | Need or challenge |
|---|---|
| Multi-provider agent | See physical cash and each provider balance together, understand upcoming pressure, and know what action may be needed. |
| Provider operations / network coordination team | Monitor assigned agents, review important alerts, contact the correct agent or field officer, coordinate approved support, and track the case until closure. |
| Risk or compliance analyst | Review unusual activity using evidence and context. Operations teams may escalate a case, but they should not make the final fraud decision. |
| Financial service provider | Understand provider-specific service pressure while keeping provider data and authority separate. |
| Management | See area-level service risk, recurring problems, and overall operational readiness. |
| Customers | Receive more reliable service from their preferred provider. |

# 6. Scope of the Challenge

## In scope

- A simulated agent ecosystem with at least two logically separate financial service providers.
- Shared physical cash and provider-specific electronic balances.
- Provider-aware demand, liquidity risk, projected service pressure, and confidence.
- Anomaly or risk indicators based on transaction, timing, balance, area, or behavioral signals.
- Human-review workflows, explanations, evidence, and safe operational recommendations.

<div align="right">Page 3</div>

---

<!-- Page 4 -->

| Codex Community Hackathon | bKash presents SUST CSE Carnival 2026 |
|:--|--:|

- Provider-aware coordination workflows covering alert routing, ownership, acknowledgement, escalation, authorized support requests, and resolution tracking.
- Web, Android, or combined prototype interfaces for agents and/or operations users.
- Testing, monitoring, evaluation, and documented limitations.

## Out of scope

- Real interoperability, settlement, or conversion between bKash, Nagad, Rocket, or other wallets.
- Access to production APIs, real customer identities, real balances, or real transaction accounts.
- Automatic blocking, accusation, disciplinary action, or final fraud determination.
- Unauthorized cash movement, wallet refill, transfer, recovery, or reversal.
- Collection of credentials, PINs, OTPs, passwords, or private authentication data.
- Claims of regulatory approval or production fraud-detection readiness.

# 7. Functional Expectations

| Priority | Expected capability |
|---|---|
| Mandatory | Show shared physical cash and separate balances for each provider. |
| Mandatory | Show which provider or shared cash reserve may face a shortage and approximately when. |
| Mandatory | Detect at least one type of unusual activity and show why it was flagged. |
| Mandatory | Use careful language such as “unusual” or “requires review”; do not declare fraud. |
| Mandatory | For at least one important alert, show who receives it, who owns it, the recommended next step, and the final status. |
| Mandatory | Show lower confidence or a safe fallback when data is missing, late, or conflicting. |
| Mandatory | Use AI, APIs, analytics, or data processing as a meaningful part of the product. |
| Recommended | Allow users to filter or prioritize by provider, agent, area, or time. |
| Recommended | Provide evidence and a simple history for important alerts. |
| Recommended | Offer clear Bengali, Banglish, or English explanations. |
| Recommended | Show at least one simple Bengali or Banglish alert with the situation, evidence, uncertainty, and a safe next step. |
| Optional | Optionally support simulations, peer comparison, relationship views, or cross-provider patterns. |
| Recommended | Support provider-specific escalation, case notes, alert history, and coordination while keeping provider boundaries clear. |
| Optional | Teams may independently select and implement one or more relevant fraud or anomaly-detection scenarios. |

<div align="right">Page 4</div>

---

<!-- Page 5 -->

| Codex Community Hackathon | bKash presents SUST CSE Carnival 2026 |
|:--|--:|

| Priority | Expected capability |
|---|---|
|  | They are free to define the pattern, detection approach, evidence, and review workflow, provided the scenario uses simulated or anonymized data, is clearly documented and evaluated, and does not present an anomaly score as proof of fraud. |

# 8. Non-Functional Expectations

| Area | Expectation |
|---|---|
| Usability | Provider distinctions, shared cash exposure, and risk signals must be easy to understand. |
| Performance | Core analytical and dashboard interactions should be responsive under the demonstrated data volume. |
| Reliability | Provider data failures or inconsistencies should not silently produce confident conclusions. |
| Explainability | Every high-impact alert should expose the reason, relevant evidence, and uncertainty. |
| Security and privacy | Use synthetic identifiers and avoid real credentials, customer identities, or sensitive account data. |
| Fairness and responsible AI | Avoid unsupported profiling and demonstrate human review for risk judgments. |
| Auditability | Important alerts, ownership changes, acknowledgements, escalations, evidence, and resolution actions should be traceable. |
| Interoperability | The prototype should represent multiple providers without assuming real technical integration. |

# 9. Data and Assumptions

Teams should use realistic synthetic, mock, anonymized, or safe public data. The data may include agent and provider IDs, area, time, transaction type, amount, status, opening and current balances, event flags, and case status. Teams must clearly explain how the data was created, what assumptions were made, and what limitations remain.

## Risk interpretation rule

An anomaly is not proof of fraud. Teams should document which behaviors are simulated, what a flag means, the expected false-positive risk, and what human review would be required before any real-world action.

## Participant flexibility note

Participants are encouraged to explore fraud or anomaly patterns of their own choosing, such as unusual transaction velocity, repeated or near-identical amounts, transaction splitting, circular activity, balance inconsistencies, location or time anomalies, abnormal failure rates, or another well-justified pattern. Teams are not required to use these examples and may propose different detection categories. The chosen scenario, assumptions, evidence, validation method, expected false positives, and human-review boundary must be explained.

<div align="right">Page 5</div>

---

<!-- Page 6 -->

| Codex Community Hackathon | bKash presents SUST CSE Carnival 2026 |
|:--|--:|

# 10. Required Deliverables

| Deliverable | What judges should see |
|---|---|
| Working prototype | A live flow showing multi-provider balances, a liquidity or anomaly alert, and how one important case is coordinated or escalated. |
| Source repository | Source code, README, setup steps, environment examples, and sample data. |
| Architecture diagram | Main interfaces, backend, data flow, analytics or AI services, monitoring, provider boundaries, and alert coordination flow. |
| Data and simulation note | How the synthetic provider data and anomaly scenarios were created, including assumptions and limitations. |
| Validation evidence | At least three measured metrics covering analytics, system performance, or reliability. |
| Responsible-design note | Privacy, human review, false positives, advisory boundaries, and actions the prototype intentionally does not perform. |
| Final presentation | Problem, users, story-driven demo, architecture, metrics, coordination flow, risks, limitations, and next steps. |

## Optional supporting materials

- Short demonstration video.
- Alert case study or review log.
- Load-test, profiling, or trace outputs.
- Additional multi-provider scenarios or relationship visualizations.

# 11. Expected Demonstration Scenarios

The following examples are included only to make the task easier to understand. Teams may use different wording, logic, interfaces, and analytical methods. These examples are advisory messages, not financial commands.

## Scenario A - Hidden provider shortage

A multi-provider agent appears healthy when all balances are added together, but one provider’s e-money is about to run out. The prototype should clearly show which provider is under pressure, when the shortage may happen, how certain the estimate is, and what safe next step is suggested.

### Illustrative Bangla alert - liquidity pressure

বর্তমান লেনদেনের ধারা অনুযায়ী বিকেল ৫টা ২০ মিনিটের মধ্যে আপনার নগদ টাকা শেষ হয়ে যেতে পারে। সবচেয়ে বেশি চাপ আসছে বিকাশ ক্যাশ-আউট থেকে। নিরাপদভাবে সেবা চালু রাখতে কমপক্ষে ২০,০০০ টাকা অতিরিক্ত নগদ ব্যবস্থা করার পরামর্শ দেওয়া হচ্ছে।

*This is an illustrative output only. Teams may use different wording, logic, interface, or analytical approach.*

<div align="right">Page 6</div>

---

<!-- Page 7 -->

| Codex Community Hackathon | bKash presents SUST CSE Carnival 2026 |
|:--|--:|

## Scenario B - Liquidity pressure with unusual activity

The agent’s physical cash is falling quickly and one provider shows a sudden rise in repeated or high-value transactions. The prototype should show both the liquidity risk and the unusual pattern, explain possible normal reasons, and recommend human review before major action.

### Illustrative Bangla alert - unusual activity requiring review

গত ১২ মিনিটে স্বাভাবিকের তুলনায় অনেক বেশি ক্যাশ-আউট হয়েছে। কয়েকটি লেনদেনের পরিমাণ প্রায় একই এবং অল্প কয়েকটি অ্যাকাউন্ট থেকে বারবার অনুরোধ এসেছে। এটি ঈদ-পূর্ব স্বাভাবিক চাহিদাও হতে পারে, তবে বড় অঙ্কের নগদ সরবরাহের আগে লেনদেনগুলো পর্যালোচনা করা প্রয়োজন।

*This is an illustrative output only. Teams may use different wording, logic, interface, or analytical approach.*

## Scenario C - Cross-provider or data inconsistency

Different provider feeds arrive late or show conflicting balances. The prototype should warn the user about the data problem, reduce confidence, keep provider balances separate, and avoid giving a misleading recommendation.

## Scenario D - Coordinated response and closure

A high-priority liquidity or anomaly alert affects one provider. The prototype should show who receives the alert, who owns it, what action is recommended, whether it was acknowledged, and whether the issue was resolved or escalated.

# 12. Success Criteria and Engineering Evidence

- The product demonstrates meaningful multi-provider insight rather than merely placing separate charts on one screen.
- Liquidity and anomaly outputs are connected, explainable, and safe for human decision support.
- Important alerts lead to a clear and traceable coordination path rather than ending as passive dashboard notifications.
- Provider boundaries and real-world integration limits are clearly respected.
- False positives, uncertainty, and data-quality failure modes are acknowledged and tested.
- The prototype presents measurable analytical and system evidence end to end.

| Possible metric | Example evidence |
|---|---|
| Provider-level demand or balance error | Validation on held-out simulated provider scenarios. |
| Shortage detection lead time | How early provider or shared-cash pressure is detected. |
| Anomaly precision and recall | Evaluation against intentionally injected simulated cases. |
| False-positive rate | Normal salary-day or Eid scenarios incorrectly flagged for review. |
| Alert explanation coverage | Percentage of alerts with reason, evidence, and uncertainty. |
| API or processing latency | Average and percentile timing at a documented agent or transaction volume. |
| Reliability and observability | Behavior, logs, metrics, or traces during delayed, missing, or inconsistent provider input. |

<div align="right">Page 7</div>

---

<!-- Page 8 -->

| Codex Community Hackathon | bKash presents SUST CSE Carnival 2026 |
|:--|--:|

# 13. Evaluation Criteria

Because the problem is already defined, judges will focus mainly on how well the team understands the problem, builds the prototype, validates the analytics, handles uncertainty, and demonstrates the complete workflow.

| Category | Weight | What judges evaluate |
|---|---:|---|
| Problem understanding and ecosystem relevance | 15% | Clarity of multi-provider operations, user roles, coordination responsibilities, provider boundaries, and documented assumptions. |
| Innovation and decision value | 20% | Quality and originality of unified liquidity, anomaly, and human decision-support insight. |
| Technical implementation and integration quality | 25% | End-to-end completeness, software quality, component integration, alert routing or case workflow, robustness, reliability, and demonstrable engineering depth. |
| Data and analytical quality | 20% | Realism of simulated data, validation method, uncertainty handling, anomaly evidence, and false-positive awareness. |
| User experience and explainability | 10% | Clarity and usefulness for agents, provider operations users, outlet coordinators, and risk reviewers, including ownership, next steps, and status visibility. |
| Security, privacy, fairness, and responsible design | 5% | Provider boundaries, human review, data safety, careful risk language, and prevention of unsafe financial actions. |
| Presentation and demonstration | 5% | Live end-to-end flow, coherent narrative, measured evidence, and honest treatment of limitations. |

# 14. Constraints and Guardrails

- Use simulated, anonymized, mock, or safe public data only.
- Represent providers as logically separate systems; do not imply unauthorized conversion or settlement.
- Do not connect to or control real wallets, balances, customer accounts, or financial infrastructure.
- Do not request PINs, OTPs, passwords, private keys, or other sensitive credentials.
- Risk signals are advisory and must support human review; the prototype must not make final fraud determinations.
- Do not automatically block users, freeze funds, accuse agents, or initiate financial actions.
- Coordination features may notify, assign, escalate, recommend, and track; they must not bypass provider authorization, expose another provider’s confidential data, or automatically transfer liquidity.
- Document assumptions, synthetic patterns, test conditions, limitations, and expected false positives.

<div align="right">Page 8</div>

---

<!-- Page 9 -->

| Codex Community Hackathon | bKash presents SUST CSE Carnival 2026 |
|:--|--:|

- Prioritize a coherent, demonstrable scope over unsupported production claims.

# 15. Innovation Opportunities

- Provider-aware liquidity planning.
- Cross-provider operational context.
- Explainable anomaly and risk evidence.
- Human review and feedback loops.
- Provider-aware alert ownership, escalation, and resolution workflows.
- Area or network hotspots.
- Context-aware distinction between legitimate spikes and suspicious patterns.
- Inclusive agent-side communication.
- Privacy-preserving synthetic data design.
- Scalable monitoring and traceability.

# 16. Submission Checklist

- At least two provider contexts represented distinctly.
- Shared cash and provider-specific balances demonstrated.
- Forward-looking liquidity insight demonstrated.
- At least one anomaly category demonstrated with evidence.
- Human-review and careful risk language included.
- At least one alert demonstrates routing, ownership, acknowledgement or escalation, and a visible resolution status.
- Repository, data, README, and architecture complete.
- At least three metrics measured and explained.
- Failure, uncertainty, and false-positive considerations shown.
- Safety, privacy, boundaries, and limitations stated.
- Final presentation ready.

# 17. Closing Statement

The strongest submissions will make a complex multi-provider situation simple to understand. They will connect liquidity insight, unusual-activity evidence, and clear coordination without unsafe integration, unsupported accusations, or automatic financial action.

<div align="right">Page 9</div>