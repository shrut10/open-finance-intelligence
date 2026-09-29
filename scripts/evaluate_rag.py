#!/usr/bin/env python3
"""Calibrate only on validation; evaluate the frozen held-out query set offline."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ofi.rag import retrieve  # noqa: E402


def evaluate(rows: list[dict], threshold: float) -> dict:
    results = []
    tp = fp = fn = tn = evidence_hits = recall_hits = answerable_count = 0
    for row in rows:
        result = retrieve(row["question"], threshold=threshold)
        answered = not result["abstained"]
        expected = row["answerable"]
        relevant = [p for p in result["hits"] if p["document_id"] == row["relevant_document"]]
        text = " ".join(p["text"] for p in relevant)
        doc_hit = bool(relevant)
        evidence_hit = bool(relevant) and all(
            re.search(pattern, text, flags=re.I) for pattern in row["evidence_patterns"]
        )
        if expected:
            answerable_count += 1
            recall_hits += int(doc_hit)
            evidence_hits += int(evidence_hit)
        tp += int(answered and expected)
        fp += int(answered and not expected)
        fn += int(not answered and expected)
        tn += int(not answered and not expected)
        results.append(
            {
                "id": row["id"],
                "question": row["question"],
                "category": row["category"],
                "expected_answerable": expected,
                "answered": answered,
                "support": result["confidence"],
                "relevant_document_at_3": doc_hit if expected else None,
                "required_evidence_at_3": evidence_hit if expected else None,
                "retrieved_passage_ids": [p["id"] for p in result["hits"]],
                "reason": result["reason"],
            }
        )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "queries": len(rows),
        "answerable_queries": answerable_count,
        "unanswerable_queries": len(rows) - answerable_count,
        "answerability_precision": round(precision, 4),
        "answerability_recall": round(recall, 4),
        "answerability_f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0,
        "abstention_accuracy": round((tp + tn) / len(rows), 4),
        "false_answers_on_unanswerable": fp,
        "document_recall_at_3": round(recall_hits / max(answerable_count, 1), 4),
        "required_evidence_recall_at_3": round(evidence_hits / max(answerable_count, 1), 4),
        "confusion_matrix": {
            "true_answer": tp,
            "false_answer": fp,
            "false_abstention": fn,
            "correct_abstention": tn,
        },
        "results": results,
    }


def main() -> None:
    query_path = ROOT / "data/corpus/evaluation_queries.json"
    source = json.loads(query_path.read_text())
    validation = [q for q in source["queries"] if q["split"] == "validation"]
    test = [q for q in source["queries"] if q["split"] == "test"]
    candidates = []
    for threshold in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        summary = evaluate(validation, threshold)
        candidates.append((threshold, summary))
    # Penalise unsupported answers first, then maximise correct answer coverage.
    threshold, val = max(
        candidates,
        key=lambda t: (-t[1]["false_answers_on_unanswerable"], t[1]["answerability_f1"], -t[0]),
    )
    final = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query_set_sha256": hashlib.sha256(query_path.read_bytes()).hexdigest(),
        "corpus_sha256": hashlib.sha256(
            (ROOT / "data/corpus/passages.json").read_bytes()
        ).hexdigest(),
        "configuration": {
            "retriever": "BM25 + query coverage + near-duplicate suppression",
            "k": 3,
            "abstention_threshold": threshold,
            "selection": "Minimise false answers on validation; then maximise answerability F1; then choose lowest threshold. Test labels are not used to tune threshold.",
        },
        "validation": val,
        "test": evaluate(test, threshold),
        "threshold_sweep": [
            {
                "threshold": t,
                "precision": r["answerability_precision"],
                "recall": r["answerability_recall"],
                "false_answers": r["false_answers_on_unanswerable"],
            }
            for t, r in candidates
        ],
        "limitations": [
            "Small hand-authored evaluation from four selected documents; not a production benchmark.",
            "Document recall and evidence-pattern recall do not measure full answer correctness.",
            "Generation is not exercised by this offline evaluation. Optional LLM output requires a separate grounded-answer review.",
            "Lexical support and rule-based scope filtering can miss paraphrases or accept related but insufficient evidence.",
            "The test suite is frozen before calibration; future changes should use a new held-out test set.",
        ],
    }
    destination = ROOT / "artifacts/rag_evaluation.json"
    destination.write_text(json.dumps(final, indent=2) + "\n")
    print(
        json.dumps(
            {
                "threshold": threshold,
                "validation": {k: v for k, v in val.items() if k != "results"},
                "test": {k: v for k, v in final["test"].items() if k != "results"},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
