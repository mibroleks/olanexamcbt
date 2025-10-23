from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from typing import Optional
import sqlite3, csv, os
from io import StringIO

# ---------------------------------------------
# APP INITIALIZATION
# ---------------------------------------------
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="super-secret-session-key")

# Ensure directories exist
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Database file & Admin credentials
DB_FILE = "school.db"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# ---------------------------------------------
# DATABASE CONNECTION & INITIALIZATION
# ---------------------------------------------
def get_db_connection():
    """Returns a SQLite connection with row factory for dict-like access"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they don't exist"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            admission_number TEXT UNIQUE NOT NULL,
            class_name TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            class_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------
# STUDENT LOGIN (WEB)
# ---------------------------------------------
@app.get("/", response_class=HTMLResponse)
def student_login(request: Request):
    """Render student login page"""
    # ✅ Added by ChatGPT: Auto-redirect if already logged in
    if request.session.get("student_id"):
        return RedirectResponse("/student/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def handle_student_login(request: Request, admission_number: str = Form(...)):
    """Handle student login via form submission"""
    conn = get_db_connection()
    student = conn.execute(
        "SELECT * FROM students WHERE admission_number = ?", (admission_number,)
    ).fetchone()

    active_links = []
    links = []

    if student:
        # ✅ Added by ChatGPT: Remember logged-in student in session
        request.session["student_id"] = student["id"]

        # ✅ Fetch all active links for student's class (multi-active links support)
        active_links = conn.execute(
            "SELECT * FROM links WHERE class_name = ? AND is_active = 1",
            (student["class_name"],)
        ).fetchall()

        # ✅ Fetch all other links for the class (inactive)
        links_all = conn.execute(
            "SELECT * FROM links WHERE class_name = ?",
            (student["class_name"],)
        ).fetchall()

        # Exclude active links from general list
        active_ids = [link["id"] for link in active_links]
        links = [link for link in links_all if link["id"] not in active_ids]

    conn.close()

    if student:
        # ✅ Render student dashboard template with multi-active links support
        return templates.TemplateResponse(
            "student_dashboard.html",
            {
                "request": request,
                "student": student,
                "active_links": active_links,
                "links": links,
                # ✅ Added safe defaults for pagination vars if template uses them
                "link_page": 1,
                "page": 1
            }
        )

    # Invalid admission number
    return templates.TemplateResponse(
        "login.html", {"request": request, "msg": "Invalid Admission Number."}
    )

# ✅ NEW: STUDENT LOGOUT (ADDED BY CHATGPT)
@app.get("/logout")
def student_logout(request: Request):
    """Logout student by clearing session"""
    request.session.clear()  # ✅ Clear all session data (logout student)
    return RedirectResponse("/", status_code=303)  # ✅ Redirect to login page

# ✅ NEW: STUDENT DASHBOARD ROUTE (ADDED BY CHATGPT)
"""
@app.get("/student/dashboard", response_class=HTMLResponse)
def student_dashboard(request: Request):
#    "Render dashboard if logged in""
    student_id = request.session.get("student_id")
    if not student_id:
        return RedirectResponse("/", status_code=303)

    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    # ✅ Fetch active/inactive links again
    active_links = conn.execute(
        "SELECT * FROM links WHERE class_name = ? AND is_active = 1",
        (student["class_name"],)
    ).fetchall()
    links_all = conn.execute(
        "SELECT * FROM links WHERE class_name = ?",
        (student["class_name"],)
    ).fetchall()
    active_ids = [link["id"] for link in active_links]
    links = [link for link in links_all if link["id"] not in active_ids]
    conn.close()

    return templates.TemplateResponse(
        "student_dashboard.html",
        {
            "request": request,
            "student": student,
            "active_links": active_links,
            "links": links,
            "link_page": 1,
            "page": 1
        }
    )
