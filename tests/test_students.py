from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4


def transcript(*rows):
    head = "<tr><th>Status</th><th>Course</th><th></th><th>Grade</th><th>Term</th><th>Credits</th></tr>"
    body = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>" for row in rows
    )
    return f"<table>{head}{body}</table>"


def history_item(code, term, credits, status):
    return {
        "course_code": code,
        "term": term,
        "credits_earned": credits,
        "status": status,
    }


def student_path():
    return f"/api/v1/students/{uuid4().hex}"


def upload(client, path, html):
    return client.post(
        f"{path}/history/import", files={"file": ("transcript.html", html, "text/html")}
    )


def test_history_import_reads_all_course_tables_and_deduplicates(client):
    path = student_path()
    html = "<table><tr><td>Other transcript metadata</td></tr></table>" + transcript(
        ("Completed", "COSC-1046", "Programming", "P", "23F", "6"),
        ("Completed", "COSC-1047", "Programming II", "A", "24W", "3"),
        ("Attempted", "COSC-1047L", "Lab", "F", "24W", ""),
        ("In-Progress", "COSC-2006", "Data Structures", "", "25F", "3"),
        ("Completed", "COSC-9991", "No term", "A", "", "3"),
        ("Fulfilled", "COSC-9992", "Requirement", "", "25F", "3"),
        ("Planned", "COSC-9993", "Placeholder", "", "26W", "3"),
    )
    html += transcript(
        ("Completed", "COSC-1046", "Programming", "B+", "23F", "5"),
        ("Completed", "COSC-1046", "Programming", "80", "23F", "1"),
        ("Completed", "COSC-1046", "Programming", "84.5", "23F", "3"),
        ("Attempted", "COSC-1046", "Programming", "F", "23W", "0"),
        ("Completed", "COSC-1047L", "Lab retake", "P", "24F", "0"),
        ("Completed", "ITEC 3000", "Verbatim code", "P", "24F", "N/A"),
    )

    response = upload(client, path, html)
    assert response.status_code == 201
    assert response.json() == {"status": "success", "past_courses_imported": 7}
    assert client.get(f"{path}/profile").json() == {
        "student_id": path.rsplit("/", 1)[1],
        "history": [
            history_item("COSC-1046", "23F", 3, "Completed"),
            history_item("COSC-1047", "24W", 3, "Completed"),
            history_item("COSC-1047L", "24W", 0, "Attempted"),
            history_item("COSC-2006", "25F", 3, "In-Progress"),
            history_item("COSC-1046", "23W", 0, "Attempted"),
            history_item("COSC-1047L", "24F", 0, "Completed"),
            history_item("ITEC 3000", "24F", 0, "Completed"),
        ],
        "plan": [],
    }


def test_history_and_plan_lifecycle(client):
    path = student_path()
    original = transcript(("Completed", "COSC-1046", "Programming", "80", "23F", "3"))
    assert upload(client, path, original).status_code == 201

    original_plan = [{"course_code": "COSC-3506", "term": "26F"}]
    response = client.post(f"{path}/plan", json={"planned_courses": original_plan})
    assert response.status_code == 200
    assert response.json() == {"status": "success", "planned_courses_saved": 1}

    history = [history_item("MATH-1001", "23F", 3, "Completed")]
    assert client.put(f"{path}/history", json={"history": history}).status_code == 200
    assert client.get(f"{path}/profile").json()["history"] == history

    new_plan = [{"course_code": "COSC-4406", "term": "27W"}]
    response = client.put(f"{path}/plan", json={"planned_courses": new_plan})
    assert response.status_code == 200
    assert response.json()["planned_courses_saved"] == 1
    assert client.get(f"{path}/profile").json()["plan"] == new_plan

    assert upload(client, path, original).status_code == 201
    assert client.get(f"{path}/profile").json()["plan"] == new_plan
    assert client.delete(f"{path}/history").status_code == 204
    assert client.get(f"{path}/profile").json()["history"] == []
    assert client.get(f"{path}/profile").json()["plan"] == new_plan
    assert client.delete(f"{path}/plan").status_code == 204
    assert client.get(f"{path}/profile").json()["plan"] == []


def test_unknown_student_and_wrong_verbs(client):
    path = student_path()
    assert upload(client, path, "<p>No transcript table</p>").status_code == 400
    assert client.get(f"{path}/profile").status_code == 404
    assert client.put(f"{path}/history", json={"history": []}).status_code == 404
    assert client.delete(f"{path}/history").status_code == 404
    assert client.post(f"{path}/plan", json={"planned_courses": []}).status_code == 404
    assert client.put(f"{path}/plan", json={"planned_courses": []}).status_code == 404
    assert client.delete(f"{path}/plan").status_code == 404
    assert client.get(f"{path}/history/import").status_code == 405
    assert client.get(f"{path}/plan").status_code == 405
    assert client.post(f"{path}/profile").status_code == 405


def test_concurrent_uploads_remain_isolated(client):
    paths = [student_path(), student_path()]
    codes = ["COSC-1046", "MATH-1001"]

    def import_student(path, code):
        html = transcript(("Completed", code, "Course title", "90", "23F", "3"))
        assert upload(client, path, html).status_code == 201

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(import_student, paths, codes))

    for path, code in zip(paths, codes):
        assert client.get(f"{path}/profile").json()["history"] == [
            history_item(code, "23F", 3, "Completed")
        ]
