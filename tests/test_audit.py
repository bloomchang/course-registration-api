import pytest

from audit import build_audit_report
from students import HistoryCourse, PlannedCourse, StudentRecord


def course(credits, prerequisites=(), cross_listed=()):
    return {
        "credits": credits,
        "prerequisites": prerequisites,
        "cross_listed": cross_listed,
    }


def attempt(code, term, credits=3, status="Completed"):
    return HistoryCourse(
        course_code=code, term=term, credits_earned=credits, status=status
    )


def planned(code, term):
    return PlannedCourse(course_code=code, term=term)


@pytest.mark.parametrize("strict, status", [(False, "warning"), (True, "failed")])
def test_audit_checks_each_prerequisite_in_chronological_order(strict, status):
    catalog = {"TEST3000": course(3, ["test-1000", "TEST2000", "test 2000"])}
    history = [
        attempt("TEST-1000", "25F", status="Failed"),
        attempt("TEST1000", "26SP"),
        attempt("TEST-1000", "26F"),
        attempt("TEST2000", "26W", status="Attempted"),
    ]
    plan = [
        planned("TEST-3000", "26F"),
        planned("test3000", "26SP"),
        planned("TEST 3000", "26S"),
        planned("TEST 3000", "26W"),
    ]
    report = build_audit_report("770001", StudentRecord(history, plan), catalog, strict)
    assert report["student_id"] == "770001"
    assert report["status"] == status
    assert report["cross_list_violations"] == []
    assert [item["term"] for item in report["timeline_validation"]] == [
        "26W",
        "26SP",
        "26S",
        "26F",
    ]
    assert [
        [error["message"] for error in item["errors"]]
        for item in report["timeline_validation"]
    ] == [
        ["Missing prerequisite: TEST-1000", "Missing prerequisite: TEST-2000"],
        ["Missing prerequisite: TEST-1000", "Missing prerequisite: TEST-2000"],
        ["Missing prerequisite: TEST-2000"],
        ["Missing prerequisite: TEST-2000"],
    ]
    assert report["timeline_validation"][0]["errors"][0] == {
        "course_code": "TEST-3000",
        "type": "MISSING_PREREQUISITE",
        "message": "Missing prerequisite: TEST-1000",
    }
    assert report["credit_summary"] == {
        "total_earned": 3,
        "total_planned": 12,
        "total_remaining_for_graduation": 105,
    }


def test_cross_list_conflict_requires_a_completed_course():
    catalog = {
        "COSC3506": course(3, cross_listed=["itec-3506", "COSC3506"]),
        "ITEC3506": course(3),
        "BUSI3506": course(3, cross_listed=["BUSI-1000"]),
    }
    history = [
        attempt("COSC 3506", "26W"),
        attempt("BUSI1000", "26W", status="Failed"),
    ]
    plan = [planned("ITEC-3506", "26S"), planned("BUSI3506", "26F")]
    report = build_audit_report("770001", StudentRecord(history, plan), catalog)
    assert report["status"] == "warning"
    assert report["timeline_validation"] == []
    assert report["cross_list_violations"] == [
        {
            "course_code": "ITEC-3506",
            "type": "CROSS_LIST_CONFLICT",
            "message": "Cross-listed with completed course COSC-3506",
        }
    ]


def test_clean_strict_report_and_graduation_credit_floor():
    catalog = {"TEST3000": course(6, ["TEST1000"])}
    history = [
        attempt("test 1000", "24W", 3),
        attempt("TEST1000", "24W", 1),
        attempt("TEST-1000", "23F", 1),
        attempt("TEST1000", "24S", 0, "Failed"),
        attempt("TEST1001", "26W", 115),
        attempt("TEST1001L", "26W", 0),
    ]
    report = build_audit_report(
        "770001", StudentRecord(history, [planned("test-3000", "26W")]), catalog, True
    )
    assert report == {
        "student_id": "770001",
        "status": "ok",
        "timeline_validation": [],
        "cross_list_violations": [],
        "credit_summary": {
            "total_earned": 118,
            "total_planned": 6,
            "total_remaining_for_graduation": 0,
        },
    }
