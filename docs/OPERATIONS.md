# Deployment and operations

## Environments

The local process, Docker image and Vercel deployment use the same `app:app` ASGI application. Python 3.12 and serving dependencies are pinned; scientific training dependencies are separate so the public server stays small. Vercel's filesystem is treated as read-only. No data downloads, training or model downloads run during cold start.

```bash
vercel link --project open-finance-intelligence
vercel deploy --prod
python scripts/smoke_test.py --base-url https://open-finance-intelligence.vercel.app
# Verify the actual LLM connection separately (fallback does not count as success):
python scripts/smoke_test.py --base-url https://open-finance-intelligence.vercel.app --require-generation
```

Vercel can connect directly to `shrut10/open-finance-intelligence`. The initial release is also verified explicitly after deployment. GitHub Actions independently runs offline tests, lint checks and a Docker build followed by a real HTTP smoke test.

## Generation configuration

| Variable | Meaning |
|---|---|
| `OFI_LLM_ENABLED` | Explicitly opt into external generation; default false |
| `OFI_LLM_BASE_URL` | OpenAI-compatible API root, e.g. `https://ai-gateway.vercel.sh/v1` |
| `OFI_LLM_MODEL` | Exact provider model identifier |
| `OFI_LLM_API_KEY` | Optional local or hosted secret |
| `AI_GATEWAY_API_KEY` | Alternative Vercel AI Gateway credential |
| `VERCEL_OIDC_TOKEN` | Vercel OIDC credential for local development/build environments |

At runtime Vercel supplies a fresh credential in the reserved `x-vercel-oidc-token` request header. The API passes it only into that request's generation call and only permits this on Vercel. It is never stored in global environment state, logged, or returned to clients. See the [OIDC reference](https://vercel.com/docs/oidc/reference).

An answer reports its actual mode. Retrieval works without a provider. Timeout, exhausted credits, missing configuration or failed generation validation produce a clearly labelled extractive fallback. Weak evidence produces abstention before any model request. Generation uses a bounded prompt and response, with no tools, browsing or autonomous actions.

The deployment uses the existing Vercel Hobby workspace. No paid subscription or automatic credit top-up is configured by this project. Vercel AI Gateway documents a free monthly allowance for eligible accounts, but may require payment-card verification before accepting even free-tier requests; availability and future terms can change. When access is unavailable or the allowance is exhausted the evidence view remains useful through the extractive fallback. Do not add a billable provider key without setting that provider's budget controls first.

References: [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi), [AI Gateway Python authentication](https://vercel.com/docs/ai-gateway/sdks-and-apis/python), [AI Gateway pricing](https://vercel.com/docs/ai-gateway/pricing).

## Data freshness and refresh

The public app displays the retrieval date and each series' latest observation separately. A health check being green means the bundled artifacts are readable, not that the observation is from today. Monthly statistics have different release lags. The document corpus is a fixed selection with publication dates, not a live catalogue of every new policy.

The refresh workflow downloads public statistics, validates them, reruns the forecast and tests, and uploads the resulting snapshot as a GitHub Actions artifact for review. It does not overwrite `main` or auto-promote a newly evaluated model. To publish a reviewed refresh, rebuild locally, review the source manifest and model report, commit the resulting artifacts and redeploy. Store the prior commit/release to retain experimental provenance.

## Request limits and privacy

The ask endpoint accepts 8–600 characters and rejects request bodies larger than 8 KB before JSON parsing. Limits are 10 requests per minute per connection address and 40 per minute per application instance. These are **best-effort process-local limits**, not a distributed abuse-control service; a scaled deployment needs a shared limiter or edge firewall and provider spending caps. Proxy behavior may group users under one connection address.

Application logs include an internally generated request ID, route template, status, latency, model version and answer mode. They omit questions, headers, credentials, query strings and IP addresses. Hosting platforms have their own access logs and retention policies. When generation is enabled, the question and retrieved public passages are transmitted to the configured model provider; the UI discloses this. There is no account system, stored chat history, analytics cookie or private-document upload.

Queries are parameterised and limited to an allowlist of datasets. The API offers no arbitrary SQL, shell execution, URL fetching or user-supplied corpus. Source material is evidence, not authority to change system instructions. Citations and lexical/numeric consistency checks reduce unsupported output but do not prove semantic entailment.

## Troubleshooting

- `/health` returns 503: rebuild/restore the bundled data, corpus or forecast artifacts. A missing required artifact must not be reported as healthy.
- The UI reports extractive fallback: inspect provider configuration, quotas and availability. Never paste a secret into an issue or browser field.
- A source endpoint changes or rejects a refresh: the immutable bundled snapshot still runs. Fix ingestion and verify its hashes before publication.
- The model fails against a baseline or intervals under-cover: preserve the result. Improving methodology requires a new experiment and fresh evaluation, not selecting a new winner using the already inspected test period.