"""

@app.get("/student/dashboard", response_class=HTMLResponse)
def student_dashboard(request: Request, link_page: int = 1):
    """Render student dashboard (with multi-active link support & pagination)"""
    student_id = request.session.get("student_id")
    if not student_id:
        # no session → redirect to login
        return RedirectResponse("/", status_code=303)

    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    # Fetch all links for this student's class
    all_links = conn.execute(
        "SELECT * FROM links WHERE class_name = ? ORDER BY id DESC",
        (student["class_name"],)
    ).fetchall()
    conn.close()

    # Split into active & inactive
    active_links = [l for l in all_links if l["is_active"] == 1]
    inactive_links = [l for l in all_links if l["is_active"] == 0]

    # ✅ Add pagination for inactive links
    per_page = 5
    total_pages = max(1, (len(inactive_links) + per_page - 1) // per_page)
    link_page = max(1, min(link_page, total_pages))
    start = (link_page - 1) * per_page
    end = start + per_page
    paginated_links = inactive_links[start:end]

    return templates.TemplateResponse(
        "student_dashboard.html",
        {
            "request": request,
            "student": student,
            "active_links": active_links,
            "links": paginated_links,
            "link_page": link_page,
            "total_pages": total_pages
        }
    )

# ---------------------------------------------
# ADMIN LOGIN / LOGOUT
# ---------------------------------------------
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request, msg: str = ""):
    """Render admin login page"""
    return templates.TemplateResponse("admin_login.html", {"request": request, "msg": msg})

@app.post("/admin/login")
def handle_admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Process admin login"""
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["admin"] = True
        return RedirectResponse("/admin/dashboard", status_code=303)
    return RedirectResponse("/admin/login?msg=Invalid+credentials", status_code=303)

@app.get("/admin/logout")
def admin_logout(request: Request):
    """Logout admin and clear session"""
    request.session.clear()
    return RedirectResponse("/admin/login?msg=Logged+out", status_code=303)

# ---------------------------------------------
# ADMIN DASHBOARD (CLASS FILTER + PAGINATION)
# ---------------------------------------------
@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, class_name: Optional[str] = None, page: int = 1, link_page: int = 1):
    """Render admin dashboard with students and links"""
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login?msg=Please+login", status_code=303)

    conn = get_db_connection()

    # 1️⃣ Filter students & links by class if provided
    if class_name:
        students = conn.execute(
            "SELECT * FROM students WHERE class_name = ?", (class_name,)
        ).fetchall()
        links = conn.execute(
            "SELECT * FROM links WHERE class_name = ?", (class_name,)
        ).fetchall()
    else:
        students = conn.execute("SELECT * FROM students").fetchall()
        links = conn.execute("SELECT * FROM links").fetchall()

    # 2️⃣ Get unique classes for dropdown
    classes = [row["class_name"] for row in conn.execute("SELECT DISTINCT class_name FROM students").fetchall()]

    conn.close()

    # ✅ Added by ChatGPT: Always pass link_page to prevent undefined error
    
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "students": students,
            "links": links,
            "selected_class": class_name,
            "classes": classes,
            "link_page": link_page,
            "total_link_pages": 1,          # ✅ Jinja expects this name
            "student_page": page,           # ✅ Match template variable
            "total_student_pages": 1        # ✅ Match template variable
        }
    )


