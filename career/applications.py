"""Record what happened after a version was sent, kept outside the sealed archive."""

from pathlib import Path

from evaluation.reporting import JSON_REPORT, read_report

from .files import CareerError, dump_yaml, parse_yaml
from .models import Application, ApplicationEvent

POSITIVE = {"screen", "interview", "offer"}


def path_for(root: Path, version: str) -> Path:
    return root / "applications" / f"{version}.yaml"


def load(path: Path) -> Application:
    return Application.model_validate(parse_yaml(path.read_bytes()))


def record(root: Path, version: str, event: ApplicationEvent, *, employer: str | None, role: str | None) -> Application:
    if not (root / "resumes" / version).is_dir():
        raise CareerError(f"resumes/{version} does not exist")
    path = path_for(root, version)
    if path.exists():
        application = load(path)
        if event.date < application.events[-1].date:
            raise CareerError("events must be recorded in date order")
        application.events.append(event)
    else:
        if not employer:
            raise CareerError("the first event for a version needs --employer")
        application = Application(version=version, employer=employer, role=role, events=[event])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(application.model_dump(mode="json", exclude_none=True)), encoding="utf-8")
    return application


def summary(root: Path) -> dict:
    rows = []
    for path in sorted((root / "applications").glob("*.yaml")):
        application = load(path)
        statuses = [event.status for event in application.events]
        report = root / "resumes" / application.version / JSON_REPORT
        score = read_report(report)["overall"]["score"] if report.is_file() else None
        rows.append({
            "version": application.version, "employer": application.employer, "role": application.role,
            "latest": statuses[-1], "advanced": bool(POSITIVE & set(statuses)),
            "submitted": application.events[0].date, "overall_score": score,
        })
    advanced = [row for row in rows if row["advanced"]]
    return {
        "applications": rows,
        "total": len(rows),
        "advanced": len(advanced),
        "advance_rate": round(len(advanced) / len(rows), 3) if rows else None,
    }
