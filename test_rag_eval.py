"""
SurveyCXM AI — DeepEval Evaluation Test Suite

Evaluates the RAG retrieval pipeline and LLM response generation for:
1. Contextual Relevancy (Did RAG retrieve relevant documentation chunks?)
2. Faithfulness (Is the AI's answer grounded strictly in retrieved context without hallucination?)
3. Answer Relevancy (Does the response directly and cleanly answer the user query?)
4. Out-of-Scope Guardrails (Does the AI reject queries outside of SurveyCXM?)

Usage:
    - Standalone:  python test_rag_eval.py
    - DeepEval CLI: deepeval test run test_rag_eval.py
"""

import os
import sys

# Force UTF-8 encoding on Windows console so emoji output from DeepEval prints cleanly
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

# Ensure repo root is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, ".env"))

import pytest
from deepeval import assert_test
from deepeval.test_case import LLMTestCase
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    GEval
)

try:
    from deepeval.test_case import SingleTurnParams as TestParams
except ImportError:
    from deepeval.test_case import LLMTestCaseParams as TestParams

from services.rag_service import rag_service
from services.ai_service import answer_rag_question


# ---------------------------------------------------------------------------
# Golden Test Cases for SurveyCXM AI
# ---------------------------------------------------------------------------

SAMPLE_METRICS = {
    "current": 48,
    "previous": 42,
    "delta": 6,
    "total_responses": 1250,
    "prev_total_responses": 1100,
    "promoters_pct": 65,
    "passives_pct": 18,
    "detractors_pct": 17,
    "current_period_label": "01/10/2026 to 26/10/2026"
}


def evaluate_case(
    question: str,
    nps_data: dict = None,
    demographics: list = None,
    critical_issues: list = None,
    min_similarity: float = 0.42
) -> tuple[str, list[str]]:
    """Helper: Runs RAG retrieval and generates answer for a given question."""
    # 1. RAG retrieval
    docs = rag_service.search_documentation(question, top_k=3, min_similarity=min_similarity)
    retrieval_context = [d["text"] for d in docs] if docs else ["No documentation context retrieved."]

    # 2. LLM response generation
    answer = answer_rag_question(
        question=question,
        doc_context=docs
    )

    return answer, retrieval_context


# ---------------------------------------------------------------------------
# Pytest / DeepEval Test Definitions
# ---------------------------------------------------------------------------

def test_survey_creation_how_to():
    """Validates that a how-to question retrieves relevant docs and generates a grounded step-by-step guide."""
    question = "How do I create a new survey from scratch in SurveyCXM?"
    answer, retrieval_context = evaluate_case(question, min_similarity=0.40)

    test_case = LLMTestCase(
        input=question,
        actual_output=answer,
        retrieval_context=retrieval_context
    )

    relevancy_metric = AnswerRelevancyMetric(threshold=0.6, model="gpt-4o-mini")
    faithfulness_metric = FaithfulnessMetric(threshold=0.6, model="gpt-4o-mini")

    assert_test(test_case, [relevancy_metric, faithfulness_metric])


def test_branching_logic_faithfulness():
    """Validates that conditional logic guidance is faithful to platform documentation."""
    question = "How does conditional branching and survey logic work?"
    answer, retrieval_context = evaluate_case(question, min_similarity=0.40)

    test_case = LLMTestCase(
        input=question,
        actual_output=answer,
        retrieval_context=retrieval_context
    )

    faithfulness_metric = FaithfulnessMetric(threshold=0.6, model="gpt-4o-mini")
    assert_test(test_case, [faithfulness_metric])


def test_metrics_answer_relevancy():
    """Validates that live CX metrics queries are answered accurately using real-time data."""
    question = "What is our current NPS score and how has it changed?"
    answer, retrieval_context = evaluate_case(question, nps_data=SAMPLE_METRICS)

    test_case = LLMTestCase(
        input=question,
        actual_output=answer,
        retrieval_context=retrieval_context
    )

    relevancy_metric = AnswerRelevancyMetric(threshold=0.7, model="gpt-4o-mini")
    assert_test(test_case, [relevancy_metric])


def test_out_of_scope_guardrail():
    """Validates that queries outside SurveyCXM scope are strictly rejected."""
    question = "Can you give me a recipe for baking chocolate cake?"
    answer, _ = evaluate_case(question)

    # Custom GEval metric checking domain adherence
    guardrail_metric = GEval(
        name="Domain Guardrail Check",
        criteria="Determine whether the assistant correctly rejected an out-of-scope question that is unrelated to SurveyCXM or Customer Experience.",
        evaluation_params=[TestParams.INPUT, TestParams.ACTUAL_OUTPUT],
        threshold=0.7,
        model="gpt-4o-mini"
    )

    test_case = LLMTestCase(
        input=question,
        actual_output=answer
    )

    assert_test(test_case, [guardrail_metric])


# ---------------------------------------------------------------------------
# Standalone CLI Runner
# ---------------------------------------------------------------------------

def run_standalone():
    """Runs the DeepEval test suite programmatically and prints summary output."""
    print("=" * 70)
    print("           SURVEYCXM AI -- DEEPEVAL EVALUATION RUNNER")
    print("=" * 70)

    tests = [
        ("1. Survey Creation (How-To Relevancy & Faithfulness)", test_survey_creation_how_to),
        ("2. Branching Logic (Documentation Grounding)", test_branching_logic_faithfulness),
        ("3. NPS Metrics (Real-time Analytical Relevancy)", test_metrics_answer_relevancy),
        ("4. Domain Scope Guardrail (Out-of-Scope Rejection)", test_out_of_scope_guardrail),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n[RUNNING] {name}...")
        try:
            test_fn()
            print(f"  [PASSED] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAILED] {name}\n     Details: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"EVALUATION COMPLETE: {passed} passed, {failed} failed out of {len(tests)} tests.")
    print("=" * 70)


if __name__ == "__main__":
    run_standalone()
