from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import sqlite3
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import bcrypt
import uuid
import os
import csv
import io
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'academia-secret-key-2026')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'academia-jwt-secret-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=7)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
AVATAR_FOLDER = os.path.join(UPLOAD_FOLDER, 'avatars')
os.makedirs(AVATAR_FOLDER, exist_ok=True)
ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

CORS(app)
jwt = JWTManager(app)

DB_PATH = os.environ.get('DB_PATH', os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'database', 'academia_main.db')))
print("DB:", DB_PATH)

# load AI lazily so startup doesn't crash if key is missing
ai_assistant = None

_ai_error = None

def get_ai():
    global ai_assistant, _ai_error
    if ai_assistant is None:
        try:
            from ai_assistant import AcademiaAIAssistant
            ai_assistant = AcademiaAIAssistant(db_connection_string=DB_PATH)
            ai_assistant.refresh_knowledge()
            _ai_error = None
        except Exception as e:
            _ai_error = str(e)
            print("AI failed to load:", e)
    return ai_assistant

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _post_notification(conn, course_id, title, content, created_by, recipient_id=None):
    conn.execute("""
        INSERT INTO announcements
            (announcement_id, course_id, title, content, created_by, priority, created_at, recipient_id, is_notification)
        VALUES (?, ?, ?, ?, ?, 'normal', ?, ?, 1)
    """, (str(uuid.uuid4()), course_id, title, content, created_by,
          datetime.now().isoformat(), recipient_id))


@app.route('/api/auth/register', methods=['POST'])
def register():
    # Accept both multipart (with avatar) and JSON
    if request.content_type and 'multipart' in request.content_type:
        data = request.form
        avatar_file = request.files.get('avatar')
    else:
        data = request.json or {}
        avatar_file = None

    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "email and password are required"}), 400

    uid = str(uuid.uuid4())
    pw_hash = bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt()).decode()

    profile_picture = None
    if avatar_file and avatar_file.filename:
        ext = os.path.splitext(secure_filename(avatar_file.filename))[1].lower()
        if ext in ALLOWED_IMAGE_EXTS:
            filename = f"{uid}{ext}"
            avatar_file.save(os.path.join(AVATAR_FOLDER, filename))
            profile_picture = filename

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users (user_id, email, password_hash, first_name, last_name, role, phone, profile_picture, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (uid, data['email'].lower(), pw_hash,
              data.get('first_name', ''), data.get('last_name', ''),
              data.get('role', 'student'), data.get('phone', ''),
              profile_picture, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({"message": "Registered successfully"}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Email already in use"}), 409

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Email and password required"}), 400

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (data['email'].lower(),)
    ).fetchone()
    conn.close()

    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    stored = user['password_hash']
    if isinstance(stored, str):
        stored = stored.encode()
    if not bcrypt.checkpw(data['password'].encode(), stored):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(identity=user['user_id'])
    print("login ok:", user['email'])
    return jsonify({
        "access_token": token,
        "user": {
            "user_id": user['user_id'],
            "email": user['email'],
            "role": user['role'],
            "first_name": user['first_name'],
            "last_name": user['last_name'],
            "profile_picture": user['profile_picture'] if 'profile_picture' in user.keys() else None
        }
    }), 200

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_me():
    uid = get_jwt_identity()
    conn = get_db()
    user = conn.execute(
        "SELECT user_id, email, role, first_name, last_name, profile_picture FROM users WHERE user_id = ?", (uid,)
    ).fetchone()
    conn.close()
    if user:
        return jsonify(dict(user)), 200
    return jsonify({"error": "Not found"}), 404

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    uid = get_jwt_identity()
    conn = get_db()

    user = conn.execute(
        "SELECT user_id, first_name, last_name, email, phone, role, created_at, profile_picture FROM users WHERE user_id = ?", (uid,)
    ).fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    role = user['role']
    if role == 'professor':
        teaching_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM courses WHERE instructor_id = ?", (uid,)
        ).fetchone()['cnt']
        extra = {"courses_teaching_count": teaching_count}
    else:
        enrolled_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM enrollments WHERE student_id = ? AND status = 'active'", (uid,)
        ).fetchone()['cnt']
        extra = {"enrolled_courses_count": enrolled_count}

    conn.close()
    return jsonify({
        "first_name": user['first_name'],
        "last_name": user['last_name'],
        "email": user['email'],
        "phone": user['phone'] or "Not provided",
        "role": role,
        "created_at": user['created_at'],
        "profile_picture": user['profile_picture'],
        **extra
    }), 200

