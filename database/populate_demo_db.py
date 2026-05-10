"""
Demo database seed — Spring 2026
Run: python populate_demo_db.py
Requires an empty academia_main.db (run init_db.py first).

Rules:
  - All emails @bis.edu
  - No fake resources (professors upload real files via the platform)
  - No quiz/exam grades — platform only has assignment submissions
  - Fixed random seed for reproducibility
  - Attendance covers all 6 courses; late counts as present (consistent with backend)
"""

import sqlite3
import bcrypt
import uuid
import os
import random
from datetime import datetime, timedelta, date

random.seed(42)   # reproducible data

DB_PATH = os.path.join(os.path.dirname(__file__), "academia_main.db")

def hp(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def uid():
    return str(uuid.uuid4())

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ── wipe existing data (keep schema) ──────────────────────────────────────────
for t in ["question_answers","questions","grades","student_submissions",
          "assignments","announcements","attendance","enrollments",
          "resources","notifications","courses","users"]:
    cur.execute(f"DELETE FROM {t}")
conn.commit()
print("Tables cleared.")

# ── helpers ──────────────────────────────────────────────────────────────────
START = date(2026, 1, 20)   # semester start
TODAY = date(2026, 3, 13)   # "today" in the demo

def sessions_between(start, end, weekdays):
    """Return list of date strings for dates between start/end on given weekdays (0=Mon…6=Sun)."""
    out = []
    d = start
    while d <= end:
        if d.weekday() in weekdays:
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out

def past(days):
    return (TODAY - timedelta(days=days)).strftime("%Y-%m-%d")

def future(days):
    return (TODAY + timedelta(days=days)).strftime("%Y-%m-%d")

# ── users ─────────────────────────────────────────────────────────────────────
users = [
    # (key, first, last, email, pw, role)
    ("prof1",    "Ahmed",   "El-Sayed",       "ahmed.elsayed@bis.edu",     "prof123",    "professor"),
    ("prof2",    "Mona",    "Hassan",          "mona.hassan@bis.edu",       "prof123",    "professor"),
    ("prof3",    "Tarek",   "Abdel-Fattah",    "tarek.abdelfattah@bis.edu", "prof123",    "professor"),

    ("s1",  "Omar",    "Farouk",   "omar.farouk@bis.edu",    "student123", "student"),
    ("s2",  "Nour",    "Ibrahim",  "nour.ibrahim@bis.edu",   "student123", "student"),
    ("s3",  "Youssef", "Mostafa",  "youssef.mostafa@bis.edu","student123", "student"),
    ("s4",  "Salma",   "Khalil",   "salma.khalil@bis.edu",   "student123", "student"),
    ("s5",  "Khaled",  "Mansour",  "khaled.mansour@bis.edu", "student123", "student"),
    ("s6",  "Hana",    "Soliman",  "hana.soliman@bis.edu",   "student123", "student"),
    ("s7",  "Mohamed", "Adel",     "mohamed.adel@bis.edu",   "student123", "student"),
    ("s8",  "Dina",    "Naguib",   "dina.naguib@bis.edu",    "student123", "student"),
    ("s9",  "Ali",     "Rashad",   "ali.rashad@bis.edu",     "student123", "student"),
    ("s10", "Farida",  "Helmy",    "farida.helmy@bis.edu",   "student123", "student"),
]

U = {}   # key -> user_id
for key, first, last, email, pw, role in users:
    user_id = uid()
    U[key] = user_id
    cur.execute("""
        INSERT INTO users (user_id, email, password_hash, first_name, last_name, role, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, email, hp(pw), first, last, role,
          datetime(2026, 1, 10).isoformat()))

print(f"Inserted {len(users)} users.")

# ── courses ───────────────────────────────────────────────────────────────────
#  (key, code, name, prof_key, weekdays, description)
courses_def = [
    ("bis101", "BIS101", "Introduction to Business Information Systems", "prof1", [6, 1],
     "Overview of information systems in business. Covers system types, IT infrastructure, and the role of IS in organizations."),
    ("bis201", "BIS201", "Database Management Systems", "prof1", [0, 2],
     "Relational databases, SQL, normalisation, ER diagrams, and database design for business applications."),
    ("bis301", "BIS301", "Systems Analysis and Design", "prof2", [1, 3],
     "Software development lifecycle, requirements gathering, UML diagrams, and system design methodologies."),
    ("bis202", "BIS202", "Web Development for Business", "prof2", [0, 3],
     "HTML, CSS, JavaScript and web frameworks. Building business web applications and e-commerce basics."),
    ("bis302", "BIS302", "Enterprise Resource Planning", "prof3", [2, 5],
     "ERP concepts, SAP fundamentals, business process integration, and enterprise system implementation."),
    ("bis401", "BIS401", "IT Project Management", "prof3", [6, 2],
     "Project planning, scheduling, risk management, agile methodology, and team collaboration tools."),
]

C = {}   # key -> course_id
for key, code, name, prof_key, _, desc in courses_def:
    course_id = uid()
    C[key] = course_id
    cur.execute("""
        INSERT INTO courses (course_id, course_code, course_name, description,
                             instructor_id, semester, year, created_at)
        VALUES (?, ?, ?, ?, ?, 'Spring', 2026, ?)
    """, (course_id, code, name, desc, U[prof_key],
          datetime(2026, 1, 10).isoformat()))

print(f"Inserted {len(courses_def)} courses.")

# ── enrolments ────────────────────────────────────────────────────────────────
enrolments = [
    # BIS101 — everyone
    *[(f"s{i}", "bis101") for i in range(1, 11)],
    # BIS201 — 8 students
    *[(s, "bis201") for s in ["s1","s2","s3","s4","s5","s7","s8","s9"]],
    # BIS301 — 6 students
    *[(s, "bis301") for s in ["s1","s3","s5","s6","s7","s10"]],
    # BIS202 — 6 students
    *[(s, "bis202") for s in ["s2","s4","s6","s8","s9","s10"]],
    # BIS302 — 5 students
    *[(s, "bis302") for s in ["s1","s2","s5","s6","s8"]],
    # BIS401 — 5 students
    *[(s, "bis401") for s in ["s3","s4","s7","s9","s10"]],
]

for student_key, course_key in enrolments:
    cur.execute("""
        INSERT INTO enrollments (enrollment_id, student_id, course_id, status, enrolled_at)
        VALUES (?, ?, ?, 'active', ?)
    """, (uid(), U[student_key], C[course_key],
          datetime(2026, 1, 20).isoformat()))

print(f"Inserted {len(enrolments)} enrolments.")

# ── attendance ────────────────────────────────────────────────────────────────
# Attendance profiles: weights for [present, absent, late]
# "late" counts as present  →  effective rate ≈ present_w + late_w
PROFILES = {
    "excellent":    [88, 6,  6],   # ~94% effective
    "good":         [78, 12, 10],  # ~88% effective
    "ok":           [70, 18, 12],  # ~82% effective
    "medium_risk":  [63, 27, 10],  # ~73% effective  (approaching 75% threshold)
    "high_risk":    [55, 37,  8],  # ~63% effective  (below 65% — high risk)
}

# Per-student profile per course
# Format: { student_key: { course_key: profile_name } }
student_profiles = {
    "s1":  {"bis101":"excellent","bis201":"excellent","bis301":"excellent","bis302":"excellent"},
    "s2":  {"bis101":"good",     "bis201":"good",     "bis202":"good",     "bis302":"good"},
    "s3":  {"bis101":"good",     "bis201":"medium_risk","bis301":"good"},
    "s4":  {"bis101":"ok",       "bis201":"ok",       "bis202":"good"},
    "s5":  {"bis101":"medium_risk","bis201":"medium_risk","bis301":"good","bis302":"good"},
    "s6":  {"bis101":"good",     "bis301":"good",     "bis202":"ok",  "bis302":"good"},
    "s7":  {"bis101":"high_risk","bis201":"high_risk","bis301":"medium_risk","bis401":"ok"},
    "s8":  {"bis101":"good",     "bis201":"good",     "bis202":"ok",  "bis302":"good"},
    "s9":  {"bis101":"ok",       "bis201":"medium_risk","bis202":"ok", "bis401":"good"},
    "s10": {"bis101":"good",     "bis301":"good",     "bis202":"good","bis401":"excellent"},
}

# course_key -> (weekdays, prof_key)
course_schedule = {
    "bis101": ([6, 1], "prof1"),
    "bis201": ([0, 2], "prof1"),
    "bis301": ([1, 3], "prof2"),
    "bis202": ([0, 3], "prof2"),
    "bis302": ([2, 5], "prof3"),
    "bis401": ([6, 2], "prof3"),
}

# enrolled students per course
course_students = {}
for sk, ck in enrolments:
    course_students.setdefault(ck, []).append(sk)

def make_statuses(n, profile_name):
    """Return a deterministically-shuffled list of n statuses matching the target profile."""
    w = PROFILES[profile_name]
    total_w = sum(w)
    n_present = round(n * w[0] / total_w)
    n_absent  = round(n * w[1] / total_w)
    n_late    = n - n_present - n_absent
    if n_late < 0:          # rounding correction
        n_absent += n_late
        n_late = 0
    statuses = ["present"] * n_present + ["absent"] * n_absent + ["late"] * n_late
    random.shuffle(statuses)
    return statuses

att_rows = 0
for course_key, (weekdays, prof_key) in course_schedule.items():
    session_dates = sessions_between(START, TODAY, weekdays)
    n = len(session_dates)
    enrolled = course_students.get(course_key, [])
    for student_key in enrolled:
        profile_name = student_profiles.get(student_key, {}).get(course_key, "good")
        statuses = make_statuses(n, profile_name)
        for session_date, status in zip(session_dates, statuses):
            cur.execute("""
                INSERT INTO attendance (attendance_id, student_id, course_id, date,
                                        status, marked_by, marked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (uid(), U[student_key], C[course_key], session_date,
                  status, U[prof_key],
                  session_date + "T09:30:00"))
            att_rows += 1

print(f"Inserted {att_rows} attendance records.")

# ── assignments ───────────────────────────────────────────────────────────────
assignments_def = [
    # (course_key, title, description, due_offset_days, points, prof_key)

    # BIS101
    ("bis101", "IS Case Study Analysis",
     "Read the assigned case study on IT adoption in Egyptian organisations and write a 2-page critical analysis.",
     -14, 20, "prof1"),
    ("bis101", "Business Process Diagram",
     "Draw a business process diagram for an online shopping system using any modelling tool (draw.io, Lucidchart, etc.).",
     +7, 25, "prof1"),
    ("bis101", "IT Infrastructure Report",
     "Research and compare cloud vs on-premise solutions for a medium-sized Egyptian business. Min 3 pages.",
     +18, 30, "prof1"),

    # BIS201
    ("bis201", "ER Diagram Design",
     "Design an ER diagram for a university registration system with at least 6 entities. Include cardinalities.",
     -8, 30, "prof1"),
    ("bis201", "SQL Queries Assignment",
     "Write SQL queries to solve 10 database problems using the provided sample schema. Submit as a .sql file.",
     +6, 40, "prof1"),
    ("bis201", "Normalisation Worksheet",
     "Normalise the given un-normalised relation to 3NF. Show each step (1NF → 2NF → 3NF) with justification.",
     +20, 25, "prof1"),

    # BIS301
    ("bis301", "Requirements Specification Document",
     "Write a complete SRS for a hospital management system. Must include functional and non-functional requirements.",
     -6, 35, "prof2"),
    ("bis301", "UML Use Case & Activity Diagrams",
     "Create use case and activity diagrams for an e-commerce checkout process using standard UML notation.",
     +9, 30, "prof2"),

    # BIS202
    ("bis202", "Personal Portfolio Website",
     "Build a personal portfolio using HTML, CSS, and vanilla JavaScript. Must be responsive and include a contact form.",
     +8, 40, "prof2"),
    ("bis202", "JavaScript DOM Project",
     "Build a dynamic to-do list application using the DOM API. Must support add, delete, and mark-complete.",
     +21, 35, "prof2"),

    # BIS302
    ("bis302", "ERP Module Presentation",
     "Present on one SAP module (MM, SD, FI, or HR). Explain its purpose, key transactions, and business impact. 10 minutes.",
     -4, 25, "prof3"),
    ("bis302", "Business Process Mapping",
     "Map the order-to-cash process using a swimlane diagram and identify where an ERP system adds value.",
     +12, 30, "prof3"),

    # BIS401
    ("bis401", "Project Charter",
     "Write a formal project charter for your graduation project. Include scope, objectives, stakeholders, and timeline.",
     +11, 30, "prof3"),
    ("bis401", "Risk Assessment Matrix",
     "Create a risk matrix for an IT implementation project. Identify at least 8 risks with likelihood, impact, and mitigation.",
     +19, 25, "prof3"),
]

A = {}   # title -> assignment_id
for course_key, title, desc, due_offset, points, prof_key in assignments_def:
    aid = uid()
    A[title] = aid
    due_date = (TODAY + timedelta(days=due_offset)).strftime("%Y-%m-%d")
    created = (TODAY - timedelta(days=abs(due_offset) + 7)).isoformat()
    cur.execute("""
        INSERT INTO assignments (assignment_id, course_id, title, description,
                                 due_date, points, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (aid, C[course_key], title, desc, due_date, points, U[prof_key], created))

print(f"Inserted {len(assignments_def)} assignments.")

# ── submissions ───────────────────────────────────────────────────────────────
# Only for past-due assignments. Format:
# (student_key, assignment_title, status, score_or_None, feedback_or_None)
submissions_def = [
    # IS Case Study Analysis (past, 20 pts)
    ("s1",  "IS Case Study Analysis", "graded", 18, "Strong analysis, well-structured argument."),
    ("s2",  "IS Case Study Analysis", "graded", 15, "Decent but needs more depth in the recommendations section."),
    ("s3",  "IS Case Study Analysis", "graded", 20, "Excellent — thorough and well-referenced."),
    ("s4",  "IS Case Study Analysis", "graded", 13, "Too brief. Expand on the organisational impact."),
    ("s5",  "IS Case Study Analysis", "graded", 17, "Good work overall, minor formatting issues."),
    ("s6",  "IS Case Study Analysis", "graded", 16, "Solid analysis. Include more local examples next time."),
    ("s7",  "IS Case Study Analysis", "submitted", None, None),
    # s8, s9, s10 missed it

    # ER Diagram Design (past, 30 pts)
    ("s1",  "ER Diagram Design", "graded", 28, "Clean design, good normalisation, all relationships correct."),
    ("s2",  "ER Diagram Design", "graded", 23, "Missing the Enrollment entity relationship. Otherwise good."),
    ("s3",  "ER Diagram Design", "graded", 26, "Well done. Add cardinality labels for completeness."),
    ("s4",  "ER Diagram Design", "submitted", None, None),
    ("s5",  "ER Diagram Design", "graded", 22, "Correct entities but several missing foreign key constraints."),
    # s7, s8, s9 missed it

    # Requirements Specification Document (past, 35 pts)
    ("s1",  "Requirements Specification Document", "graded", 33, "Professional quality — very detailed and well-organised."),
    ("s3",  "Requirements Specification Document", "graded", 27, "Good but missing most non-functional requirements."),
    ("s5",  "Requirements Specification Document", "submitted", None, None),
    ("s6",  "Requirements Specification Document", "graded", 30, "Good structure. Functional requirements are thorough."),
    # s7, s10 missed it

    # ERP Module Presentation (past, 25 pts)
    ("s1",  "ERP Module Presentation", "graded", 23, "Confident delivery and accurate content."),
    ("s2",  "ERP Module Presentation", "graded", 20, "Content was strong but the presentation ran too short."),
    ("s5",  "ERP Module Presentation", "submitted", None, None),
    ("s6",  "ERP Module Presentation", "graded", 22, "Good choice of module (SD). Real-world examples were relevant."),
    ("s8",  "ERP Module Presentation", "submitted", None, None),
]

for sk, title, status, score, feedback in submissions_def:
    submitted_at = (TODAY - timedelta(days=random.randint(1, 4))).isoformat()
    cur.execute("""
        INSERT INTO student_submissions (submission_id, assignment_id, student_id,
                                         submitted_at, status, score, feedback, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, '')
    """, (uid(), A[title], U[sk], submitted_at, status, score, feedback))

print(f"Inserted {len(submissions_def)} submissions.")

# ── grades (assignment-only — no quizzes/exams) ───────────────────────────────
# Grades mirror graded submissions so the grades table stays consistent.
graded_submissions = [s for s in submissions_def if s[2] == "graded"]
for sk, title, _, score, _ in graded_submissions:
    # find which course this assignment belongs to
    course_key = next(c for c, t, *_ in assignments_def if t == title)
    cur.execute("""
        INSERT INTO grades (grade_id, student_id, course_id, assignment_id,
                            score, max_score, grade_type, graded_by, graded_at)
        VALUES (?, ?, ?, ?, ?, ?, 'assignment', ?, ?)
    """, (uid(), U[sk], C[course_key], A[title], score,
          next(pts for c, t, *rest, pts, p in assignments_def if t == title),
          next(U[p] for c, t, *rest, pts, p in assignments_def if t == title),
          (TODAY - timedelta(days=random.randint(1, 3))).isoformat()))

print(f"Inserted {len(graded_submissions)} grade records.")

# ── announcements ─────────────────────────────────────────────────────────────
announcements_def = [
    ("bis101", "Welcome to BIS101 — Spring 2026",
     "Welcome! Lectures are on Sunday and Tuesday, 10:00–11:30 AM in Hall 3. "
     "Office hours: Wednesday 1–3 PM. Course materials will be uploaded on the platform.",
     "normal", "prof1", -18),
    ("bis101", "Midterm Exam — 20 March 2026",
     "The midterm exam is scheduled for Thursday 20 March. It will cover Chapters 1–4 and the IS Case Study. "
     "Bring your student ID. No calculators allowed.",
     "high", "prof1", -3),
    ("bis201", "Database Lab Moved to Lab 5",
     "The Monday database lab session has been relocated to Lab 5 starting this week. "
     "Please update your schedules accordingly.",
     "normal", "prof1", -10),
    ("bis201", "SQL Assignment Tips",
     "A few students have asked about question 7 in the SQL assignment — remember to use a subquery, not a JOIN. "
     "Come to office hours if you need help before the deadline.",
     "normal", "prof1", -2),
    ("bis301", "Form Your Project Teams",
     "Please form teams of 3–4 students for the semester project. "
     "Submit your team list via the platform by end of this week.",
     "normal", "prof2", -7),
    ("bis302", "SAP System Access",
     "Your SAP login credentials have been sent to your @bis.edu email. "
     "Please verify your access before next Wednesday's lab. Contact IT support if you have issues.",
     "urgent", "prof3", -5),
    ("bis401", "Guest Lecture — Wednesday 18 March",
     "We have a guest speaker from Vodafone Egypt joining us next Wednesday to discuss real-world IT project management. "
     "Attendance is mandatory. Prepare two questions in advance.",
     "high", "prof3", -4),
    ("bis202", "Portfolio Deadline Reminder",
     "Reminder: the Personal Portfolio Website assignment is due in 8 days. "
     "Make sure your site is deployed (GitHub Pages is fine) and the link is submitted on the platform.",
     "normal", "prof2", -1),
]

for course_key, title, content, priority, prof_key, day_offset in announcements_def:
    cur.execute("""
        INSERT INTO announcements (announcement_id, course_id, title, content,
                                   priority, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (uid(), C[course_key], title, content, priority, U[prof_key],
          (TODAY + timedelta(days=day_offset)).isoformat()))

print(f"Inserted {len(announcements_def)} announcements.")

# ── Q&A forum ─────────────────────────────────────────────────────────────────
questions_def = [
    ("bis101", "What is the difference between MIS and DSS?",
     "I'm confused about the difference between Management Information Systems and Decision Support Systems. "
     "Could someone explain with real examples?",
     "s4", False, -9),
    ("bis101", "How do ERP systems help businesses?",
     "Can someone give a real-world example of how ERP systems improve business operations? "
     "Looking for something from an Egyptian company if possible.",
     "s6", True, -6),
    ("bis201", "INNER JOIN vs LEFT JOIN — when to use each?",
     "I keep mixing these up. Can someone explain when I should use INNER JOIN vs LEFT JOIN with a simple example?",
     "s2", True, -8),
    ("bis201", "Normalisation to 3NF confusion",
     "I understand 1NF and 2NF but I keep making mistakes at 3NF. "
     "What exactly is a transitive dependency and how do I spot it?",
     "s8", False, -5),
    ("bis301", "Use case vs activity diagram — which to use when?",
     "Both diagrams seem to describe processes. When should I choose a use case diagram vs an activity diagram?",
     "s1", False, -4),
    ("bis202", "Recommended resources for learning JavaScript quickly?",
     "I have HTML and CSS down. What is the fastest way to get comfortable with JavaScript? "
     "Any good free resources?",
     "s9", True, -7),
    ("bis401", "How do you handle scope creep in Agile projects?",
     "Our team project keeps expanding. What are some practical ways to manage scope creep "
     "when using an agile approach?",
     "s3", False, -3),
]

QID = {}   # index -> question_id
for i, (course_key, title, text, sk, answered, day_offset) in enumerate(questions_def):
    qid = uid()
    QID[i] = qid
    cur.execute("""
        INSERT INTO questions (question_id, course_id, title, question_text,
                               asked_by, created_at, is_answered, views)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (qid, C[course_key], title, text, U[sk],
          (TODAY + timedelta(days=day_offset)).isoformat(),
          1 if answered else 0, random.randint(8, 55)))

answers_def = [
    (1, "ERP systems like SAP integrate all business departments — finance, HR, supply chain, sales — into one platform. "
        "For example, when a customer places an order, inventory, invoicing, and logistics all update automatically. "
        "In Egypt, companies like El-Araby Group and Juhayna use SAP to manage their operations.",
        "s1", False),
    (2, "INNER JOIN returns only rows where there is a match in both tables. "
        "LEFT JOIN returns all rows from the left table; if there is no match in the right table, you get NULL. "
        "Use LEFT JOIN when you want to keep all records from one side even if the other side is empty — "
        "for example, listing all students even if they have no submissions yet.",
        "prof1", True),
    (5, "I'd recommend JavaScript.info for the theory — it's free and very thorough. "
        "For practice, try building small projects: a to-do list, a weather app using a public API, or a calculator. "
        "freeCodeCamp's JavaScript curriculum is also solid if you want structured exercises.",
        "s10", False),
]

for q_idx, text, sk, accepted in answers_def:
    cur.execute("""
        INSERT INTO question_answers (answer_id, question_id, answer_text,
                                      answered_by, created_at, is_accepted, upvotes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (uid(), QID[q_idx], text, U[sk],
          TODAY.isoformat(), 1 if accepted else 0, random.randint(1, 10)))

print(f"Inserted {len(questions_def)} questions and {len(answers_def)} answers.")

conn.commit()
conn.close()

print("\nDatabase populated successfully!")
print("=" * 55)
print("LOGIN CREDENTIALS")
print("=" * 55)
print("Professors (password: prof123):")
print("  ahmed.elsayed@bis.edu")
print("  mona.hassan@bis.edu")
print("  tarek.abdelfattah@bis.edu")
print("\nStudents (password: student123):")
students_list = [u for u in users if u[5] == "student"]
for _, first, last, email, _, _ in students_list:
    print(f"  {email}")
print("=" * 55)

# ── attendance summary for verification ──────────────────────────────────────
print("\nExpected attendance profiles (present+late = attends):")
print(f"{'Student':<20} {'Course':<10} {'Profile':<14} {'Effective %':>11}")
print("-" * 60)
for sk, profiles in sorted(student_profiles.items()):
    name = next(f"{u[1]} {u[2]}" for u in users if u[0] == sk)
    for ck, profile in profiles.items():
        w = PROFILES[profile]
        eff = (w[0] + w[2]) / sum(w) * 100
        print(f"  {name:<18} {ck:<10} {profile:<14} {eff:>9.0f}%")
