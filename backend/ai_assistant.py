"""
connects to openai and pulls data from the platform db to give personalized answers
also reads uploaded pdf/docx files if the professor uploaded any
"""
import os
import glob
import sqlite3
from dotenv import load_dotenv
from datetime import datetime, timedelta
import PyPDF2
import docx
import openai

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))


class AcademiaAIAssistant:
    def __init__(self, db_connection_string=None):
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.DOCUMENT_DIRECTORY = os.path.join(os.path.dirname(__file__), "academic_documents")
        self.UPLOADS_DIRECTORY = os.path.join(os.path.dirname(__file__), "uploads")
        self.MAIN_DB_PATH = db_connection_string or os.path.join(os.path.dirname(__file__), "academia_main.db")
        os.makedirs(self.DOCUMENT_DIRECTORY, exist_ok=True)
        self.document_cache = ""
        self.resource_metadata = []  # [{title, course_name, resource_id, file_type}]
        self.conversation_histories = {}  # user_id -> list of messages
        openai.api_key = self.OPENAI_API_KEY

    # ── sall helpers

    @staticmethod
    def _count_absences(records):
        """Return number of absent/unexcused records."""
        return sum(1 for r in records if r["status"] in ("absent", "unexcused"))

    @staticmethod
    def _readable_ext(path):
        """Return lowercased extension, or None if not a readable text format."""
        ext = os.path.splitext(path)[1].lower()
        return ext if ext in {'.pdf', '.docx', '.txt'} else None

    # ─────────────────────────────────────────────────────────────────────────

    def refresh_knowledge(self):
        """Loads documents from academic_documents and uploaded resources into memory."""
        print("Loading documents...")
        parts = []

        # scan academic_documents folder (manual uploads by admin)
        for path in glob.glob(os.path.join(self.DOCUMENT_DIRECTORY, '*.*')):
            if not self._readable_ext(path):
                continue
            try:
                content = self._read_file(path)
                if content:
                    parts.append(f"=== {os.path.basename(path)} ===\n{content}")
            except Exception as e:
                print(f"Error reading {path}: {e}")

        # scan uploads folder (professor-uploaded resources) and build resource metadata
        self.resource_metadata = []
        try:
            conn = sqlite3.connect(self.MAIN_DB_PATH)
            conn.row_factory = sqlite3.Row
            db_resources = conn.execute("""
                SELECT r.resource_id, r.title, r.file_path, r.file_type,
                       c.course_name
                FROM resources r JOIN courses c ON r.course_id = c.course_id
            """).fetchall()
            conn.close()

            # build a lookup: filename -> resource record
            resource_by_file = {r['file_path']: dict(r) for r in db_resources}

            for path in glob.glob(os.path.join(self.UPLOADS_DIRECTORY, '*.*')):
                fname = os.path.basename(path)
                rec = resource_by_file.get(fname)
                if not rec:
                    continue
                # add to metadata list regardless of file type
                self.resource_metadata.append({
                    "title": rec['title'],
                    "course_name": rec['course_name'],
                    "resource_id": rec['resource_id'],
                    "file_type": rec['file_type']
                })
                # only read text-extractable formats into document cache
                if self._readable_ext(path):
                    try:
                        content = self._read_file(path)
                        if content:
                            parts.append(f"=== RESOURCE: {rec['title']} ({rec['course_name']}) ===\n{content}")
                    except Exception as e:
                        print(f"Error reading uploaded resource {fname}: {e}")
        except Exception as e:
            print(f"Error loading uploaded resources: {e}")

        self.document_cache = "\n\n".join(parts)
        if self.document_cache:
            print(f"Loaded {len(parts)} document(s), {len(self.resource_metadata)} resource(s) indexed")
        else:
            print(f"No documents found. {len(self.resource_metadata)} resource(s) in metadata only")

    def _read_file(self, path):
        # handles pdf, docx, txt
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            with open(path, 'rb') as f:
                return "\n".join(p.extract_text() or "" for p in PyPDF2.PdfReader(f).pages)
        elif ext == ".docx":
            return "\n".join(p.text for p in docx.Document(path).paragraphs)
        elif ext == ".txt":
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        return ""

    def _get_platform_data(self, user_id):
        # pull relevant db data to build the AI's context string
        try:
            conn = sqlite3.connect(self.MAIN_DB_PATH)
            conn.row_factory = sqlite3.Row

            user = conn.execute(
                "SELECT first_name, last_name, role FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not user:
                conn.close()
                return ""

            role = user["role"]
            name = f"{user['first_name']} {user['last_name']}"
            lines = [f"User: {name} (role: {role})", f"Date: {datetime.now().strftime('%Y-%m-%d')}", ""]

            if role == "student":
                # Get enrolled courses
                courses = conn.execute("""
                    SELECT c.course_id, c.course_name, c.course_code,
                           u.first_name || ' ' || u.last_name AS instructor
                    FROM courses c
                    JOIN enrollments e ON c.course_id = e.course_id
                    JOIN users u ON c.instructor_id = u.user_id
                    WHERE e.student_id = ? AND e.status = 'active'
                """, (user_id,)).fetchall()

                lines.append(f"Enrolled in {len(courses)} courses:")
                for c in courses:
                    lines.append(f"  - {c['course_name']} ({c['course_code']}) with {c['instructor']}")

                # Attendance per course
                lines.append("\nAttendance:")
                for c in courses:
                    recs = conn.execute(
                        "SELECT status FROM attendance WHERE student_id=? AND course_id=?",
                        (user_id, c["course_id"])
                    ).fetchall()
                    if recs:
                        total = len(recs)
                        absent = self._count_absences(recs)
                        rate = (total - absent) / total * 100
                        lines.append(f"  {c['course_name']}: {rate:.0f}% ({total - absent}/{total} present)")

                # Assignments
                assignments = conn.execute("""
                    SELECT a.title, a.due_date, a.points, c.course_name,
                           COALESCE(s.status, 'not_submitted') AS sub_status, s.score
                    FROM assignments a
                    JOIN courses c ON a.course_id = c.course_id
                    JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ?
                    LEFT JOIN student_submissions s ON a.assignment_id = s.assignment_id AND s.student_id = ?
                    ORDER BY a.due_date
                """, (user_id, user_id)).fetchall()

                lines.append("\nAssignments:")
                for a in assignments:
                    grade = f" - Score: {a['score']}/{a['points']}" if a['score'] else ""
                    lines.append(f"  [{a['sub_status']}] {a['title']} ({a['course_name']}) due {a['due_date']}{grade}")

                # Grades — only assignment grades
                grades = conn.execute("""
                    SELECT g.score, g.max_score, g.grade_type, c.course_name
                    FROM grades g JOIN courses c ON g.course_id = c.course_id
                    WHERE g.student_id = ?
                      AND LOWER(g.grade_type) NOT IN ('exam', 'midterm', 'final', 'test')
                    ORDER BY g.graded_at DESC
                """, (user_id,)).fetchall()

                if grades:
                    lines.append("\nGrades:")
                    for g in grades:
                        lines.append(f"  {g['course_name']} - {g['grade_type']}: {g['score']}/{g['max_score']}")

                # Quizzes
                today_str = datetime.now().strftime("%Y-%m-%d")
                quizzes = conn.execute("""
                    SELECT q.quiz_id, q.title, q.quiz_date, q.total_points, c.course_name,
                           a.score, a.status as attempt_status
                    FROM quizzes q
                    JOIN courses c ON q.course_id = c.course_id
                    JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ?
                    LEFT JOIN quiz_attempts a ON q.quiz_id = a.quiz_id AND a.student_id = ?
                    ORDER BY q.quiz_date DESC
                """, (user_id, user_id)).fetchall()

                if quizzes:
                    lines.append("\nQuizzes:")
                    for qz in quizzes:
                        if qz['attempt_status'] in ('submitted',):
                            lines.append(f"  [scored] {qz['title']} ({qz['course_name']}) on {qz['quiz_date']}: {qz['score']}/{qz['total_points']}")
                        elif qz['attempt_status'] == 'graded_zero':
                            lines.append(f"  [missed/0] {qz['title']} ({qz['course_name']}) on {qz['quiz_date']}: 0/{qz['total_points']}")
                        elif qz['quiz_date'] == today_str:
                            lines.append(f"  [available TODAY] {qz['title']} ({qz['course_name']}) — {qz['total_points']} questions")
                        elif qz['quiz_date'] > today_str:
                            lines.append(f"  [upcoming] {qz['title']} ({qz['course_name']}) on {qz['quiz_date']} — {qz['total_points']} questions")

                # Recent announcements
                anns = conn.execute("""
                    SELECT a.title, a.content, c.course_name
                    FROM announcements a
                    JOIN courses c ON a.course_id = c.course_id
                    JOIN enrollments e ON a.course_id = e.course_id
                    WHERE e.student_id = ? AND e.status = 'active'
                    ORDER BY a.created_at DESC LIMIT 5
                """, (user_id,)).fetchall()

                if anns:
                    lines.append("\nRecent announcements:")
                    for a in anns:
                        lines.append(f"  [{a['course_name']}] {a['title']}: {a['content'][:150]}")

                # Q&A Forum activity
                my_questions = conn.execute("""
                    SELECT q.title, q.question_text, q.is_answered, c.course_name,
                           (SELECT COUNT(*) FROM question_answers qa WHERE qa.question_id = q.question_id) as answer_count
                    FROM questions q JOIN courses c ON q.course_id = c.course_id
                    WHERE q.asked_by = ?
                    ORDER BY q.created_at DESC LIMIT 5
                """, (user_id,)).fetchall()

                my_answers = conn.execute("""
                    SELECT qa.answer_text, q.title as question_title, c.course_name, qa.upvotes, qa.is_accepted
                    FROM question_answers qa
                    JOIN questions q ON qa.question_id = q.question_id
                    JOIN courses c ON q.course_id = c.course_id
                    WHERE qa.answered_by = ?
                    ORDER BY qa.created_at DESC LIMIT 5
                """, (user_id,)).fetchall()

                if my_questions or my_answers:
                    lines.append("\nQ&A Forum activity:")
                    if my_questions:
                        lines.append("  Questions asked:")
                        for q in my_questions:
                            answered = "answered" if q['is_answered'] else f"{q['answer_count']} response(s)"
                            lines.append(f"    [{q['course_name']}] \"{q['title']}\" — {answered}")
                    if my_answers:
                        lines.append("  Answers given:")
                        for a in my_answers:
                            accepted = " (accepted answer)" if a['is_accepted'] else ""
                            lines.append(f"    [{a['course_name']}] On \"{a['question_title']}\"{accepted} — {a['upvotes']} upvotes")

                # Course resources available
                res_list = conn.execute("""
                    SELECT r.title, r.file_type, r.description, c.course_name
                    FROM resources r JOIN courses c ON r.course_id = c.course_id
                    JOIN enrollments e ON c.course_id = e.course_id
                    WHERE e.student_id = ? AND e.status = 'active'
                    ORDER BY r.uploaded_at DESC LIMIT 10
                """, (user_id,)).fetchall()

                if res_list:
                    lines.append("\nAvailable course resources:")
                    for r in res_list:
                        lines.append(f"  [{r['course_name']}] \"{r['title']}\" ({r['file_type'].upper()}){' — ' + r['description'][:80] if r['description'] else ''}")

            elif role == "professor":
                courses = conn.execute("""
                    SELECT c.course_id, c.course_name, c.course_code,
                           (SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.course_id AND e.status='active') AS enrolled
                    FROM courses c WHERE c.instructor_id = ?
                """, (user_id,)).fetchall()

                lines.append(f"Teaching {len(courses)} courses:")
                for c in courses:
                    lines.append(f"\n  {c['course_name']} ({c['course_code']}) - {c['enrolled']} students")

                    # Student attendance summary
                    students = conn.execute("""
                        SELECT u.first_name || ' ' || u.last_name AS name, u.user_id
                        FROM users u JOIN enrollments e ON u.user_id = e.student_id
                        WHERE e.course_id=? AND e.status='active'
                    """, (c['course_id'],)).fetchall()

                    for s in students:
                        recs = conn.execute(
                            "SELECT status FROM attendance WHERE student_id=? AND course_id=?",
                            (s['user_id'], c['course_id'])
                        ).fetchall()
                        if recs:
                            total = len(recs)
                            absent = self._count_absences(recs)
                            rate = (total - absent) / total * 100
                            flag = " (LOW)" if rate < 75 else ""
                            lines.append(f"    {s['name']}: {rate:.0f}% attendance{flag}")

                    # Assignment submission status
                    asgns = conn.execute("""
                        SELECT a.title, a.due_date, a.points,
                               (SELECT COUNT(*) FROM student_submissions s WHERE s.assignment_id = a.assignment_id) as submitted_count
                        FROM assignments a WHERE a.course_id = ?
                        ORDER BY a.due_date
                    """, (c['course_id'],)).fetchall()
                    if asgns:
                        for a in asgns:
                            lines.append(f"    Assignment \"{a['title']}\" due {a['due_date']}: {a['submitted_count']}/{c['enrolled']} submitted")

                    # Quiz results
                    quizzes = conn.execute("""
                        SELECT q.title, q.quiz_date, q.total_points,
                               (SELECT COUNT(*) FROM quiz_attempts qa WHERE qa.quiz_id = q.quiz_id AND qa.status = 'submitted') as submissions,
                               (SELECT ROUND(AVG(qa.score),1) FROM quiz_attempts qa WHERE qa.quiz_id = q.quiz_id AND qa.status = 'submitted') as avg_score
                        FROM quizzes q WHERE q.course_id = ? AND q.created_by = ?
                        ORDER BY q.quiz_date DESC
                    """, (c['course_id'], user_id)).fetchall()
                    if quizzes:
                        lines.append(f"  Quizzes:")
                        for qz in quizzes:
                            avg = f", avg score {qz['avg_score']}/{qz['total_points']}" if qz['avg_score'] else ""
                            lines.append(f"    \"{qz['title']}\" on {qz['quiz_date']}: {qz['submissions']} submitted{avg}")

                    # Recent announcements for this course
                    anns = conn.execute("""
                        SELECT title, content, created_at FROM announcements
                        WHERE course_id = ? ORDER BY created_at DESC LIMIT 3
                    """, (c['course_id'],)).fetchall()
                    if anns:
                        lines.append(f"  Recent announcements:")
                        for a in anns:
                            lines.append(f"    \"{a['title']}\": {a['content'][:100]}")

                    # Course resources
                    resources = conn.execute("""
                        SELECT title, file_type, downloads FROM resources
                        WHERE course_id = ? ORDER BY uploaded_at DESC LIMIT 5
                    """, (c['course_id'],)).fetchall()
                    if resources:
                        lines.append(f"  Resources uploaded: {', '.join(r['title'] + ' (' + r['file_type'].upper() + ')' for r in resources)}")

                    # Q&A Forum for this course
                    forum_qs = conn.execute("""
                        SELECT q.title, q.is_answered, q.views,
                               (SELECT COUNT(*) FROM question_answers qa WHERE qa.question_id = q.question_id) as answer_count,
                               u.first_name || ' ' || u.last_name as asked_by_name
                        FROM questions q JOIN users u ON q.asked_by = u.user_id
                        WHERE q.course_id = ?
                        ORDER BY q.created_at DESC LIMIT 5
                    """, (c['course_id'],)).fetchall()
                    if forum_qs:
                        unanswered = sum(1 for q in forum_qs if not q['is_answered'])
                        lines.append(f"  Q&A Forum ({unanswered} unanswered):")
                        for q in forum_qs:
                            status = "answered" if q['is_answered'] else f"{q['answer_count']} answer(s)"
                            lines.append(f"    \"{q['title']}\" by {q['asked_by_name']} — {status}, {q['views']} views")

            conn.close()
            return "\n".join(lines)

        except Exception as e:
            print(f"Error getting platform data: {e}")
            return ""

    def ask(self, question, student_id=None, course_id=None, lang="en"):
        """Main chat function - combines documents + platform data to answer questions.
        Returns a tuple (answer, suggested_resources) where suggested_resources is a list
        of resource dicts whose titles appear in the question or answer."""
        user_id = student_id

        # this took a while to get right - the context has to come before the user question
        history = self.conversation_histories.get(user_id, [])

        # Build context
        context_parts = []
        if self.document_cache:
            context_parts.append("Course Materials:\n" + self.document_cache[:6000])
        platform_data = self._get_platform_data(user_id) if user_id else ""
        if platform_data:
            context_parts.append(platform_data)
        # include resource listing so AI knows what's available
        if self.resource_metadata:
            res_lines = ["Available Course Resources (you can recommend these by name):"]
            for r in self.resource_metadata:
                res_lines.append(f"  - \"{r['title']}\" ({r['file_type'].upper()}) in {r['course_name']} [id:{r['resource_id']}]")
            context_parts.append("\n".join(res_lines))
        context = "\n\n".join(context_parts) or "No data available."

        lang_instruction = "مهم جداً: يجب أن تكتب ردك كاملاً باللغة العربية الفصحى. جميع الجمل يجب أن تكون بالعربية.\n\n" if lang == "ar" else ""
        system_prompt = lang_instruction + """You are an AI assistant for Academia BIS, a university academic management platform.
Answer questions strictly using the provided platform data and course materials.
Be helpful, warm, and concise. Use actual numbers from the data — do not invent or assume anything.

This platform contains ALL of these features — you are fully aware of each:
- Courses & enrolments
- Assignments (with submissions, grading, auto-zero for overdue)
- Attendance tracking (present / late / absent / unexcused)
- Quizzes (MCQ, auto-graded, accessible only on quiz date, auto-zero if missed)
- Q&A Forum (students ask questions, anyone can answer, answers can be upvoted/accepted)
- Announcements (posted by professors per course)
- Course Resources (files uploaded by professors: PDFs, slides, etc.)
- Notifications (system alerts for the user)
- Student grades (linked to assignments and quizzes)

This platform does NOT have exams, midterms, or finals.
Reference any feature above when the user's data includes relevant records.
Do not invent data — if something is not in the context, say you don't have that information.

When relevant, recommend specific course resources by name from the Available Course Resources list.
For professors: proactively mention unanswered forum questions, low attendance students, or upcoming quiz results.
For students: mention upcoming quizzes, unanswered forum questions, and available resources when relevant.
If you don't know something, say so clearly.
Do not use any markdown formatting in your responses — no asterisks, no bold, no bullet symbols, no headers. Write in plain text only."""

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history[-12:]:
            messages.append(msg)
        messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"})

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4.1-mini",
                messages=messages,
                max_tokens=800,
                temperature=0.3
            )
            answer = response.choices[0].message.content.strip()

            # Save to history
            if user_id:
                if user_id not in self.conversation_histories:
                    self.conversation_histories[user_id] = []
                self.conversation_histories[user_id].append({"role": "user", "content": question})
                self.conversation_histories[user_id].append({"role": "assistant", "content": answer})
                # Keep only last 16 messages
                if len(self.conversation_histories[user_id]) > 16:
                    self.conversation_histories[user_id] = self.conversation_histories[user_id][-16:]

            # find resources mentioned in the question or answer
            combined_text = (question + " " + answer).lower()
            suggested = [
                r for r in self.resource_metadata
                if r['title'].lower() in combined_text
            ]

            return answer, suggested

        except Exception as e:
            return f"Sorry, I ran into an error: {str(e)}", []

    def clear_history(self, user_id):
        self.conversation_histories.pop(user_id, None)

    def analyze_attendance_risk(self, student_id):
        """Check if a student's attendance is at risk."""
        try:
            conn = sqlite3.connect(self.MAIN_DB_PATH)
            conn.row_factory = sqlite3.Row
            records = conn.execute("""
                SELECT a.status, c.course_name, c.course_id
                FROM attendance a JOIN courses c ON a.course_id = c.course_id
                WHERE a.student_id = ?
            """, (student_id,)).fetchall()
            conn.close()

            if not records:
                return {"risk_level": "unknown", "attendance_rate": 0, "absences": 0,
                        "total_classes": 0, "recommendation": "No attendance records yet.",
                        "courses_at_risk": []}

            total = len(records)
            absences = self._count_absences(records)
            rate = (total - absences) / total

            # 75% is the official university threshold for attendance
            # Check per-course
            by_course = {}
            for r in records:
                key = (r["course_id"], r["course_name"])
                by_course.setdefault(key, {"total": 0, "absences": 0})
                by_course[key]["total"] += 1
                if r["status"] in ("absent", "unexcused"):
                    by_course[key]["absences"] += 1

            courses_at_risk = []
            for (cid, cname), d in by_course.items():
                cr = (d["total"] - d["absences"]) / d["total"]
                if cr < 0.75:
                    courses_at_risk.append({
                        "course_id": cid, "course_name": cname,
                        "attendance_rate": round(cr, 3),
                        "absences": d["absences"], "total_classes": d["total"]
                    })

            if rate >= 0.90:
                risk_level = "low"
                recommendation = "Good attendance! Keep it up."
            elif rate >= 0.75:
                risk_level = "medium"
                recommendation = f"Attendance is {rate*100:.0f}%. Try not to miss more classes."
            else:
                risk_level = "high"
                recommendation = f"Attendance is {rate*100:.0f}%, below 75%. You need to attend more classes."

            return {"risk_level": risk_level, "attendance_rate": round(rate, 3),
                    "absences": absences, "total_classes": total,
                    "recommendation": recommendation, "courses_at_risk": courses_at_risk}

        except Exception as e:
            return {"risk_level": "error", "attendance_rate": 0,
                    "absences": 0, "total_classes": 0,
                    "recommendation": str(e), "courses_at_risk": []}

    def optimize_workload(self, student_id):
        """Get upcoming assignments and quizzes sorted by priority — quizzes always top."""
        try:
            conn = sqlite3.connect(self.MAIN_DB_PATH)
            conn.row_factory = sqlite3.Row
            today_str = datetime.now().strftime("%Y-%m-%d")

            assignments = conn.execute("""
                SELECT a.assignment_id, a.title, a.due_date, a.points, c.course_name,
                       COALESCE(s.status, 'not_submitted') AS sub_status
                FROM assignments a
                JOIN courses c ON a.course_id = c.course_id
                JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ?
                LEFT JOIN student_submissions s ON a.assignment_id = s.assignment_id AND s.student_id = ?
                WHERE (s.status IS NULL OR s.status = 'not_submitted')
                ORDER BY a.due_date
            """, (student_id, student_id)).fetchall()

            # Pending quizzes: today (not yet attempted) and upcoming
            quizzes = conn.execute("""
                SELECT q.quiz_id, q.title, q.quiz_date, q.total_points, c.course_name
                FROM quizzes q
                JOIN courses c ON q.course_id = c.course_id
                JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ? AND e.status = 'active'
                LEFT JOIN quiz_attempts a ON q.quiz_id = a.quiz_id AND a.student_id = ?
                WHERE a.attempt_id IS NULL AND q.quiz_date >= ?
                ORDER BY q.quiz_date
            """, (student_id, student_id, today_str)).fetchall()

            conn.close()

            schedule = []

            # Quizzes first — always highest priority
            for qz in quizzes:
                days = (datetime.strptime(qz["quiz_date"], "%Y-%m-%d") - datetime.now()).days
                if days == 0:
                    priority, suggestion = "critical", "Quiz is TODAY — must take it or get 0!"
                elif days <= 3:
                    priority, suggestion = "urgent", "Quiz coming up very soon"
                elif days <= 7:
                    priority, suggestion = "high", "Quiz this week — prepare now"
                else:
                    priority, suggestion = "medium", "Upcoming quiz — start reviewing"

                schedule.append({
                    "quiz_id": qz["quiz_id"], "title": qz["title"],
                    "course": qz["course_name"], "due_date": qz["quiz_date"],
                    "days_until_due": days, "points": qz["total_points"],
                    "priority": priority, "suggestion": suggestion,
                    "type": "quiz"
                })

            # Assignments after
            for a in assignments:
                days = (datetime.strptime(a["due_date"], "%Y-%m-%d") - datetime.now()).days
                if days < 0:
                    priority, suggestion = "urgent", "Overdue! Submit now"
                elif days == 0:
                    priority, suggestion = "urgent", "Due today!"
                elif days <= 3:
                    priority, suggestion = "high", "Due very soon"
                elif days <= 7:
                    priority, suggestion = "medium", "Due this week"
                else:
                    priority, suggestion = "low", "Plan ahead"

                schedule.append({
                    "assignment_id": a["assignment_id"], "title": a["title"],
                    "course": a["course_name"], "due_date": a["due_date"],
                    "days_until_due": days, "points": a["points"],
                    "priority": priority, "suggestion": suggestion,
                    "type": "assignment"
                })

            if not schedule:
                return {"schedule": [],
                        "workload_analysis": {"status": "light", "total_assignments": 0, "urgent_count": 0},
                        "recommendations": ["No pending assignments or quizzes!"]}

            total = len(schedule)
            urgent = sum(1 for s in schedule if s["priority"] in ("urgent", "critical"))
            quiz_count = sum(1 for s in schedule if s.get("type") == "quiz")

            recs = [f"{total} pending items ({quiz_count} quiz(zes))" + (f", {urgent} urgent!" if urgent else ".")]

            return {"schedule": schedule,
                    "workload_analysis": {"status": "heavy" if total > 5 else "moderate" if total > 2 else "light",
                                          "total_assignments": total, "urgent_count": urgent},
                    "recommendations": recs}

        except Exception as e:
            return {"schedule": [],
                    "workload_analysis": {"status": "error", "total_assignments": 0, "urgent_count": 0},
                    "recommendations": [str(e)]}

    def generate_student_report(self, student_id, lang="en"):
        """AI-written conversational report for a student — advisor tone, sections, motivation."""
        snapshot = self._get_platform_data(student_id)
        workload = self.optimize_workload(student_id)

        workload_lines = []
        if workload["schedule"]:
            workload_lines.append("Pending tasks ranked by urgency (quizzes listed first — always top priority):")
            for item in workload["schedule"][:10]:
                days_label = "TODAY — MUST TAKE NOW" if (item.get("type") == "quiz" and item["days_until_due"] == 0) \
                    else ("Overdue" if item["days_until_due"] < 0 else ("Due today" if item["days_until_due"] == 0 else f"Due in {item['days_until_due']} days"))
                item_type = "QUIZ" if item.get("type") == "quiz" else "Assignment"
                workload_lines.append(
                    f"  - [{item_type}] {item['title']} ({item['course']}) — {days_label}, {item['points']} pts [{item['priority']} priority] — {item['suggestion']}"
                )
        else:
            workload_lines.append("No pending assignments or quizzes.")

        # Explicitly build quiz context so GPT sees it front-and-centre
        quiz_lines = []
        try:
            conn = sqlite3.connect(self.MAIN_DB_PATH)
            conn.row_factory = sqlite3.Row
            today_str = datetime.now().strftime("%Y-%m-%d")
            quizzes = conn.execute("""
                SELECT q.title, q.quiz_date, q.total_points, c.course_name,
                       a.score, a.status as attempt_status
                FROM quizzes q
                JOIN courses c ON q.course_id = c.course_id
                JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ? AND e.status = 'active'
                LEFT JOIN quiz_attempts a ON q.quiz_id = a.quiz_id AND a.student_id = ?
                ORDER BY q.quiz_date DESC
            """, (student_id, student_id)).fetchall()
            conn.close()

            if quizzes:
                quiz_lines.append("\nQuiz status:")
                for qz in quizzes:
                    if qz['attempt_status'] == 'submitted':
                        quiz_lines.append(f"  [SCORED] \"{qz['title']}\" ({qz['course_name']}) on {qz['quiz_date']}: scored {qz['score']}/{qz['total_points']}")
                    elif qz['attempt_status'] == 'graded_zero':
                        quiz_lines.append(f"  [MISSED — 0/{qz['total_points']}] \"{qz['title']}\" ({qz['course_name']}) on {qz['quiz_date']} — was not attempted")
                    elif qz['quiz_date'] == today_str:
                        quiz_lines.append(f"  [AVAILABLE TODAY] \"{qz['title']}\" ({qz['course_name']}) — {qz['total_points']} pts — student has NOT taken it yet")
                    elif qz['quiz_date'] > today_str:
                        quiz_lines.append(f"  [UPCOMING] \"{qz['title']}\" ({qz['course_name']}) on {qz['quiz_date']} — {qz['total_points']} pts")
            else:
                quiz_lines.append("\nNo quizzes scheduled yet.")
        except Exception:
            pass

        workload_context = "\n".join(workload_lines) + "\n".join(quiz_lines)

        lang_instruction = """مهم جداً: يجب أن تكتب ردك كاملاً باللغة العربية الفصحى. جميع الجمل يجب أن تكون بالعربية.
استخدم هذه الأسماء للأقسام بالضبط (بنفس التنسيق **الاسم**):
- **نظرة عامة** (Overview)
- **ما تقوم به بشكل جيد** (What You're Doing Well)
- **ما يجب التركيز عليه** (Where to Focus)
- **مهامك ذات الأولوية هذا الأسبوع** (Your Priority Tasks This Week)

""" if lang == "ar" else ""
        system_prompt = lang_instruction + """You are a caring, experienced academic advisor having a one-on-one conversation with a university student.
Write a personal, warm academic report — NOT a bullet list, NOT a formal document. Write in natural flowing paragraphs as if you're talking directly to the student by name.

Structure your response with exactly these four labeled sections, each header on its own line formatted as **Section Name**:

**Overview**
A 2-3 sentence honest but warm summary of where the student stands right now — overall attendance, submission record, general academic health.

**What You're Doing Well**
Highlight real strengths from the data — good attendance in specific courses, submitted assignments, solid grades. Be specific and genuine, not generic praise.

**Where to Focus**
Identify 1-3 concrete areas that need work — low attendance in a named course, an overdue or missing assignment, a low grade. Be direct but supportive, not critical.

**Your Priority Tasks This Week**
Using the pending assignments AND quiz data, tell the student exactly what to tackle first and why. Rank by urgency (days left) and point value. If a quiz is available today or coming up soon, make it the top priority — quizzes are locked to their date and cannot be made up. Write it as personal advice — "I'd start with X because it's due in 2 days and worth 25 points" — not a flat list.

After the four sections, close with one short motivational sentence (no header). Make it genuine and specific to their situation — not a generic "keep it up!".

Rules:
- Use the student's first name throughout
- Cite actual numbers from the data (e.g. "your attendance in BIS201 is 73%")
- Never mention exams or midterms — the platform has quizzes which you CAN reference if quiz data is present
- If a quiz is upcoming or was missed, mention it in the priority or focus section
- If the student has unanswered forum questions or hasn't engaged with available resources, mention that
- If there are unread notifications, flag any that seem important
- Keep the full report to 380-460 words
- Write as if you genuinely care about this student's success"""

        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Write my academic report:\n\n{snapshot}\n\n{workload_context}"}
                ],
                max_tokens=750,
                temperature=0.4
            )
            return {
                "narrative": resp.choices[0].message.content.strip(),
                "workload": workload,
                "raw_snapshot": snapshot
            }
        except Exception as e:
            return {"narrative": f"Could not generate report: {e}", "workload": workload, "raw_snapshot": snapshot}

    def generate_professor_insights(self, professor_id, lang="en"):
        """AI briefing for a professor — actionable, specific, class-builder mindset."""
        snapshot = self._get_platform_data(professor_id)

        lang_instruction = """مهم جداً: يجب أن تكتب ردك كاملاً باللغة العربية الفصحى. جميع الجمل يجب أن تكون بالعربية.
استخدم هذه الأسماء للأقسام بالضبط (بنفس التنسيق **الاسم**):
- **ملخص صحة الفصل** (Class Health Summary)
- **الطلاب الذين يحتاجون إلى اهتمام** (Students Who Need Attention)
- **ما يسير بشكل جيد** (What's Going Well)
- **الإجراءات الموصى بها هذا الأسبوع** (Recommended Actions This Week)

""" if lang == "ar" else ""
        system_prompt = lang_instruction + """You are a dependable academic intelligence assistant briefing a university professor before their week.
Write in a professional but warm tone — like a trusted colleague giving a smart, actionable briefing. Use natural flowing paragraphs, not bullet points.

Structure your response with exactly these four labeled sections, each header on its own line formatted as **Section Name**:

**Class Health Summary**
A 2-3 sentence honest overview of how the professor's classes are performing — overall attendance trends, submission rates, general engagement. Use actual numbers.

**Students Who Need Attention**
Name specific students whose attendance is below 75% or who have missing/overdue submissions. For each, explain the risk and suggest a concrete action (e.g. "A quick message to Mohamed this week could make a difference — he's missed 4 of 15 classes in BIS201"). If no students are at risk, say so clearly and honestly.

**What's Going Well**
Highlight strong performers, courses with high attendance, or good submission rates. Keep it brief but genuine — professors need to know what's working too.

**Recommended Actions This Week**
Give 2-3 specific, actionable steps the professor should take this week. Be concrete and realistic — name courses and students where relevant. Mention unanswered forum questions, upcoming quizzes, or missing resources if they appear in the data.

Rules:
- Use actual numbers from the data
- Be specific about student names and courses
- Never mention exams or midterms — quizzes exist on the platform and you can reference them
- Mention Q&A forum questions that need answers and available/missing resources when relevant
- Keep the full report to 380-460 words
- Write as someone who understands that early professor intervention is the most powerful tool for student success"""

        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Generate my class briefing:\n\n{snapshot}"}
                ],
                max_tokens=750,
                temperature=0.55
            )
            return {"narrative": resp.choices[0].message.content.strip(), "raw_snapshot": snapshot}
        except Exception as e:
            return {"narrative": f"Could not generate insights: {e}", "raw_snapshot": snapshot}
