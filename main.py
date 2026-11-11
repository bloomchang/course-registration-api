from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, UploadFile

from audit import COURSE_CODE, build_audit_report, normalize_code
from students import CurrentStudent, router as student_router

app = FastAPI()
app.state.students = {}
app.state.catalog = {}
app.include_router(student_router)


def extract_codes(text):
    matches = COURSE_CODE.findall(text.upper())
    codes = [subject + number for subject, number in matches]

    # Remove duplicates while keeping their original order.
    return list(dict.fromkeys(codes))


@app.get("/")
def home():
    return {"message": "Course Registration API is running"}


@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile):
    # Limit the amount read into memory to 5 MB.
    max_size = 5 * 1024 * 1024
    try:
        content = await file.read(max_size + 1)
    finally:
        await file.close()

    if len(content) > max_size:
        raise HTTPException(413, "File exceeds the 5 MB limit.")

    soup = BeautifulSoup(content, "html.parser")
    table = soup.find("table")

    if table is None:
        raise HTTPException(400, "No course table found.")

    imported = {}

    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)

        # Skip the header row.
        if not cells:
            continue

        if len(cells) != 5:
            raise HTTPException(400, "Each course row must have five columns.")

        values = [cell.get_text(" ", strip=True) for cell in cells]
        code, title, credits_text, prerequisites, cross_listed = values

        course_code = normalize_code(code)
        if not COURSE_CODE.fullmatch(course_code):
            raise HTTPException(400, f"Invalid course code: {code}")

        try:
            credits = float(credits_text)
        except ValueError:
            raise HTTPException(400, f"Invalid credits for {code}")

        if not 0 <= credits < float("inf"):
            raise HTTPException(400, f"Invalid credits for {code}")

        imported[course_code] = {
            "course_code": course_code,
            "title": title,
            "credits": credits,
            "prerequisites": extract_codes(prerequisites),
            "cross_listed": extract_codes(cross_listed),
        }

    if not imported:
        raise HTTPException(400, "The table contains no courses.")

    # Replace the catalog only after the whole file passes validation.
    app.state.catalog = imported

    return {
        "message": "Catalog imported successfully",
        "imported_count": len(imported),
    }


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):
    course = app.state.catalog.get(normalize_code(course_code))
    if course is None:
        raise HTTPException(404, "Course not found.")
    return course


@app.get("/api/v1/students/{student_id}/audit-report")
def audit_report(student_id: str, student: CurrentStudent, strict: bool = False):
    try:
        return build_audit_report(student_id, student, app.state.catalog, strict)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
