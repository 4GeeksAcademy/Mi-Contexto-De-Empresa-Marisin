"""Eval de retrieval del RAG de TrackFlow (BRIEFING Hito 7 §4-§5).

* **Recall@3:** porcentaje de preguntas de `data/eval/test-queries.json` cuyo
  chunk correcto (`source_document` + `chunk_index`) aparece entre los 3
  primeros resultados de Qdrant. Umbral del BRIEFING: ≥ 80 %.
* **Calibración de `min_score`:** compara la similitud del chunk correcto en
  las preguntas de la base con la mejor similitud de las preguntas fuera de
  alcance (que no tienen respuesta en los documentos).
* **Con `--answers`:** ejecuta `query()` (LLM de generación) para cada pregunta
  y comprueba la fidelidad: ninguna cifra de la respuesta puede faltar en los
  chunks recuperados, y cada respuesta debe incluir los datos clave esperados.

Requiere haber indexado antes con `python -m data.process.rag`.

    python scripts/rag_eval.py
    python scripts/rag_eval.py --answers
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.pipelines import rag as pipeline  # noqa: E402
from data.process import rag as process  # noqa: E402

QUERIES_PATH = ROOT / "data" / "eval" / "test-queries.json"
RESULTS_PATH = ROOT / "data" / "eval" / "rag_eval_results.json"
SEARCH_LIMIT = 5


def scored_search(question: str, limit: int = SEARCH_LIMIT) -> list[dict]:
    """Búsqueda con puntuaciones (solo para el eval: `retrieve()` no expone scores)."""
    response = process.get_qdrant_client().query_points(
        collection_name=process.COLLECTION_NAME,
        query=process.embed(question),
        limit=limit,
        with_payload=True,
    )
    return [
        {
            "score": round(float(point.score), 4),
            "source_document": point.payload["source_document"],
            "chunk_index": point.payload["chunk_index"],
            "section": point.payload["section"],
        }
        for point in response.points
    ]


def suggest_threshold(correct_scores: list[float], out_of_scope_tops: list[float]) -> dict:
    lowest_correct = min(correct_scores)
    highest_out = max(out_of_scope_tops) if out_of_scope_tops else 0.0
    separable = highest_out < lowest_correct
    suggestion = round((highest_out + lowest_correct) / 2, 2) if separable else round(lowest_correct - 0.02, 2)
    return {
        "lowest_correct_chunk_score": round(lowest_correct, 4),
        "median_correct_chunk_score": round(statistics.median(correct_scores), 4),
        "highest_out_of_scope_score": round(highest_out, 4),
        "separable": separable,
        "suggested_min_score": suggestion,
    }


def evaluate(with_answers: bool = False) -> dict:
    spec = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    k = spec["k"]
    min_score = pipeline.DEFAULT_MIN_SCORE
    chunks = {(c["source_document"], c["chunk_index"]): c for c in process.build_chunks()}

    rows, correct_scores = [], []
    for item in spec["queries"]:
        expected = item["expected"]
        key = (expected["source_document"], expected["chunk_index"])
        if key not in chunks or expected["contains"] not in chunks[key]["text"]:
            raise ValueError(f"{item['id']}: el chunk esperado no existe o no contiene '{expected['contains']}'")
        hits = scored_search(item["question"])
        top_k = hits[:k]
        rank = next(
            (i + 1 for i, h in enumerate(hits) if (h["source_document"], h["chunk_index"]) == key), None
        )
        hit_at_k = rank is not None and rank <= k
        correct_score = next(
            (h["score"] for h in hits if (h["source_document"], h["chunk_index"]) == key), None
        )
        if correct_score is not None:
            correct_scores.append(correct_score)
        rows.append(
            {
                "id": item["id"],
                "question": item["question"],
                "expected": f"{expected['source_document']}#{expected['chunk_index']}",
                "rank": rank,
                "hit_at_k": hit_at_k,
                "correct_chunk_score": correct_score,
                "survives_min_score": correct_score is not None and correct_score >= min_score,
                "top_k": top_k,
            }
        )

    out_rows = []
    for item in spec.get("out_of_scope", []):
        hits = scored_search(item["question"])
        out_rows.append(
            {
                "id": item["id"],
                "question": item["question"],
                "top_score": hits[0]["score"] if hits else 0.0,
                "chunks_over_min_score": sum(h["score"] >= min_score for h in hits),
            }
        )

    recall = sum(r["hit_at_k"] for r in rows) / len(rows)
    recall_with_threshold = sum(r["hit_at_k"] and r["survives_min_score"] for r in rows) / len(rows)
    per_document: dict[str, list[bool]] = {}
    for row in rows:
        per_document.setdefault(row["expected"].split("#")[0], []).append(row["hit_at_k"])

    settings = process.load_settings()
    results = {
        "collection": process.COLLECTION_NAME,
        "embedding_model": settings.embedding_model,
        "generation_model": settings.llm_model,
        "chunks_indexed": len(chunks),
        "k": k,
        "min_score": min_score,
        "recall_at_k": round(recall, 4),
        "recall_at_k_with_min_score": round(recall_with_threshold, 4),
        "recall_threshold": spec["recall_threshold"],
        "passes": recall >= spec["recall_threshold"],
        "recall_by_document": {doc: round(sum(v) / len(v), 4) for doc, v in per_document.items()},
        "threshold_analysis": suggest_threshold(correct_scores, [r["top_score"] for r in out_rows]),
        "queries": rows,
        "out_of_scope": out_rows,
    }

    if with_answers:
        answers = []
        for item in spec["queries"] + spec.get("out_of_scope", []):
            context = pipeline.retrieve(item["question"])
            answer = pipeline.generate_answer(item["question"], context)
            missing = [term for term in item.get("answer_must_include", []) if term.lower() not in answer.lower()]
            answers.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "answer": answer,
                    "context": [f"{c['source_document']}#{c['chunk_index']}" for c in context],
                    "unsupported_figures": pipeline.unsupported_figures(answer, context),
                    "missing_terms": missing,
                }
            )
        results["answers"] = answers
        results["faithfulness_ok"] = all(not a["unsupported_figures"] for a in answers)
        results["answers_with_missing_terms"] = [a["id"] for a in answers if a["missing_terms"]]
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Eval de retrieval del RAG de TrackFlow")
    parser.add_argument("--answers", action="store_true", help="genera también las respuestas con el LLM")
    parser.add_argument("--output", type=Path, default=RESULTS_PATH)
    args = parser.parse_args(argv)

    results = evaluate(with_answers=args.answers)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Colección {results['collection']} · {results['chunks_indexed']} chunks · "
          f"embeddings {results['embedding_model']} · generación {results['generation_model']}")
    for row in results["queries"]:
        mark = "✓" if row["hit_at_k"] else "✗"
        print(f"{mark} {row['id']} rango {row['rank']}  score {row['correct_chunk_score']}  {row['question']}")
    for row in results["out_of_scope"]:
        print(f"· {row['id']} fuera de alcance  mejor score {row['top_score']}  {row['question']}")
    print(f"Recall@{results['k']}: {results['recall_at_k']:.0%} (umbral {results['recall_threshold']:.0%}) "
          f"→ {'CUMPLE' if results['passes'] else 'NO CUMPLE'}")
    print(f"Recall@{results['k']} con min_score={results['min_score']}: {results['recall_at_k_with_min_score']:.0%}")
    t = results["threshold_analysis"]
    print(f"Umbral: chunk correcto mín. {t['lowest_correct_chunk_score']} (mediana {t['median_correct_chunk_score']}) · "
          f"fuera de alcance máx. {t['highest_out_of_scope_score']} → sugerido {t['suggested_min_score']}")
    if args.answers:
        print(f"Fidelidad de cifras: {'OK' if results['faithfulness_ok'] else 'REVISAR'} · "
              f"respuestas sin los datos clave: {results['answers_with_missing_terms'] or 'ninguna'}")
    print(f"Resultados en {args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output}")


if __name__ == "__main__":
    main()