@app.route('/api/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    uid = get_jwt_identity()
    data = request.json or {}
    conn = get_db()
    conn.execute(
        "UPDATE users SET first_name=?, last_name=?, phone=? WHERE user_id=?",
        (data.get('first_name', ''), data.get('last_name', ''), data.get('phone', ''), uid)
    )
    conn.commit()
    user = conn.execute(
        "SELECT user_id, email, role, first_name, last_name, profile_picture FROM users WHERE user_id=?", (uid,)
    ).fetchone()
    conn.close()
    return jsonify({"message": "Profile updated", "user": dict(user)}), 200

@app.route('/api/users/avatar', methods=['POST'])
@jwt_required()
def upload_avatar():
    uid = get_jwt_identity()
    if 'avatar' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['avatar']
    if not file or not file.filename:
        return jsonify({"error": "No file selected"}), 400
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": "Invalid file type. Use jpg, png, gif, or webp."}), 400
    filename = f"{uid}{ext}"
    file.save(os.path.join(AVATAR_FOLDER, filename))
    conn = get_db()
    conn.execute("UPDATE users SET profile_picture=? WHERE user_id=?", (filename, uid))
    conn.commit()
    conn.close()
    return jsonify({"profile_picture": filename}), 200

@app.route('/api/uploads/avatars/<path:filename>', methods=['GET'])
def serve_avatar(filename):
    return send_from_directory(AVATAR_FOLDER, filename)

# --- courses ---

@app.route('/api/courses', methods=['GET'])
@jwt_required()
def get_courses():
    uid = get_jwt_identity()
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()

    if user and user['role'] == 'professor':
        rows = conn.execute("""
            SELECT c.*, u.first_name || ' ' || u.last_name as instructor_name
            FROM courses c JOIN users u ON c.instructor_id = u.user_id
            WHERE c.instructor_id = ? ORDER BY c.created_at DESC
        """, (uid,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT c.*, u.first_name || ' ' || u.last_name as instructor_name
            FROM courses c JOIN enrollments e ON c.course_id = e.course_id
            JOIN users u ON c.instructor_id = u.user_id
            WHERE e.student_id = ? AND e.status = 'active' ORDER BY c.created_at DESC
        """, (uid,)).fetchall()

    conn.close()
    return jsonify({"courses": [dict(r) for r in rows]}), 200

@app.route('/api/courses/all', methods=['GET'])
@jwt_required()
def get_all_courses():
    uid = get_jwt_identity()
    conn = get_db()
    rows = conn.execute("""
        SELECT c.*, u.first_name || ' ' || u.last_name as instructor_name,
        CASE WHEN e.student_id IS NOT NULL THEN 1 ELSE 0 END as is_enrolled
        FROM courses c JOIN users u ON c.instructor_id = u.user_id
        LEFT JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ?
        ORDER BY c.created_at DESC
    """, (uid,)).fetchall()
    conn.close()
    return jsonify({"courses": [dict(r) for r in rows]}), 200

@app.route('/api/courses', methods=['POST'])
@jwt_required()
def create_course():
    data = request.json
    if not data or not data.get('course_code') or not data.get('course_name'):
        return jsonify({"error": "course_code and course_name required"}), 400

    # cid = data['course_code'].lower() + '_' + str(int(data.get('year', 2026)))  # tried this first but duplicate codes broke everything
    cid = str(uuid.uuid4())
    conn = get_db()
    conn.execute("""
        INSERT INTO courses (course_id, course_code, course_name, description, instructor_id, semester, year, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (cid, data['course_code'], data['course_name'],
          data.get('description', ''), get_jwt_identity(),
          data.get('semester', 'Spring'), int(data.get('year', 2026)),
          datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"message": "Course created", "course_id": cid}), 201

@app.route('/api/courses/<course_id>', methods=['DELETE'])
@jwt_required()
def delete_course(course_id):
    uid = get_jwt_identity()
    conn = get_db()
    course = conn.execute("SELECT instructor_id FROM courses WHERE course_id=?", (course_id,)).fetchone()
    if not course:
        conn.close(); return jsonify({"error": "Course not found"}), 404
    if course['instructor_id'] != uid:
        conn.close(); return jsonify({"error": "Not authorized"}), 403
    conn.execute("DELETE FROM enrollments WHERE course_id=?", (course_id,))
    conn.execute("DELETE FROM announcements WHERE course_id=?", (course_id,))
    conn.execute("DELETE FROM courses WHERE course_id=?", (course_id,))
    conn.commit(); conn.close()
    return jsonify({"message": "Course deleted"}), 200

@app.route('/api/courses/<course_id>', methods=['PUT'])
@jwt_required()
def update_course(course_id):
    uid = get_jwt_identity()
    data = request.json
    conn = get_db()
    course = conn.execute("SELECT instructor_id FROM courses WHERE course_id=?", (course_id,)).fetchone()
    if not course:
        conn.close(); return jsonify({"error": "Course not found"}), 404
    if course['instructor_id'] != uid:
        conn.close(); return jsonify({"error": "Not authorized"}), 403
    conn.execute("""UPDATE courses SET course_name=?, course_code=?, description=? WHERE course_id=?""",
                 (data.get('course_name'), data.get('course_code'), data.get('description', ''), course_id))
    conn.commit(); conn.close()
    return jsonify({"message": "Course updated"}), 200

@app.route('/api/courses/<course_id>/enroll', methods=['POST'])
@jwt_required()
def enroll(course_id):
    uid = get_jwt_identity()
    conn = get_db()

    existing = conn.execute(
        "SELECT enrollment_id FROM enrollments WHERE student_id = ? AND course_id = ?",
        (uid, course_id)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({"error": "Already enrolled"}), 409

    conn.execute("""
        INSERT INTO enrollments (enrollment_id, student_id, course_id, status, enrolled_at)
        VALUES (?, ?, ?, 'active', ?)
    """, (str(uuid.uuid4()), uid, course_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    # TODO: send e mail notfication here
    return jsonify({"message": "Enrolled!"}), 201

# assignments / submissions

def _auto_close_overdue(conn, student_id):
    """For every overdue assignment the student never submitted, insert a graded/0 record."""
    today = datetime.now().strftime("%Y-%m-%d")
    overdue = conn.execute("""
        SELECT a.assignment_id, a.points
        FROM assignments a
        JOIN enrollments e ON a.course_id = e.course_id AND e.student_id = ?
        LEFT JOIN student_submissions s ON a.assignment_id = s.assignment_id AND s.student_id = ?
        WHERE a.due_date < ? AND e.status = 'active'
          AND s.submission_id IS NULL
    """, (student_id, student_id, today)).fetchall()

    for a in overdue:
        conn.execute("""
            INSERT INTO student_submissions
                (submission_id, assignment_id, student_id, submitted_at, status, score, feedback, file_path)
            VALUES (?, ?, ?, ?, 'graded', 0, 'Not submitted by deadline — automatically graded 0.', '')
        """, (str(uuid.uuid4()), a['assignment_id'], student_id, today))
    if overdue:
        conn.commit()


@app.route('/api/assignments', methods=['GET'])
@jwt_required()
def get_assignments():
    uid = get_jwt_identity()
    course_id = request.args.get('course_id')
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()

    if user and user['role'] == 'student':
        _auto_close_overdue(conn, uid)

    if course_id:
        rows = conn.execute("""
            SELECT a.*, c.course_name,
            CASE WHEN s.submission_id IS NOT NULL THEN s.status ELSE 'not_submitted' END as submission_status,
            s.score, s.submission_id, s.feedback
            FROM assignments a JOIN courses c ON a.course_id = c.course_id
            LEFT JOIN student_submissions s ON a.assignment_id = s.assignment_id AND s.student_id = ?
            WHERE a.course_id = ? ORDER BY a.due_date
        """, (uid, course_id)).fetchall()
    elif user and user['role'] == 'professor':
        rows = conn.execute("""
            SELECT a.*, c.course_name,
            (SELECT COUNT(*) FROM student_submissions s WHERE s.assignment_id = a.assignment_id) as submission_count
            FROM assignments a JOIN courses c ON a.course_id = c.course_id
            WHERE c.instructor_id = ? ORDER BY a.due_date
        """, (uid,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT a.*, c.course_name,
            CASE WHEN s.submission_id IS NOT NULL THEN s.status ELSE 'not_submitted' END as submission_status,
            s.score, s.submission_id, s.feedback
            FROM assignments a JOIN courses c ON a.course_id = c.course_id
            JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ?
            LEFT JOIN student_submissions s ON a.assignment_id = s.assignment_id AND s.student_id = ?
            WHERE e.status = 'active' ORDER BY a.due_date
        """, (uid, uid)).fetchall()

    conn.close()
    return jsonify({"assignments": [dict(r) for r in rows]}), 200

@app.route('/api/assignments', methods=['POST'])
@jwt_required()
def create_assignment():
    data = request.json
    if not data or not data.get('title') or not data.get('due_date'):
        return jsonify({"error": "title and due_date are required"}), 400

    uid = get_jwt_identity()
    aid = str(uuid.uuid4())
    conn = get_db()
    conn.execute("""
        INSERT INTO assignments (assignment_id, course_id, title, description, due_date, points, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (aid, data['course_id'], data['title'],
          data.get('description', ''), data['due_date'],
          int(data.get('points', 100)), uid, datetime.now().isoformat()))

    course = conn.execute("SELECT course_name FROM courses WHERE course_id=?", (data['course_id'],)).fetchone()
    course_name = course['course_name'] if course else 'your course'
    _post_notification(conn, data['course_id'],
        f"New Assignment: {data['title']}",
        f"A new assignment \"{data['title']}\" has been posted in {course_name}. Due date: {data['due_date']}.",
        uid)

    conn.commit()
    conn.close()
    return jsonify({"message": "Assignment created", "assignment_id": aid}), 201

@app.route('/api/assignments/<assignment_id>', methods=['PUT'])
@jwt_required()
def update_assignment(assignment_id):
    uid = get_jwt_identity()
    data = request.json
    conn = get_db()
    asgn = conn.execute("SELECT created_by FROM assignments WHERE assignment_id=?", (assignment_id,)).fetchone()
    if not asgn:
        conn.close(); return jsonify({"error": "Assignment not found"}), 404
    if asgn['created_by'] != uid:
        conn.close(); return jsonify({"error": "Not authorized"}), 403
    conn.execute("""UPDATE assignments SET title=?, description=?, due_date=?, points=? WHERE assignment_id=?""",
                 (data.get('title'), data.get('description', ''), data.get('due_date'), int(data.get('points', 100)), assignment_id))
    conn.commit(); conn.close()
    return jsonify({"message": "Assignment updated"}), 200

@app.route('/api/assignments/<assignment_id>', methods=['DELETE'])
@jwt_required()
def delete_assignment(assignment_id):
    uid = get_jwt_identity()
    conn = get_db()
    asgn = conn.execute("SELECT created_by FROM assignments WHERE assignment_id=?", (assignment_id,)).fetchone()
    if not asgn:
        conn.close(); return jsonify({"error": "Assignment not found"}), 404
    if asgn['created_by'] != uid:
        conn.close(); return jsonify({"error": "Not authorized"}), 403
    conn.execute("DELETE FROM student_submissions WHERE assignment_id=?", (assignment_id,))
    conn.execute("DELETE FROM assignments WHERE assignment_id=?", (assignment_id,))
    conn.commit(); conn.close()
    return jsonify({"message": "Assignment deleted"}), 200

@app.route('/api/assignments/<assignment_id>/submit', methods=['POST'])
@jwt_required()
def submit_assignment(assignment_id):
    uid = get_jwt_identity()
    conn = get_db()

    assignment = conn.execute(
        "SELECT due_date FROM assignments WHERE assignment_id = ?", (assignment_id,)
    ).fetchone()
    if not assignment:
        conn.close()
        return jsonify({"error": "Assignment not found"}), 404

    today = datetime.now().strftime("%Y-%m-%d")
    if assignment['due_date'] < today:
        conn.close()
        return jsonify({"error": f"Deadline passed on {assignment['due_date']}. Submission is no longer accepted."}), 400

    existing = conn.execute(
        "SELECT submission_id FROM student_submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, uid)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Already submitted"}), 409

    # handle both multipart (file upload) and plain JSON (notes only)
    saved_filename = ''
    notes = ''
    if request.content_type and 'multipart/form-data' in request.content_type:
        notes = request.form.get('notes', '')
        file = request.files.get('file')
        if file and file.filename:
            ext = os.path.splitext(secure_filename(file.filename))[1]
            saved_filename = f"sub_{uid[:8]}_{assignment_id[:8]}{ext}"
            file.save(os.path.join(UPLOAD_FOLDER, saved_filename))
    else:
        data = request.json or {}
        notes = data.get('notes', '')

    sub_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO student_submissions (submission_id, assignment_id, student_id, submitted_at, status, file_path)
        VALUES (?, ?, ?, ?, 'submitted', ?)
    """, (sub_id, assignment_id, uid, datetime.now().isoformat(), saved_filename or notes))

    full_assignment = conn.execute(
        "SELECT title, course_id FROM assignments WHERE assignment_id = ?", (assignment_id,)
    ).fetchone()
    student = conn.execute(
        "SELECT first_name, last_name FROM users WHERE user_id = ?", (uid,)
    ).fetchone()
    if full_assignment and student:
        instructor = conn.execute(
            "SELECT instructor_id FROM courses WHERE course_id = ?", (full_assignment['course_id'],)
        ).fetchone()
        if instructor:
            _post_notification(conn, full_assignment['course_id'],
                f"New Submission: {full_assignment['title']}",
                f"{student['first_name']} {student['last_name']} submitted \"{full_assignment['title']}\".",
                uid, recipient_id=instructor['instructor_id'])

    conn.commit()
    conn.close()
    return jsonify({"message": "Submitted!", "submission_id": sub_id}), 201

@app.route('/api/assignments/<assignment_id>/submissions', methods=['GET'])
@jwt_required()
def get_submissions(assignment_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT s.*, u.first_name, u.last_name, u.email
        FROM student_submissions s JOIN users u ON s.student_id = u.user_id
        WHERE s.assignment_id = ? ORDER BY s.submitted_at DESC
    """, (assignment_id,)).fetchall()
    conn.close()
    return jsonify({"submissions": [dict(r) for r in rows]}), 200

@app.route('/api/assignments/<assignment_id>/grade', methods=['POST'])
@jwt_required()
def grade_assignment(assignment_id):
    data = request.json
    if not data or 'score' not in data or 'student_id' not in data:
        return jsonify({"error": "score and student_id are required"}), 400

    conn = get_db()
    conn.execute("""
        UPDATE student_submissions SET score = ?, feedback = ?, status = 'graded'
        WHERE assignment_id = ? AND student_id = ?
    """, (data['score'], data.get('feedback', ''), assignment_id, data['student_id']))

    assignment = conn.execute(
        "SELECT title, course_id, points FROM assignments WHERE assignment_id = ?", (assignment_id,)
    ).fetchone()
    if assignment:
        feedback_note = f" Feedback: {data['feedback']}" if data.get('feedback') else ""
        _post_notification(conn, assignment['course_id'],
            f"Assignment Graded: {assignment['title']}",
            f"Your submission for \"{assignment['title']}\" has been graded. Score: {data['score']}/{assignment['points']}.{feedback_note}",
            get_jwt_identity(), recipient_id=data['student_id'])

    conn.commit()
    conn.close()
    return jsonify({"message": "Graded"}), 200

# attendance tracking

@app.route('/api/attendance/mark', methods=['POST'])
@jwt_required()
def mark_attendance():
    data = request.json
    if not data:
        return jsonify({"error": "missing data in request"}), 400
    # TODO: need to add bulk attendance marking

    conn = get_db()
    existing = conn.execute(
        "SELECT attendance_id FROM attendance WHERE student_id = ? AND course_id = ? AND date = ?",
        (data['student_id'], data['course_id'], data['date'])
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE attendance SET status = ?, marked_by = ?, marked_at = ?
            WHERE attendance_id = ?
        """, (data['status'], get_jwt_identity(), datetime.now().isoformat(), existing['attendance_id']))
    else:
        conn.execute("""
            INSERT INTO attendance (attendance_id, student_id, course_id, date, status, marked_by, marked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (str(uuid.uuid4()), data['student_id'], data['course_id'],
              data['date'], data['status'], get_jwt_identity(), datetime.now().isoformat()))

    conn.commit()
    conn.close()
    return jsonify({"message": "Attendance recorded"}), 201

@app.route('/api/attendance/student', methods=['GET'])
@jwt_required()
def get_my_attendance():
    uid = get_jwt_identity()
    conn = get_db()
    rows = conn.execute("""
        SELECT a.*, c.course_name FROM attendance a
        JOIN courses c ON a.course_id = c.course_id
        WHERE a.student_id = ? ORDER BY a.date DESC
    """, (uid,)).fetchall()
    conn.close()
    return jsonify({"attendance": [dict(r) for r in rows]}), 200

@app.route('/api/attendance/course/<course_id>', methods=['GET'])
@jwt_required()
def get_course_attendance(course_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT a.*, u.first_name, u.last_name, u.email
        FROM attendance a JOIN users u ON a.student_id = u.user_id
        WHERE a.course_id = ? ORDER BY a.date DESC, u.last_name
    """, (course_id,)).fetchall()
    conn.close()
    return jsonify({"attendance": [dict(r) for r in rows]}), 200

@app.route('/api/attendance/export/<course_id>', methods=['GET'])
@jwt_required()
def export_attendance_csv(course_id):
    conn = get_db()
    course = conn.execute("SELECT course_name, course_code FROM courses WHERE course_id = ?", (course_id,)).fetchone()
    rows = conn.execute("""
        SELECT u.first_name || ' ' || u.last_name AS student_name,
               u.email,
               a.date,
               a.status,
               a.notes
        FROM attendance a
        JOIN users u ON a.student_id = u.user_id
        WHERE a.course_id = ?
        ORDER BY a.date DESC, u.last_name
    """, (course_id,)).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Name", "Email", "Date", "Status", "Notes"])
    for r in rows:
        writer.writerow([r["student_name"], r["email"], r["date"], r["status"], r["notes"] or ""])

    course_label = f"{course['course_code']}" if course else course_id
    filename = f"attendance_{course_label}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.route('/api/attendance/students/<course_id>', methods=['GET'])
@jwt_required()
def get_enrolled_students(course_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT u.user_id, u.first_name, u.last_name, u.email
        FROM users u JOIN enrollments e ON u.user_id = e.student_id
        WHERE e.course_id = ? AND e.status = 'active' ORDER BY u.last_name
    """, (course_id,)).fetchall()
    conn.close()
    return jsonify({"students": [dict(r) for r in rows]}), 200

@app.route('/api/attendance/mark-bulk', methods=['POST'])
@jwt_required()
def mark_attendance_bulk():
    data = request.json
    if not data or not data.get('course_id') or not data.get('date') or not data.get('records'):
        return jsonify({"error": "course_id, date, and records are required"}), 400

    records = data['records']
    if not isinstance(records, list) or len(records) == 0:
        return jsonify({"error": "records must be a non-empty list"}), 400

    marker_id = get_jwt_identity()
    conn = get_db()
    saved = 0
    for rec in records:
        student_id = rec.get('student_id')
        status = rec.get('status', 'present')
        if not student_id:
            continue
        existing = conn.execute(
            "SELECT attendance_id FROM attendance WHERE student_id = ? AND course_id = ? AND date = ?",
            (student_id, data['course_id'], data['date'])
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE attendance SET status = ?, marked_by = ?, marked_at = ? WHERE attendance_id = ?",
                (status, marker_id, datetime.now().isoformat(), existing['attendance_id'])
            )
        else:
            conn.execute("""
                INSERT INTO attendance (attendance_id, student_id, course_id, date, status, marked_by, marked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), student_id, data['course_id'],
                  data['date'], status, marker_id, datetime.now().isoformat()))
        saved += 1

    conn.commit()
    conn.close()
    return jsonify({"message": f"{saved} attendance record(s) saved"}), 201

# announcements

@app.route('/api/announcements', methods=['GET'])
@jwt_required()
def get_announcements():
    uid = get_jwt_identity()
    course_id = request.args.get('course_id')
    conn = get_db()
    seen_sub = "EXISTS(SELECT 1 FROM announcement_views WHERE announcement_id=a.announcement_id AND user_id=?)"

    if course_id:
        rows = conn.execute(f"""
            SELECT a.*, u.first_name || ' ' || u.last_name as author_name,
                   {seen_sub} as is_read
            FROM announcements a JOIN users u ON a.created_by = u.user_id
            WHERE a.course_id = ? AND (a.recipient_id IS NULL OR a.recipient_id = ?)
            ORDER BY a.created_at DESC
        """, (uid, course_id, uid)).fetchall()
    else:
        user = conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()
        if user and user['role'] == 'professor':
            rows = conn.execute(f"""
                SELECT a.*, u.first_name || ' ' || u.last_name as author_name, c.course_name,
                       {seen_sub} as is_read
                FROM announcements a JOIN users u ON a.created_by = u.user_id
                JOIN courses c ON a.course_id = c.course_id
                WHERE c.instructor_id = ?
                  AND (
                    a.is_notification = 0
                    OR (a.is_notification = 1 AND a.recipient_id = ?)
                  )
                ORDER BY a.created_at DESC
            """, (uid, uid, uid)).fetchall()
        else:
            rows = conn.execute(f"""
                SELECT DISTINCT a.*, u.first_name || ' ' || u.last_name as author_name, c.course_name,
                       {seen_sub} as is_read
                FROM announcements a JOIN users u ON a.created_by = u.user_id
                JOIN courses c ON a.course_id = c.course_id
                JOIN enrollments e ON a.course_id = e.course_id
                WHERE e.student_id = ? AND e.status = 'active'
                  AND (a.recipient_id IS NULL OR a.recipient_id = ?)
                ORDER BY a.created_at DESC
            """, (uid, uid, uid)).fetchall()

    conn.close()
    return jsonify({"announcements": [dict(r) for r in rows]}), 200

@app.route('/api/announcements/unread-count', methods=['GET'])
@jwt_required()
def get_unread_count():
    uid = get_jwt_identity()
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()
    if user and user['role'] == 'professor':
        count = conn.execute("""
            SELECT COUNT(*) as cnt FROM announcements a
            JOIN courses c ON a.course_id = c.course_id
            WHERE c.instructor_id = ?
              AND NOT EXISTS(SELECT 1 FROM announcement_views WHERE announcement_id=a.announcement_id AND user_id=?)
        """, (uid, uid)).fetchone()['cnt']
    else:
        count = conn.execute("""
            SELECT COUNT(DISTINCT a.announcement_id) as cnt
            FROM announcements a
            JOIN courses c ON a.course_id = c.course_id
            JOIN enrollments e ON a.course_id = e.course_id
            WHERE e.student_id = ? AND e.status = 'active'
              AND (a.recipient_id IS NULL OR a.recipient_id = ?)
              AND NOT EXISTS(SELECT 1 FROM announcement_views WHERE announcement_id=a.announcement_id AND user_id=?)
        """, (uid, uid, uid)).fetchone()['cnt']
    conn.close()
    return jsonify({"unread": count}), 200

@app.route('/api/announcements/mark-read', methods=['POST'])
@jwt_required()
def mark_announcements_read():
    uid = get_jwt_identity()
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()
    now = datetime.now().isoformat()

    # was fetching all ids first then looping insertions — hitting db like 40 times per call
    # ids = conn.execute("SELECT announcement_id FROM announcements ...").fetchall()
    # for row in ids:
    #     conn.execute("INSERT OR IGNORE INTO announcement_views ...", (uuid, row['announcement_id'], uid, now))

    if user and user['role'] == 'professor':
        conn.execute("""
            INSERT OR IGNORE INTO announcement_views (view_id, announcement_id, user_id, seen_at)
            SELECT lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||
                   substr(lower(hex(randomblob(2))),2)||'-'||
                   substr('89ab',abs(random())%4+1,1)||
                   substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6))),
                   a.announcement_id, ?, ?
            FROM announcements a
            JOIN courses c ON a.course_id = c.course_id
            WHERE c.instructor_id = ?
        """, (uid, now, uid))
    else:
        conn.execute("""
            INSERT OR IGNORE INTO announcement_views (view_id, announcement_id, user_id, seen_at)
            SELECT lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||
                   substr(lower(hex(randomblob(2))),2)||'-'||
                   substr('89ab',abs(random())%4+1,1)||
                   substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6))),
                   a.announcement_id, ?, ?
            FROM announcements a
            JOIN courses c ON a.course_id = c.course_id
            JOIN enrollments e ON a.course_id = e.course_id
            WHERE e.student_id = ? AND e.status = 'active'
              AND (a.recipient_id IS NULL OR a.recipient_id = ?)
        """, (uid, now, uid, uid))

    conn.commit()
    conn.close()
    return jsonify({"message": "Marked as read"}), 200

@app.route('/api/announcements', methods=['POST'])
@jwt_required()
def create_announcement():
    data = request.json
    if not data or not data.get('title') or not data.get('content'):
        return jsonify({"error": "missing fields"}), 400

    ann_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute("""
        INSERT INTO announcements (announcement_id, course_id, title, content, created_by, priority, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (ann_id, data['course_id'], data['title'], data['content'],
          get_jwt_identity(), data.get('priority', 'normal'), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"message": "Announcement posted"}), 201

# forum / Q&A

@app.route('/api/forum/questions', methods=['GET'])
@jwt_required()
def get_questions():
    course_id = request.args.get('course_id')
    if not course_id:
        return jsonify({"error": "course_id required"}), 400

    conn = get_db()
    rows = conn.execute("""
        SELECT q.*, u.first_name || ' ' || u.last_name as author_name,
        (SELECT COUNT(*) FROM question_answers WHERE question_id = q.question_id) as answer_count
        FROM questions q JOIN users u ON q.asked_by = u.user_id
        WHERE q.course_id = ? ORDER BY q.created_at DESC
    """, (course_id,)).fetchall()
    conn.close()
    return jsonify({"questions": [dict(r) for r in rows]}), 200

@app.route('/api/forum/questions', methods=['POST'])
@jwt_required()
def post_question():
    uid = get_jwt_identity()
    data = request.json
    if not data or not data.get('title') or not data.get('question_text'):
        return jsonify({"error": "title and question_text required"}), 400

    qid = str(uuid.uuid4())
    conn = get_db()
    conn.execute("""
        INSERT INTO questions (question_id, course_id, title, question_text, asked_by, created_at, is_answered, views)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0)
    """, (qid, data['course_id'], data['title'], data['question_text'], uid, datetime.now().isoformat()))

    asker = conn.execute("SELECT role, first_name, last_name FROM users WHERE user_id = ?", (uid,)).fetchone()
    if asker and asker['role'] == 'student':
        instructor = conn.execute(
            "SELECT instructor_id FROM courses WHERE course_id = ?", (data['course_id'],)
        ).fetchone()
        if instructor:
            _post_notification(conn, data['course_id'],
                f"New Question: {data['title']}",
                f"{asker['first_name']} {asker['last_name']} posted a question: \"{data['title']}\".",
                uid, recipient_id=instructor['instructor_id'])

    conn.commit()
    conn.close()
    return jsonify({"message": "Question posted", "question_id": qid}), 201

@app.route('/api/forum/questions/<question_id>', methods=['GET'])
@jwt_required()
def get_question_detail(question_id):
    conn = get_db()
    question = conn.execute("""
        SELECT q.*, u.first_name || ' ' || u.last_name as author_name
        FROM questions q JOIN users u ON q.asked_by = u.user_id
        WHERE q.question_id = ?
    """, (question_id,)).fetchone()

    if not question:
        conn.close()
        return jsonify({"error": "Question not found"}), 404

    answers = conn.execute("""
        SELECT a.*, u.first_name || ' ' || u.last_name as author_name, u.role
        FROM question_answers a JOIN users u ON a.answered_by = u.user_id
        WHERE a.question_id = ? ORDER BY a.is_accepted DESC, a.created_at
    """, (question_id,)).fetchall()

    conn.execute("UPDATE questions SET views = views + 1 WHERE question_id = ?", (question_id,))
    conn.commit()
    conn.close()
    return jsonify({"question": dict(question), "answers": [dict(a) for a in answers]}), 200

@app.route('/api/forum/questions/<question_id>/answers', methods=['POST'])
@jwt_required()
def post_answer(question_id):
    uid = get_jwt_identity()
    data = request.json
    if not data or not data.get('answer_text'):
        return jsonify({"error": "answer_text is required"}), 400

    aid = str(uuid.uuid4())
    conn = get_db()
    conn.execute("""
        INSERT INTO question_answers (answer_id, question_id, answer_text, answered_by, created_at, is_accepted, upvotes)
        VALUES (?, ?, ?, ?, ?, 0, 0)
    """, (aid, question_id, data['answer_text'], uid, datetime.now().isoformat()))
    conn.execute("UPDATE questions SET is_answered = 1 WHERE question_id = ?", (question_id,))

    question = conn.execute(
        "SELECT asked_by, title, course_id FROM questions WHERE question_id = ?", (question_id,)
    ).fetchone()
    if question and question['asked_by'] != uid:
        answerer = conn.execute(
            "SELECT first_name, last_name, role FROM users WHERE user_id = ?", (uid,)
        ).fetchone()
        answerer_label = f"Prof. {answerer['last_name']}" if answerer and answerer['role'] == 'professor' else (f"{answerer['first_name']} {answerer['last_name']}" if answerer else "Someone")
        _post_notification(conn, question['course_id'],
            "Your question received an answer",
            f"{answerer_label} answered your question: \"{question['title']}\".",
            uid, recipient_id=question['asked_by'])

    conn.commit()
    conn.close()
    return jsonify({"message": "Answer posted"}), 201

# resources upload

@app.route('/api/resources', methods=['GET'])
@jwt_required()
def get_resources():
    course_id = request.args.get('course_id')
    uid = get_jwt_identity()
    conn = get_db()

    if course_id:
        rows = conn.execute("""
            SELECT r.*, u.first_name || ' ' || u.last_name as uploader_name, c.course_name
            FROM resources r
            JOIN users u ON r.uploaded_by = u.user_id
            JOIN courses c ON r.course_id = c.course_id
            WHERE r.course_id = ? ORDER BY r.uploaded_at DESC
        """, (course_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT r.*, u.first_name || ' ' || u.last_name as uploader_name, c.course_name
            FROM resources r
            JOIN users u ON r.uploaded_by = u.user_id
            JOIN courses c ON r.course_id = c.course_id
            LEFT JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ?
            WHERE c.instructor_id = ? OR e.student_id = ?
            ORDER BY r.uploaded_at DESC
        """, (uid, uid, uid)).fetchall()

    conn.close()
    return jsonify({"resources": [dict(r) for r in rows]}), 200

@app.route('/api/resources', methods=['POST'])
@jwt_required()
def upload_resource():
    if 'file' not in request.files:
        return jsonify({"error": "no file"}), 400

    file = request.files['file']
    course_id = request.form.get('course_id')
    title = request.form.get('title')

    if not course_id or not title:
        return jsonify({"error": "need course_id and title"}), 400

    allowed = {'pdf', 'pptx', 'docx', 'xlsx', 'txt', 'png', 'jpg', 'zip'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if not ext or ext not in allowed:
        return jsonify({"error": "file type not allowed"}), 400

    rid = str(uuid.uuid4())
    fname = f"{rid}_{secure_filename(file.filename)}"
    file.save(os.path.join(UPLOAD_FOLDER, fname))
    print("file saved:", fname)

    conn = get_db()
    conn.execute("""
        INSERT INTO resources (resource_id, course_id, title, description, file_path, file_type, uploaded_by, uploaded_at, downloads)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (rid, course_id, title, request.form.get('description', ''),
          fname, ext, get_jwt_identity(), datetime.now().isoformat()))
    conn.commit()
    conn.close()

    ai = get_ai()
    if ai:
        ai.refresh_knowledge()

    return jsonify({"message": "Uploaded!", "resource_id": rid}), 201

@app.route('/api/resources/<resource_id>/download', methods=['GET'])
@jwt_required()
def download_resource(resource_id):
    conn = get_db()
    row = conn.execute(
        "SELECT file_path, title, file_type FROM resources WHERE resource_id = ?", (resource_id,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    conn.execute("UPDATE resources SET downloads = downloads + 1 WHERE resource_id = ?", (resource_id,))
    conn.commit()
    conn.close()
    return send_from_directory(UPLOAD_FOLDER, row['file_path'], as_attachment=True,
                               download_name=f"{row['title']}.{row['file_type']}")

# AI endpoints
# connects to ai_assistant.py

@app.route('/api/ai/chat', methods=['POST'])
@jwt_required()
def ai_chat():
    uid = get_jwt_identity()
    data = request.json
    if not data or not data.get('message'):
        return jsonify({"error": "message required"}), 400

    ai = get_ai()
    if not ai:
        msg = f"AI failed to start: {_ai_error}" if _ai_error else "AI not available. Add your OPENAI_API_KEY to the .env file."
        return jsonify({"response": msg}), 200

    try:
        lang = data.get('lang', 'en')
        result = ai.ask(data['message'], student_id=uid, course_id=data.get('course_id'), lang=lang)
        answer, suggested = result if isinstance(result, tuple) else (result, [])
        return jsonify({"response": answer, "resources": suggested}), 200
    except Exception as e:
        return jsonify({"response": f"AI error: {e}", "resources": []}), 200

@app.route('/api/ai/attendance-risk', methods=['GET'])
@jwt_required()
def get_attendance_risk():
    uid = get_jwt_identity()
    ai = get_ai()
    if not ai:
        return jsonify({"risk_level": "unknown", "recommendation": "AI unavailable",
                        "attendance_rate": 0, "absences": 0, "total_classes": 0, "courses_at_risk": []}), 200
    return jsonify(ai.analyze_attendance_risk(uid)), 200

@app.route('/api/ai/workload-optimization', methods=['GET'])
@jwt_required()
def optimize_workload():
    uid = get_jwt_identity()
    ai = get_ai()
    if not ai:
        return jsonify({"schedule": [], "workload_analysis": {}, "recommendations": []}), 200
    return jsonify(ai.optimize_workload(uid)), 200

@app.route("/api/ai/student-report", methods=["GET"])
@jwt_required()
def student_report():
    uid = get_jwt_identity()
    ai = get_ai()
    if not ai:
        return jsonify({"narrative": "AI unavailable", "raw_snapshot": ""}), 200
    lang = request.args.get('lang', 'en')
    return jsonify(ai.generate_student_report(uid, lang=lang)), 200

@app.route("/api/ai/professor-insights", methods=["GET"])
@jwt_required()
def professor_insights():
    uid = get_jwt_identity()
    ai = get_ai()
    if not ai:
        return jsonify({"narrative": "AI unavailable", "raw_snapshot": ""}), 200
    lang = request.args.get('lang', 'en')
    return jsonify(ai.generate_professor_insights(uid, lang=lang)), 200

@app.route('/api/ai/refresh', methods=['POST'])
@jwt_required()
def refresh_ai():
    ai = get_ai()
    if not ai:
        return jsonify({"error": "AI not available"}), 503
    ai.refresh_knowledge()
    return jsonify({"message": "Knowledge refreshed"}), 200

@app.route('/api/ai/clear-history', methods=['POST'])
@jwt_required()
def clear_chat_history():
    uid = get_jwt_identity()
    ai = get_ai()
    if ai:
        ai.clear_history(uid)
    return jsonify({"message": "Conversation cleared"}), 200

# Analytics

@app.route('/api/analytics/professor', methods=['GET'])
@jwt_required()
def professor_analytics():
    uid = get_jwt_identity()
    conn = get_db()

    risk_counts = {"high": 0, "medium": 0, "low": 0}
    risk_students = []

    courses = conn.execute("SELECT course_id, course_name FROM courses WHERE instructor_id=?", (uid,)).fetchall()
    for course in courses:
        students = conn.execute("""
            SELECT u.user_id, u.first_name || ' ' || u.last_name as name, u.email
            FROM users u JOIN enrollments e ON u.user_id = e.student_id
            WHERE e.course_id = ? AND e.status = 'active'
        """, (course['course_id'],)).fetchall()

        for s in students:
            att = conn.execute(
                "SELECT status FROM attendance WHERE student_id=? AND course_id=?",
                (s['user_id'], course['course_id'])
            ).fetchall()
            att_rate = (sum(1 for a in att if a['status'] in ('present', 'late')) / len(att) * 100) if att else 100
            rate_r = round(att_rate, 1)

            if att_rate < 65:
                risk_counts["high"] += 1
                risk_students.append({"name": s['name'], "email": s['email'], "attendance": rate_r, "course": course['course_name'], "risk_level": "high", "reason": f"Attendance critically low at {rate_r}% (threshold: 65%)"})
            elif att_rate < 75:
                risk_counts["medium"] += 1
                risk_students.append({"name": s['name'], "email": s['email'], "attendance": rate_r, "course": course['course_name'], "risk_level": "medium", "reason": f"Attendance at {rate_r}% — approaching the 75% minimum"})
            else:
                risk_counts["low"] += 1

    conn.close()
    at_risk     = [s for s in risk_students if s["risk_level"] == "high"][:10]
    medium_risk = [s for s in risk_students if s["risk_level"] == "medium"][:10]
    return jsonify({
        "high_risk_students": risk_counts["high"],
        "medium_risk_students": risk_counts["medium"],
        "low_risk_students": risk_counts["low"],
        "at_risk_students": at_risk,
        "medium_risk_students_list": medium_risk
    }), 200

# quizzes

@app.route('/api/quizzes', methods=['GET'])
@jwt_required()
def get_quizzes():
    uid = get_jwt_identity()
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id=?", (uid,)).fetchone()
    today = datetime.now().strftime("%Y-%m-%d")

    if user and user['role'] == 'professor':
        rows = conn.execute("""
            SELECT q.*, c.course_name, c.course_code,
                   (SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = q.quiz_id) as question_count,
                   (SELECT COUNT(*) FROM quiz_attempts WHERE quiz_id = q.quiz_id AND status != 'graded_zero') as attempt_count
            FROM quizzes q JOIN courses c ON q.course_id = c.course_id
            WHERE q.created_by = ? ORDER BY q.quiz_date DESC
        """, (uid,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT q.*, c.course_name, c.course_code,
                   (SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = q.quiz_id) as question_count,
                   a.score, a.status as attempt_status, a.submitted_at as attempted_at
            FROM quizzes q
            JOIN courses c ON q.course_id = c.course_id
            JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ? AND e.status = 'active'
            LEFT JOIN quiz_attempts a ON q.quiz_id = a.quiz_id AND a.student_id = ?
            ORDER BY q.quiz_date DESC
        """, (uid, uid)).fetchall()

        # auto-grade zero for past quizzes with no attempt
        for row in rows:
            if row['quiz_date'] < today and (row['attempt_status'] is None or row['attempt_status'] == 'pending'):
                existing = conn.execute(
                    "SELECT attempt_id FROM quiz_attempts WHERE quiz_id=? AND student_id=?",
                    (row['quiz_id'], uid)
                ).fetchone()
                total = row['question_count']
                if existing:
                    conn.execute(
                        "UPDATE quiz_attempts SET score=0, status='graded_zero', submitted_at=? WHERE attempt_id=?",
                        (datetime.now().isoformat(), existing['attempt_id'])
                    )
                else:
                    conn.execute("""
                        INSERT INTO quiz_attempts (attempt_id, quiz_id, student_id, answers, score, total, submitted_at, status)
                        VALUES (?, ?, ?, '{}', 0, ?, ?, 'graded_zero')
                    """, (str(uuid.uuid4()), row['quiz_id'], uid, total, datetime.now().isoformat()))
        conn.commit()

        # re-fetch with updated attempt data — temp fix, ideally update in place
        rows = conn.execute("""
            SELECT q.*, c.course_name, c.course_code,
                   (SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = q.quiz_id) as question_count,
                   a.score, a.status as attempt_status, a.submitted_at as attempted_at
            FROM quizzes q
            JOIN courses c ON q.course_id = c.course_id
            JOIN enrollments e ON c.course_id = e.course_id AND e.student_id = ? AND e.status = 'active'
            LEFT JOIN quiz_attempts a ON q.quiz_id = a.quiz_id AND a.student_id = ?
            ORDER BY q.quiz_date DESC
        """, (uid, uid)).fetchall()

    conn.close()
    return jsonify({"quizzes": [dict(r) for r in rows]}), 200


@app.route('/api/quizzes', methods=['POST'])
@jwt_required()
def create_quiz():
    uid = get_jwt_identity()
    data = request.json
    if not data or not data.get('title') or not data.get('quiz_date') or not data.get('course_id'):
        return jsonify({"error": "missing required fields"}), 400
    questions = data.get('questions', [])
    if len(questions) == 0:
        return jsonify({"error": "At least one question is required"}), 400

    quiz_id = str(uuid.uuid4())
    total_points = len(questions)
    conn = get_db()

    conn.execute("""
        INSERT INTO quizzes (quiz_id, course_id, created_by, title, description, quiz_date, total_points, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (quiz_id, data['course_id'], uid, data['title'],
          data.get('description', ''), data['quiz_date'], total_points, datetime.now().isoformat()))

    for i, q in enumerate(questions):
        conn.execute("""
            INSERT INTO quiz_questions (question_id, quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option, question_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(uuid.uuid4()), quiz_id, q['question_text'],
              q['option_a'], q['option_b'], q['option_c'], q['option_d'],
              q['correct_option'], i))

    course = conn.execute("SELECT course_name FROM courses WHERE course_id=?", (data['course_id'],)).fetchone()
    course_name = course['course_name'] if course else 'your course'
    _post_notification(conn, data['course_id'],
        f"Quiz Scheduled: {data['title']}",
        f"A quiz titled \"{data['title']}\" has been scheduled for {data['quiz_date']} in {course_name}. "
        f"It consists of {total_points} MCQ question{'s' if total_points != 1 else ''}, each worth 1 point. "
        f"The quiz will only be accessible on {data['quiz_date']}.",
        uid)

    conn.commit()
    conn.close()
    return jsonify({"message": "Quiz created", "quiz_id": quiz_id}), 201

@app.route('/api/quizzes/<quiz_id>', methods=['PUT'])
@jwt_required()
def update_quiz(quiz_id):
    uid = get_jwt_identity()
    data = request.json
    conn = get_db()
    quiz = conn.execute("SELECT created_by FROM quizzes WHERE quiz_id=?", (quiz_id,)).fetchone()
    if not quiz:
        conn.close(); return jsonify({"error": "Quiz not found"}), 404
    if quiz['created_by'] != uid:
        conn.close(); return jsonify({"error": "Not authorized"}), 403
    conn.execute("""UPDATE quizzes SET title=?, description=?, quiz_date=? WHERE quiz_id=?""",
                 (data.get('title'), data.get('description', ''), data.get('quiz_date'), quiz_id))
    conn.commit(); conn.close()
    return jsonify({"message": "Quiz updated"}), 200

@app.route('/api/quizzes/<quiz_id>', methods=['DELETE'])
@jwt_required()
def delete_quiz(quiz_id):
    uid = get_jwt_identity()
    conn = get_db()
    quiz = conn.execute("SELECT created_by FROM quizzes WHERE quiz_id=?", (quiz_id,)).fetchone()
    if not quiz:
        conn.close(); return jsonify({"error": "Quiz not found"}), 404
    if quiz['created_by'] != uid:
        conn.close(); return jsonify({"error": "Not authorized"}), 403
    conn.execute("DELETE FROM quiz_attempts WHERE quiz_id=?", (quiz_id,))
    conn.execute("DELETE FROM quiz_questions WHERE quiz_id=?", (quiz_id,))
    conn.execute("DELETE FROM quizzes WHERE quiz_id=?", (quiz_id,))
    conn.commit(); conn.close()
    return jsonify({"message": "Quiz deleted"}), 200

@app.route('/api/quizzes/<quiz_id>', methods=['GET'])
@jwt_required()
def get_quiz(quiz_id):
    uid = get_jwt_identity()
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    quiz = conn.execute("""
        SELECT q.*, c.course_name,
               (SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = q.quiz_id) as question_count
        FROM quizzes q JOIN courses c ON q.course_id = c.course_id
        WHERE q.quiz_id = ?
    """, (quiz_id,)).fetchone()

    if not quiz:
        conn.close()
        return jsonify({"error": "Quiz not found"}), 404

    user = conn.execute("SELECT role FROM users WHERE user_id=?", (uid,)).fetchone()
    questions = conn.execute(
        "SELECT * FROM quiz_questions WHERE quiz_id=? ORDER BY question_order", (quiz_id,)
    ).fetchall()

    result = dict(quiz)
    if user and user['role'] == 'professor':
        result['questions'] = [dict(q) for q in questions]
    else:
        # students only get questions on quiz day
        if quiz['quiz_date'] != today:
            conn.close()
            return jsonify({"error": "Quiz is only accessible on its scheduled date", "quiz_date": quiz['quiz_date']}), 403
        # strip correct answers
        safe_qs = []
        for q in questions:
            d = dict(q)
            del d['correct_option']
            safe_qs.append(d)
        result['questions'] = safe_qs

    conn.close()
    return jsonify(result), 200


@app.route('/api/quizzes/<quiz_id>/attempt', methods=['POST'])
@jwt_required()
def submit_quiz(quiz_id):
    uid = get_jwt_identity()
    data = request.json or {}
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()

    quiz = conn.execute("SELECT * FROM quizzes WHERE quiz_id=?", (quiz_id,)).fetchone()
    if not quiz:
        conn.close()
        return jsonify({"error": "Quiz not found"}), 404

    if quiz['quiz_date'] != today:
        conn.close()
        return jsonify({"error": "Quiz can only be submitted on its scheduled date"}), 403

    existing = conn.execute(
        "SELECT attempt_id FROM quiz_attempts WHERE quiz_id=? AND student_id=?", (quiz_id, uid)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Already attempted this quiz"}), 409

    answers = data.get('answers', {})  # {question_id: selected_option}
    questions = conn.execute(
        "SELECT question_id, correct_option FROM quiz_questions WHERE quiz_id=?", (quiz_id,)
    ).fetchall()

    score = sum(1 for q in questions if answers.get(q['question_id']) == q['correct_option'])
    total = len(questions)

    import json
    attempt_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO quiz_attempts (attempt_id, quiz_id, student_id, answers, score, total, submitted_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted')
    """, (attempt_id, quiz_id, uid, json.dumps(answers), score, total, datetime.now().isoformat()))

    quiz_info = conn.execute(
        "SELECT title, course_id FROM quizzes WHERE quiz_id=?", (quiz_id,)
    ).fetchone()
    if quiz_info:
        _post_notification(conn, quiz_info['course_id'],
            f"Quiz Graded: {quiz_info['title']}",
            f"Your quiz \"{quiz_info['title']}\" has been auto-graded. You scored {score}/{total}.",
            uid, recipient_id=uid)

    conn.commit()
    conn.close()
    return jsonify({"message": "Quiz submitted", "score": score, "total": total}), 201


@app.route('/api/quizzes/<quiz_id>/results', methods=['GET'])
@jwt_required()
def get_quiz_results(quiz_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT a.*, u.first_name || ' ' || u.last_name as student_name, u.email
        FROM quiz_attempts a JOIN users u ON a.student_id = u.user_id
        WHERE a.quiz_id = ? ORDER BY a.score DESC
    """, (quiz_id,)).fetchall()
    conn.close()
    return jsonify({"results": [dict(r) for r in rows]}), 200


@app.route('/api/quizzes/<quiz_id>/review', methods=['GET'])
@jwt_required()
def review_quiz(quiz_id):
    """Return per-question right/wrong only after the quiz date has passed."""
    import json as _json
    uid   = get_jwt_identity()
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = get_db()

    quiz = conn.execute("SELECT * FROM quizzes WHERE quiz_id=?", (quiz_id,)).fetchone()
    if not quiz:
        conn.close()
        return jsonify({"error": "Quiz not found"}), 404

    attempt = conn.execute(
        "SELECT * FROM quiz_attempts WHERE quiz_id=? AND student_id=?", (quiz_id, uid)
    ).fetchone()
    if not attempt:
        conn.close()
        return jsonify({"error": "No attempt found"}), 404

    answers     = _json.loads(attempt['answers'] or '{}')
    quiz_closed = quiz['quiz_date'] < today   # only reveal after quiz date is over

    if not quiz_closed:
        conn.close()
        return jsonify({
            "score": attempt['score'], "total": attempt['total'],
            "quiz_closed": False, "quiz_date": quiz['quiz_date']
        }), 200

    questions = conn.execute(
        "SELECT question_id, question_text, option_a, option_b, option_c, option_d, correct_option "
        "FROM quiz_questions WHERE quiz_id=?", (quiz_id,)
    ).fetchall()
    conn.close()

    review_qs = [{
        "question_id":   q['question_id'],
        "question_text": q['question_text'],
        "option_a": q['option_a'], "option_b": q['option_b'],
        "option_c": q['option_c'], "option_d": q['option_d'],
        "correct_option":  q['correct_option'],
        "student_answer":  answers.get(q['question_id']),
        "is_correct":      answers.get(q['question_id']) == q['correct_option'],
    } for q in questions]

    return jsonify({
        "score": attempt['score'], "total": attempt['total'],
        "quiz_closed": True, "quiz_date": quiz['quiz_date'],
        "questions": review_qs
    }), 200


@app.route('/api/submissions/<submission_id>/file', methods=['GET'])
@jwt_required()
def download_submission_file(submission_id):
    conn = get_db()
    row = conn.execute(
        "SELECT file_path, student_id FROM student_submissions WHERE submission_id = ?", (submission_id,)
    ).fetchone()
    conn.close()
    if not row or not row['file_path'] or '.' not in row['file_path']:
        return jsonify({"error": "No file attached"}), 404
    return send_from_directory(UPLOAD_FOLDER, row['file_path'], as_attachment=True)

@app.route('/api/grades', methods=['GET'])
@jwt_required()
def get_grades():
    uid = get_jwt_identity()
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()

    if user and user['role'] == 'professor':
        course_id = request.args.get('course_id')
        if course_id:
            rows = conn.execute("""
                SELECT g.grade_id, g.score, g.max_score, g.graded_at,
                       a.title as assignment_title, NULL as quiz_title, 'assignment' as entry_type,
                       u.first_name || ' ' || u.last_name as student_name,
                       u.email as student_email,
                       c.course_name
                FROM grades g
                JOIN users u ON g.student_id = u.user_id
                JOIN courses c ON g.course_id = c.course_id
                LEFT JOIN assignments a ON g.assignment_id = a.assignment_id
                WHERE g.course_id = ?
                UNION ALL
                SELECT qa.attempt_id, qa.score, qa.total, qa.submitted_at,
                       NULL, q.title, 'quiz',
                       u.first_name || ' ' || u.last_name,
                       u.email,
                       c.course_name
                FROM quiz_attempts qa
                JOIN quizzes q ON qa.quiz_id = q.quiz_id
                JOIN users u ON qa.student_id = u.user_id
                JOIN courses c ON q.course_id = c.course_id
                WHERE q.course_id = ? AND qa.status IN ('submitted', 'graded_zero')
                ORDER BY graded_at DESC
            """, (course_id, course_id)).fetchall()
        else:
            rows = conn.execute("""
                SELECT g.grade_id, g.score, g.max_score, g.graded_at,
                       a.title as assignment_title, NULL as quiz_title, 'assignment' as entry_type,
                       u.first_name || ' ' || u.last_name as student_name,
                       u.email as student_email,
                       c.course_name
                FROM grades g
                JOIN users u ON g.student_id = u.user_id
                JOIN courses c ON g.course_id = c.course_id
                LEFT JOIN assignments a ON g.assignment_id = a.assignment_id
                WHERE c.instructor_id = ?
                UNION ALL
                SELECT qa.attempt_id, qa.score, qa.total, qa.submitted_at,
                       NULL, q.title, 'quiz',
                       u.first_name || ' ' || u.last_name,
                       u.email,
                       c.course_name
                FROM quiz_attempts qa
                JOIN quizzes q ON qa.quiz_id = q.quiz_id
                JOIN users u ON qa.student_id = u.user_id
                JOIN courses c ON q.course_id = c.course_id
                WHERE c.instructor_id = ? AND qa.status IN ('submitted', 'graded_zero')
                ORDER BY c.course_name, graded_at DESC
            """, (uid, uid)).fetchall()
    else:
        rows = conn.execute("""
            SELECT g.grade_id, g.score, g.max_score, g.grade_type, g.graded_at,
                   a.title as assignment_title,
                   c.course_name,
                   s.feedback
            FROM grades g
            JOIN courses c ON g.course_id = c.course_id
            LEFT JOIN assignments a ON g.assignment_id = a.assignment_id
            LEFT JOIN student_submissions s ON g.assignment_id = s.assignment_id AND s.student_id = g.student_id
            WHERE g.student_id = ?
            ORDER BY g.graded_at DESC
        """, (uid,)).fetchall()

    conn.close()
    return jsonify({"grades": [dict(r) for r in rows]}), 200


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5002)
