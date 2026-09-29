# Evidence retrieval and grounded generation

The application answers bounded research questions about four dated policy documents. It does **not** provide a live regulatory search engine or personal financial advice. The monetary-policy data/forecast panel is a separate pipeline from this document corpus.

## Corpus and reuse

The bundled corpus comprises:

| Document | Publisher | Published | Scope |
|---|---|---|---|
| Critical third parties memorandum of understanding | Bank of England / FCA | 12 November 2024 | Coordination, shared/lead oversight, information sharing and confidentiality |
| Digital pound consultation response | Bank of England / HM Treasury | 25 January 2024 | Proposed design, privacy, cash, holding limits and decision process |
| Monetary Policy Committee remit | HM Treasury, addressed to the Bank | 26 November 2025 | Inflation target, accountability and policy objectives |
| Financial crisis management memorandum | HM Treasury / Bank of England | 1 September 2025 | Operational responsibility, liquidity support and public funds |

All four selected documents explicitly allow reuse under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). The two PDF licences were verified on pages 2 and 4 respectively; the GOV.UK sources carry OGL/Crown copyright notices. Attribution, official URL, publication and retrieval timestamps, full-file SHA-256, and licence evidence are recorded in `data/corpus/manifest.json`. The corpus includes no client or personal data. No institution endorses this project. Logos and other excluded third-party material are not extracted into retrieval passages.

This selection is intentional: general BoE website narrative is **not automatically OGL**, and [FCA general website terms](https://www.fca.org.uk/legal) impose separate reuse restrictions. These restrictions should be checked before adding documents. The [BoE terms](https://www.bankofengland.co.uk/legal) separately license its statistical database. Do not infer that every public document is open-licensed.

`python scripts/build_corpus.py` deterministically rebuilds passages from bundled raw files. `--refresh` re-fetches the four fixed allowlisted official URLs; review content/licences and rerun evaluation before publishing an update. Downloading is an explicit build task, never done on an API request. The raw corpus is about 7 MB. There are 284 passages; PDF page locations are preserved in `#page=` citation links. HTML sources link to the document.

## Retrieval and abstention

1. Lowercase/tokenise, remove a small declared stopword list and apply a simple stemmer. Expand common domain acronyms.
2. Retrieve using BM25 (k1=1.5, b=0.75), then weight by query-term coverage. Suppress near-duplicate passages.
3. Return up to three passages, with a support score `(1 - exp(-BM25 / 9)) × original_query_term_coverage`.
4. Abstain when top support is below **0.30** or fewer than two substantive original terms match. Also abstain on explicit requests for current/future facts, personal investment decisions or bypassing citation/instruction rules.

The support score is **not a calibrated probability**. Lexical overlap cannot establish semantic entailment. This retriever may miss synonyms and retrieve related material that does not actually answer the question. Scope patterns are an extra guard, not a comprehensive prompt-injection defence.

## Two transparent answer modes

**Extractive (default, no secret or inference bill):** select relevant verbatim sentences from the first two retrieved passages. The API labels this `extractive`. The source text, full evidence excerpt, document date and official page link are always available. This is retrieval plus deterministic extractive answering; it is **not** an LLM.

**Grounded LLM (explicitly enabled):** send only the question and three retrieved passages to a configured OpenAI-compatible chat-completions endpoint. The prompt treats evidence and questions as untrusted data, requires dated/conditional language and a citation on every generated statement. The provider returns structured JSON sentences and source IDs. Local checks reject unknown/missing citations, numbers absent from cited evidence, URLs/HTML, excessive length and very low token overlap. These checks reduce clear mistakes; they do **not** prove entailment or prevent all hallucinations (e.g. a negated or overstated claim can still share vocabulary). Users must inspect the cited source for consequential decisions.

Only one upstream request is made: 15-second timeout (5-second connection timeout), maximum 420 generated tokens, no retry loop, no model tools. Generation is never called for an abstained question. API-level rate limits further bound use. If the provider is unavailable or fails local validation, return `extractive_fallback` and explain the fallback. Do not label this as a successful LLM response. The app does not persist questions or provider responses.

Environment variables:

| Variable | Purpose |
|---|---|
| `OFI_LLM_ENABLED=true` | Explicitly opt into provider calls |
| `OFI_LLM_MODEL` | Exact model identifier supported by the provider |
| `OFI_LLM_BASE_URL` | HTTPS API base, defaults to `https://api.openai.com/v1` |
| `OFI_LLM_API_KEY` | Server-side provider key; never put it in browser code or Git |
| `AI_GATEWAY_API_KEY` / `VERCEL_OIDC_TOKEN` | Optional fallback credentials **only** when the hostname is exactly `ai-gateway.vercel.sh` |

On Vercel, `https://ai-gateway.vercel.sh/v1` supports gateway models. Availability, authentication and credit quotas must be verified on the actual deployment; a configured environment variable alone does not establish a successful generation. The code never purchases credits or enables top-ups.

Vercel runtime authentication uses its reserved `x-vercel-oidc-token` request header; the environment variable is a local/build fallback. The token is passed directly into the current call, never written into shared process state, and only forwarded to the exact AI Gateway hostname.

## Reproducible evaluation

`python scripts/evaluate_rag.py` uses 36 manually authored labelled questions in `data/corpus/evaluation_queries.json`: **12 validation, 24 held-out test**. The query set was fixed before threshold calibration. Only validation is used to select among 11 thresholds: minimise false answers to unanswerable questions, then maximise answerability F1, then prefer the lower threshold. The held-out labels are not used in this choice. Hashes identify the exact corpus and query set.

Measured results for the bundled snapshot:

| Metric | Validation | Held-out test |
|---|---:|---:|
| Queries | 12 (7 answerable / 5 negative) | 24 (16 answerable / 8 negative) |
| Correct abstention on negatives | 5/5 | 8/8 |
| Passed support gate on positives | 7/7 | 16/16 |
| Correct document in top 3 | 7/7 | 16/16 |
| All labelled evidence patterns in top 3 | 6/7 | **13/16 (81.25%)** |

The last metric is stricter and exposes missing evidence despite correct document retrieval. All individual results, including failures, are retained in `artifacts/rag_evaluation.json`. Passing the support gate does not mean the answer is correct. Evidence patterns check coverage, not full natural-language correctness. This is a small, hand-authored portfolio benchmark over four chosen documents, not a representative user study. Corpus/rules were designed with domain knowledge; the test set is held out from threshold selection, not from every aspect of development. Future tuning should use new held-out questions.

The offline evaluation does **not** score optional LLM synthesis or factuality. Generation checks are covered with offline unit tests; deployment smoke tests verify actual provider connectivity separately. Do not report 100% answer accuracy or hallucination-free RAG.