# ---------------------------------------------
# ADMIN STUDENT MANAGEMENT
# ---------------------------------------------
@app.post("/admin/add_student")
def add_student(name: str = Form(...), admission_number: str = Form(...), class_name: str = Form(...)):
    """Add a new student"""
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO students (name, admission_number, class_name) VALUES (?, ?, ?)",
            (name.strip(), admission_number.strip(), class_name.strip())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Duplicate admission number skipped
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/delete_student")
def delete_student(admission_number: str = Form(...)):
    """Delete a student by admission number"""
    conn = get_db_connection()
    conn.execute("DELETE FROM students WHERE admission_number = ?", (admission_number,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/upload_csv")
async def upload_csv(csv_file: UploadFile = File(...)):
    """Upload CSV file to add multiple students"""
    content = await csv_file.read()
    reader = csv.reader(StringIO(content.decode("utf-8")))
    conn = get_db_connection()
    for row in reader:
        if len(row) >= 3:
            name, admission_number, class_name = row[0].strip(), row[1].strip(), row[2].strip()
            try:
                conn.execute(
                    "INSERT INTO students (name, admission_number, class_name) VALUES (?, ?, ?)",
                    (name, admission_number, class_name)
                )
            except sqlite3.IntegrityError:
                continue
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

# ✅ NEW: Delete all students (optional per class)
@app.post("/admin/delete_all_students")
def delete_all_students(class_name: Optional[str] = Form(None)):
    """Delete all students, optionally filtered by class"""
    conn = get_db_connection()
    if class_name:
        conn.execute("DELETE FROM students WHERE class_name = ?", (class_name,))
    else:
        conn.execute("DELETE FROM students")
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

# ---------------------------------------------
# ADMIN LINKS MANAGEMENT
# ---------------------------------------------
@app.post("/admin/upload_link")
def upload_link(name: str = Form(...), link: str = Form(...), class_name: str = Form(...)):
    """Upload a new form link"""
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO links (name, url, class_name) VALUES (?, ?, ?)",
        (name.strip(), link.strip(), class_name.strip())
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

# ✅ NEW: Upload multiple links via CSV
@app.post("/admin/upload_links_csv")
async def upload_links_csv(csv_file: UploadFile = File(...)):
    """Upload CSV file to add multiple links"""
    content = await csv_file.read()
    reader = csv.reader(StringIO(content.decode("utf-8")))
    conn = get_db_connection()
    for row in reader:
        if len(row) >= 3:
            name, url, class_name = row[0].strip(), row[1].strip(), row[2].strip()
            conn.execute(
                "INSERT INTO links (name, url, class_name) VALUES (?, ?, ?)",
                (name, url, class_name)
            )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/toggle_link/{link_id}")
def toggle_link(link_id: int):
    """Toggle a link's active state (supports multiple active links)"""
    conn = get_db_connection()
    link = conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if not link:
        conn.close()
        return JSONResponse({"status": "error", "message": "Link not found"}, status_code=404)
    new_state = 0 if link["is_active"] == 1 else 1
    conn.execute("UPDATE links SET is_active = ? WHERE id = ?", (new_state, link_id))
    conn.commit()
    conn.close()
    return JSONResponse({"status": "success", "id": link_id, "new_state": new_state})

@app.post("/admin/delete_link/{link_id}")
def delete_link(link_id: int):
    """Delete a link"""
    conn = get_db_connection()
    conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
    conn.commit()
    conn.close()
    return JSONResponse({"status": "success"})

# ✅ NEW: Delete all links (optional per class)
@app.post("/admin/delete_all_links")
def delete_all_links(class_name: Optional[str] = Form(None)):
    """Delete all links, optionally filtered by class"""
    conn = get_db_connection()
    if class_name:
        conn.execute("DELETE FROM links WHERE class_name = ?", (class_name,))
    else:
        conn.execute("DELETE FROM links")
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

# ---------------------------------------------
# JSON STUDENT LOGIN (API)
# ---------------------------------------------
@app.post("/student_login")
async def student_login_json(data: dict):
    """API endpoint for JSON student login (mobile/SPA)"""
    admission_number = data.get("admission_number")
    if not admission_number:
        return JSONResponse({"detail": "Admission number required."}, status_code=400)

    conn = get_db_connection()
    student = conn.execute(
        "SELECT * FROM students WHERE admission_number = ?", (admission_number,)
    ).fetchone()
    if not student:
        conn.close()
        return JSONResponse({"detail": "Invalid Admission Number."}, status_code=401)

    # ✅ Fetch all active links for the student's class
    active_links = conn.execute(
        "SELECT url, name FROM links WHERE class_name = ? AND is_active = 1",
        (student["class_name"],)
    ).fetchall()
    conn.close()

    if not active_links:
        return JSONResponse({"detail": "No active form links."}, status_code=404)

    links_data = [{"name": l["name"], "url": l["url"]} for l in active_links]
    return JSONResponse({"student": dict(student), "active_links": links_data})

# ---------------------------------------------
# GLOBAL ERROR HANDLERS
# ---------------------------------------------
@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions"""
    print(f"🔥 Internal error: {exc}")
    return PlainTextResponse(f"Internal Server Error: {exc}", status_code=500)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTP exceptions handler"""
    return PlainTextResponse(f"HTTP Error: {exc.detail}", status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Request validation errors handler"""
    return PlainTextResponse(f"Validation Error: {exc}", status_code=422)
