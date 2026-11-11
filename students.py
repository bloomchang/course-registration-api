import re
from dataclasses import dataclass, field
from typing import Annotated

from bs4 import BeautifulSoup
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/students/{student_id}")
TRANSCRIPT_COLUMNS = {"status", "course", "grade", "term", "credits"}
PAST_STATUSES = {"Completed", "In-Progress", "Attempted"}


class HistoryCourse(BaseModel):
    course_code: str
    term: str
    credits_earned: int
    status: str


class PlannedCourse(BaseModel):
    course_code: str
    term: str


class HistoryPayload(BaseModel):
    history: list[HistoryCourse]


class PlanPayload(BaseModel):
    planned_courses: list[PlannedCourse]


@dataclass
class StudentRecord:
    history: list[HistoryCourse] = field(default_factory=list)
    plan: list[PlannedCourse] = field(default_factory=list)


def grade_rank(grade: str) -> int:
    if re.fullmatch(r"\d+(?:\.\d+)?%?", grade):
        return 2
    if grade.upper() != "P" and re.fullmatch(r"[A-Za-z][+-]?", grade):
        return 1
    return 0


def parse_credits(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return 0


def parse_transcript(html: bytes) -> list[HistoryCourse]:
    soup = BeautifulSoup(html, "html.parser")
    best_rows = {}
    found_header = False

    for table in soup.find_all("table"):
        columns = {}
        for row in table.find_all("tr"):
            if row.find_parent("table") is not table:
                continue
            cells = row.find_all(["th", "td"], recursive=False)
            values = [cell.get_text(" ", strip=True) for cell in cells]
            labels = {label.casefold(): index for index, label in enumerate(values)}
            if TRANSCRIPT_COLUMNS <= labels.keys():
                columns = {name: labels[name] for name in TRANSCRIPT_COLUMNS}
                found_header = True
                continue
            if not columns or len(values) <= max(columns.values()):
                continue

            status = values[columns["status"]]
            term = values[columns["term"]]
            if status not in PAST_STATUSES or not term:
                continue

            code = values[columns["course"]]
            credits = parse_credits(values[columns["credits"]])
            rank = (grade_rank(values[columns["grade"]]), credits)
            key = (code, term)
            if key not in best_rows or rank > best_rows[key][0]:
                best_rows[key] = (
                    rank,
                    HistoryCourse(
                        course_code=code,
                        term=term,
                        credits_earned=credits,
                        status=status,
                    ),
                )

    if not found_header:
        raise HTTPException(400, "No transcript course table found")
    return [course for _, course in best_rows.values()]


def get_student(student_id: str, request: Request) -> StudentRecord:
    student = request.app.state.students.get(student_id)
    if student is None:
        raise HTTPException(404, "Student not found")
    return student


CurrentStudent = Annotated[StudentRecord, Depends(get_student)]


@router.post("/history/import", status_code=201)
async def import_history(
    student_id: str, request: Request, file: Annotated[UploadFile, File()]
):
    try:
        content = await file.read()
    finally:
        await file.close()

    history = await run_in_threadpool(parse_transcript, content)
    student = request.app.state.students.setdefault(student_id, StudentRecord())
    student.history = history
    return {"status": "success", "past_courses_imported": len(history)}


@router.put("/history")
def replace_history(payload: HistoryPayload, student: CurrentStudent):
    student.history = payload.history
    return {"status": "success", "message": "Academic history updated successfully"}


@router.delete("/history", status_code=204)
def clear_history(student: CurrentStudent):
    student.history = []
    return Response(status_code=204)


@router.post("/plan")
@router.put("/plan")
def save_plan(payload: PlanPayload, student: CurrentStudent):
    student.plan = payload.planned_courses
    return {"status": "success", "planned_courses_saved": len(payload.planned_courses)}


@router.delete("/plan", status_code=204)
def clear_plan(student: CurrentStudent):
    student.plan = []
    return Response(status_code=204)


@router.get("/profile")
def get_profile(student_id: str, student: CurrentStudent):
    return {"student_id": student_id, "history": student.history, "plan": student.plan}
