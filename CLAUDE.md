# CLAUDE.md

## Response style
- Be concise. Keep answers short — minimize lines.
- Lead with the answer; cut preamble, recaps, and restating the question.
- Avoid long tables/lists unless asked. Prefer a few tight sentences.
- Don't over-explain trade-offs; give the recommendation, not a survey.

## Execution
- Do NOT spin up compute / run warehouse or cluster queries unless absolutely needed. Prefer writing files and using metadata/CLI; only execute against compute when there's no other way to do the task.

## Azure workspace provisioning
- AVOID NAT gateways. When creating any qa/prod (or new) Databricks workspace, do NOT enable No-Public-IP / Secure Cluster Connectivity — an NPIP workspace with a Databricks-managed VNet auto-provisions a NAT gateway that bills ~$32/mo per workspace whether idle or not.
- Provision workspaces public-IP (NPIP disabled), matching dev (`enableNoPublicIp=false`, managed VNet) — no NAT gateway, no idle egress cost.
- If NPIP is ever required for security, get explicit sign-off first, since it forces the NAT-gateway cost.
