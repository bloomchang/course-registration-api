from uuid import uuid4

import pytest


def upload_catalog(client, html):
    return client.post(
        "/api/v1/admin/catalog/import",
        files={"file": ("catalog.html", html, "text/html")},
    )


def test_catalog_import_and_lookup(client):
    assert client.get("/").status_code == 200
    response = upload_catalog(
        client,
        """<table><tr><th>Course</th></tr>
        <tr><td>COSC-3506</td><td>Software Engineering</td><td>3</td>
        <td>COSC 2007, COSC-2007</td><td>ITEC-3506</td></tr></table>""",
    )
    assert response.status_code == 200
    assert response.json()["imported_count"] == 1

    response = client.get("/api/v1/catalog/courses/cosc%203506")
    assert response.status_code == 200
    assert response.json() == {
        "course_code": "COSC3506",
        "title": "Software Engineering",
        "credits": 3,
        "prerequisites": ["COSC2007"],
        "cross_listed": ["ITEC3506"],
    }
    assert client.get("/api/v1/catalog/courses/NOPE1000").status_code == 404


@pytest.mark.parametrize(
    "html",
    [
        "<p>No catalog</p>",
        "<table></table>",
        "<table><tr><td>Only one cell</td></tr></table>",
        "<table><tr><td>bad-code</td><td>Title</td><td>3</td><td></td><td></td></tr></table>",
        "<table><tr><td>TEST1000</td><td>Title</td><td>bad</td><td></td><td></td></tr></table>",
        "<table><tr><td>TEST1000</td><td>Title</td><td>nan</td><td></td><td></td></tr></table>",
    ],
)
def test_catalog_rejects_invalid_files(client, html):
    assert upload_catalog(client, html).status_code == 400


def test_audit_report_uses_imported_catalog_history_and_plan(client):
    catalog = """<table>
        <tr><td>TEST-1000</td><td>Foundation</td><td>3</td><td></td><td></td></tr>
        <tr><td>TEST 2000</td><td>Next course</td><td>4</td><td>test-1000</td><td></td></tr>
        <tr><td>TEST3000</td><td>Advanced</td><td>3</td><td>TEST-2000</td><td></td></tr>
        <tr><td>ITEC-1000</td><td>Cross-listed foundation</td><td>3</td><td></td><td>TEST 1000</td></tr>
    </table>"""
    assert upload_catalog(client, catalog).status_code == 200

    student_id = uuid4().hex
    path = f"/api/v1/students/{student_id}"
    transcript = """<table>
        <tr><th>Status</th><th>Course</th><th>Title</th><th>Grade</th><th>Term</th><th>Credits</th></tr>
        <tr><td>Attempted</td><td>TEST1000</td><td>Foundation</td><td>F</td><td>25F</td><td>0</td></tr>
        <tr><td>Completed</td><td>TEST 1000</td><td>Foundation</td><td>90</td><td>26SP</td><td>3</td></tr>
        <tr><td>Completed</td><td>test-1000</td><td>Foundation</td><td>93</td><td>26S</td><td>3</td></tr>
    </table>"""
    response = client.post(
        f"{path}/history/import",
        files={"file": ("transcript.html", transcript, "text/html")},
    )
    assert response.status_code == 201
    assert response.json()["past_courses_imported"] == 3

    plan = [
        {"course_code": "test3000", "term": "26F"},
        {"course_code": "test 2000", "term": "26SP"},
        {"course_code": "ITEC1000", "term": "26S"},
    ]
    response = client.post(f"{path}/plan", json={"planned_courses": plan})
    assert response.status_code == 200

    response = client.get(f"{path}/audit-report")
    assert response.status_code == 200
    report = response.json()
    assert report == {
        "student_id": student_id,
        "status": "warning",
        "timeline_validation": [
            {
                "term": "26SP",
                "errors": [
                    {
                        "course_code": "TEST-2000",
                        "type": "MISSING_PREREQUISITE",
                        "message": "Missing prerequisite: TEST-1000",
                    }
                ],
            },
            {
                "term": "26F",
                "errors": [
                    {
                        "course_code": "TEST-3000",
                        "type": "MISSING_PREREQUISITE",
                        "message": "Missing prerequisite: TEST-2000",
                    }
                ],
            },
        ],
        "cross_list_violations": [
            {
                "course_code": "ITEC-1000",
                "type": "CROSS_LIST_CONFLICT",
                "message": "Cross-listed with completed course TEST-1000",
            }
        ],
        "credit_summary": {
            "total_earned": 3,
            "total_planned": 10,
            "total_remaining_for_graduation": 107,
        },
    }
    response = client.get(f"{path}/audit-report", params={"strict": "true"})
    assert response.status_code == 200
    assert response.json() == {**report, "status": "failed"}

    plan = [{"course_code": "TEST2000", "term": "26F"}]
    assert client.put(f"{path}/plan", json={"planned_courses": plan}).status_code == 200
    response = client.get(f"{path}/audit-report", params={"strict": "true"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    assert (
        client.get(f"{path}/audit-report", params={"strict": "maybe"}).status_code
        == 422
    )
    plan[0]["term"] = "Fall 2026"
    assert client.put(f"{path}/plan", json={"planned_courses": plan}).status_code == 200
    assert client.get(f"{path}/audit-report").status_code == 422


def test_audit_report_unknown_student(client):
    response = client.get(f"/api/v1/students/{uuid4().hex}/audit-report")
    assert response.status_code == 404
