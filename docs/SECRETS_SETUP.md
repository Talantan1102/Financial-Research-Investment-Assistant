# GitHub Repo Secrets Setup

Plan D nightly workflow needs `DASHSCOPE_API_KEY` to run real LLM calls
during eval + cassette drift detection. This is a one-time setup.

## Steps

1. Go to https://github.com/Talantan1102/Financial-Research-Investment-Assistant/settings/secrets/actions
2. Click **"New repository secret"**
3. Name: `DASHSCOPE_API_KEY`
4. Value: paste the key from your local `backend/.env` (the value after `DASHSCOPE_API_KEY=`)
5. Click **"Add secret"**

## Verification

After setup, manually trigger the nightly workflow once:

1. Go to https://github.com/Talantan1102/Financial-Research-Investment-Assistant/actions/workflows/nightly.yml
2. Click **"Run workflow"** → **"Run workflow"** (use main branch)
3. Watch the run — it should complete in ≤ 30min.

Expected total cost: ≤ ¥0.10 (per Plan C Task 0 spike: ~70 eval cases × ¥0.0006/case ≈ ¥0.04, plus drift detection on 2 cassettes ≈ ¥0.02).

If `EVAL_COST_LIMIT_CNY=20` is hit, that's a 200x buffer — almost certainly a bug, not a real cost overrun.

## What's NOT in repo secrets

- `OPENROUTER_API_KEY` / `BOCHA_API_KEY` / `TUSHARE_API_TOKEN` — none of these are needed by the nightly workflow under v0 (no agent yet uses them in eval).
- PR workflow does not use any secret (cassettes only, no live LLM).

## Rotating the key

If `DASHSCOPE_API_KEY` is compromised:
1. Revoke at https://bailian.console.aliyun.com (DashScope console)
2. Re-create in `backend/.env` (local) AND repo secret (CI)
3. Both must match for nightly to run.
