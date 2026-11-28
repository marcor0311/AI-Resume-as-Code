"""Print benchmark scores for repeatable synthetic PDF fixtures."""

from evaluation.engine import evaluate
from tests.test_evaluation import KEYWORDS, PARTIAL, POSTING, STRONG, STUFFED, UNRELATED, make_pdf
from tests.test_evaluation_cases import (
    CLINICAL_POSTING, CLINICAL_UNRELATED, PIPELINE_PARTIAL, PIPELINE_POSTING, SOLUTIONS_POSTING, SOLUTIONS_STRONG,
)
from tests.test_resume_refinement import refinement_reports


def main() -> None:
    print("| Case | Overall | Readiness | Job match | Semantic fit | Literal keywords |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name, lines, posting in (
        ("Aligned", STRONG, POSTING),
        ("Partially aligned", PARTIAL, POSTING),
        ("Unrelated", UNRELATED, POSTING),
        ("Aligned, short posting", STRONG, KEYWORDS),
        ("Stuffed, short posting", STUFFED, KEYWORDS),
        ("Clinical data, unrelated candidate", CLINICAL_UNRELATED, CLINICAL_POSTING),
        ("Data pipelines, partial evidence", PIPELINE_PARTIAL, PIPELINE_POSTING),
        ("Cloud solutions, strong evidence", SOLUTIONS_STRONG, SOLUTIONS_POSTING),
    ):
        report = evaluate(make_pdf(lines), posting)
        scores = [report[key]["score"] for key in ("overall", "ats_readiness", "job_match", "semantic_fit")]
        scores.append(report["job_match"]["components"]["keywords"]["score"])
        print(f"| {name} | " + " | ".join(f"{score:.2f}" for score in scores) + " |")
    print("\n| Controlled revision | ATS Readiness before → after | Job Match before → after |")
    print("| --- | ---: | ---: |")
    for name, (before, after) in refinement_reports().items():
        changes = [f"{before[key]['score']:.2f} → {after[key]['score']:.2f}" for key in ("ats_readiness", "job_match")]
        print(f"| {name} | " + " | ".join(changes) + " |")


if __name__ == "__main__":
    main()
