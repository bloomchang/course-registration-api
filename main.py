import re

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, UploadFile

app = FastAPI()

# Courses stay here while the server is running.
catalog = {}

# Match codes such as COSC 3506, ITEC3506, or MATH 1001.
CODE_PATTERN = re.compile(r"\b([A-Z]{2,10})\s*(\d{3,4}[A-Z]?)\b")


def normalize_code(text):
    return re.sub(r"\s+", "", text).upper()


def extract_codes(text):
    matches = CODE_PATTERN.findall(text.upper())
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

        if not CODE_PATTERN.fullmatch(code.upper()):
            raise HTTPException(400, f"Invalid course code: {code}")

        try:
            credits = float(credits_text)
        except ValueError:
            raise HTTPException(400, f"Invalid credits for {code}")

        if not 0 <= credits < float("inf"):
            raise HTTPException(400, f"Invalid credits for {code}")

        course_code = normalize_code(code)

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
    catalog.clear()
    catalog.update(imported)

    return {
        "message": "Catalog imported successfully",
        "imported_count": len(imported),
    }


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):
    code = normalize_code(course_code)

    if code not in catalog:
        raise HTTPException(404, "Course not found.")

    return catalog[code]