# Teardown checklist (run when pausing)

- [ ] No Runtime session held open; no pinned instance.
- [ ] Long-term Memory disabled or short TTL.
- [ ] CloudWatch log retention confirmed at 3 days (set in stack).
- [ ] **KB confirmed on S3 Vectors, not OpenSearch** (re-check — the expensive mistake).
- [ ] No VPC endpoints / provisioned throughput.
- [ ] Secrets Manager: only the keys you need.
- [ ] Budget alert active; Cost Explorer (filter `Project=research-desk`) shows nothing odd.

## Quick destroy

```bash
cd infra
cdk destroy ResearchDeskPhase0 --force
```
