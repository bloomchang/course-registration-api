import re
from collections import defaultdict

from students import StudentRecord

COURSE_CODE = re.compile(r"\b([A-Z]{2,10})[\s-]*(\d{3,4}[A-Z]?)\b")
TERM_CODE = re.compile(r"([0-9]{2})(W|SP|S|F)")
SEASON_ORDER = {"W": 0, "SP": 1, "S": 2, "F": 3}
GRADUATION_CREDITS = 120


def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]+", "", code).upper()


def display_code(code: str) -> str:
    match = COURSE_CODE.fullmatch(code)
    return "-".join(match.groups()) if match else code


def term_key(term: str) -> tuple[int, int]:
    match = TERM_CODE.fullmatch(term)
    if match is None:
        raise ValueError(f"Invalid academic term: {term!r}")
    year, season = match.groups()
    return int(year), SEASON_ORDER[season]


def build_audit_report(student_id: str, student: StudentRecord, catalog, strict=False):
    """Audit the student's saved history and plan against the current catalog."""
    first_completion = {}
    latest_completion = {}
    for attempt in student.history:
        if attempt.status != "Completed":
            continue

        code = normalize_code(attempt.course_code)
        term = term_key(attempt.term)
        first_completion[code] = min(term, first_completion.get(code, term))
        completion = (term, attempt.credits_earned)
        latest_completion[code] = max(
            completion, latest_completion.get(code, completion)
        )

    cross_listings = defaultdict(set)
    for code, course in catalog.items():
        for alias in course["cross_listed"]:
            other_code = normalize_code(alias)
            if other_code != code:
                cross_listings[code].add(other_code)
                cross_listings[other_code].add(code)

    errors_by_term = defaultdict(list)
    cross_list_violations = []
    total_planned = 0
    for item in student.plan:
        code = normalize_code(item.course_code)
        term = item.term
        planned_term = term_key(term)
        course = catalog.get(code)
        if course is not None:
            total_planned += course["credits"]
            for prerequisite in dict.fromkeys(
                map(normalize_code, course["prerequisites"])
            ):
                completion = first_completion.get(prerequisite)
                if completion is None or completion >= planned_term:
                    errors_by_term[term].append(
                        {
                            "course_code": display_code(code),
                            "type": "MISSING_PREREQUISITE",
                            "message": f"Missing prerequisite: {display_code(prerequisite)}",
                        }
                    )

        for completed in sorted(cross_listings[code].intersection(first_completion)):
            cross_list_violations.append(
                {
                    "course_code": display_code(code),
                    "type": "CROSS_LIST_CONFLICT",
                    "message": f"Cross-listed with completed course {display_code(completed)}",
                }
            )

    total_earned = sum(credits for _, credits in latest_completion.values())
    status = "ok"
    if errors_by_term or cross_list_violations:
        status = "failed" if strict else "warning"

    return {
        "student_id": student_id,
        "status": status,
        "timeline_validation": [
            {"term": term, "errors": errors_by_term[term]}
            for term in sorted(errors_by_term, key=term_key)
        ],
        "cross_list_violations": cross_list_violations,
        "credit_summary": {
            "total_earned": total_earned,
            "total_planned": total_planned,
            "total_remaining_for_graduation": max(
                0, GRADUATION_CREDITS - total_earned - total_planned
            ),
        },
    }
