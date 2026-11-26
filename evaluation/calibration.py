"""Check whether evaluator scores rank real application outcomes correctly."""

from pathlib import Path

from career.files import CareerError, parse_yaml

from .reporting import JSON_REPORT, read_report

MIN_CASES = 10
SCORES = ("overall", "job_match", "semantic_fit", "ats_readiness")


def score_of(report: dict, key: str) -> float | None:
    block = report.get(key)
    return block["score"] if block else None


def auc(positive: list[float], negative: list[float]) -> float | None:
    """Probability that a random advanced case outscores a random non-advanced one."""
    if not positive or not negative:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positive for n in negative)
    return round(wins / (len(positive) * len(negative)), 3)


def cases_from_applications(root: Path) -> list[dict]:
    from career.applications import POSITIVE, load

    cases = []
    for path in sorted((root / "applications").glob("*.yaml")):
        application = load(path)
        statuses = {event.status for event in application.events}
        if statuses <= {"submitted"}:
            continue  # Still pending. No outcome yet.
        report = root / "resumes" / application.version / JSON_REPORT
        if report.is_file():
            cases.append({"id": application.version, "report": report, "advanced": bool(POSITIVE & statuses)})
    return cases


def cases_from_file(path: Path) -> list[dict]:
    data = parse_yaml(path.read_bytes())
    if not isinstance(data, list):
        raise CareerError("calibration cases must be a YAML list of {id, report, advanced}")
    base = path.parent
    return [{"id": str(item["id"]), "report": base / item["report"], "advanced": bool(item["advanced"])} for item in data]


def calibrate(cases: list[dict]) -> dict:
    loaded = [{**case, "report_data": read_report(Path(case["report"]))} for case in cases]
    metrics = {}
    for key in SCORES:
        pos = [s for c in loaded if c["advanced"] and (s := score_of(c["report_data"], key)) is not None]
        neg = [s for c in loaded if not c["advanced"] and (s := score_of(c["report_data"], key)) is not None]
        metrics[key] = {
            "auc": auc(pos, neg),
            "mean_advanced": round(sum(pos) / len(pos), 2) if pos else None,
            "mean_not_advanced": round(sum(neg) / len(neg), 2) if neg else None,
        }
    advanced = sum(case["advanced"] for case in loaded)
    warnings = []
    if len(loaded) < MIN_CASES:
        warnings.append(f"Only {len(loaded)} cases with outcomes. Treat results as anecdotal below {MIN_CASES}.")
    if not advanced or advanced == len(loaded):
        warnings.append("Calibration needs both advanced and non-advanced outcomes.")
    return {
        "cases": len(loaded), "advanced": advanced, "metrics": metrics, "warnings": warnings,
        "interpretation": "AUC 0.5 means the score does not separate outcomes. Values near 1.0 rank advanced applications higher.",
        "rows": [{"id": c["id"], "advanced": c["advanced"], "overall": score_of(c["report_data"], "overall")} for c in loaded],
    }
