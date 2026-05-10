import sqlite3
from datetime import datetime


def init_database():
    conn = sqlite3.connect('academia_main.db')
    cursor = conn.cursor()

    # Users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student', 'professor')),
            phone TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME
        )
    ''')

    # Courses
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            course_id TEXT PRIMARY KEY,
            course_code TEXT NOT NULL,
            course_name TEXT NOT NULL,
            description TEXT,
            instructor_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            year INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (instructor_id) REFERENCES users(user_id)
        )
    ''')

    # Enrollments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS enrollments (
            enrollment_id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            course_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'dropped', 'completed')),
            enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(user_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    ''')

    # Attendance
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            attendance_id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            course_id TEXT NOT NULL,
            date DATE NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('present', 'absent', 'late', 'excused', 'unexcused')),
            marked_by TEXT NOT NULL,
            marked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (student_id) REFERENCES users(user_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id),
            FOREIGN KEY (marked_by) REFERENCES users(user_id)
        )
    ''')

    # Assignments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assignments (
            assignment_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_date DATE NOT NULL,
            points INTEGER NOT NULL,
            created_by TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id),
            FOREIGN KEY (created_by) REFERENCES users(user_id)
        )
    ''')

    # Student submissions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_submissions (
            submission_id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            file_path TEXT,
            status TEXT NOT NULL CHECK(status IN ('submitted', 'graded', 'late', 'pending')),
            score REAL,
            feedback TEXT,
            FOREIGN KEY (assignment_id) REFERENCES assignments(assignment_id),
            FOREIGN KEY (student_id) REFERENCES users(user_id)
        )
    ''')

    # Grades
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grades (
            grade_id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            course_id TEXT NOT NULL,
            assignment_id TEXT,
            score REAL NOT NULL,
            max_score REAL NOT NULL,
            grade_type TEXT NOT NULL CHECK(grade_type IN ('assignment', 'quiz', 'project')),
            graded_by TEXT NOT NULL,
            graded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(user_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id),
            FOREIGN KEY (assignment_id) REFERENCES assignments(assignment_id),
            FOREIGN KEY (graded_by) REFERENCES users(user_id)
        )
    ''')

    # Announcements — also used for system notifications via is_notification + recipient_id
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            announcement_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            priority TEXT DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high', 'urgent')),
            recipient_id TEXT,
            is_notification INTEGER DEFAULT 0,
            FOREIGN KEY (course_id) REFERENCES courses(course_id),
            FOREIGN KEY (created_by) REFERENCES users(user_id),
            FOREIGN KEY (recipient_id) REFERENCES users(user_id)
        )
    ''')

    # Announcement views — tracks who has read what
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS announcement_views (
            view_id TEXT PRIMARY KEY,
            announcement_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (announcement_id) REFERENCES announcements(announcement_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE(announcement_id, user_id)
        )
    ''')

    # Q&A Forum questions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            question_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            title TEXT NOT NULL,
            question_text TEXT NOT NULL,
            asked_by TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_answered BOOLEAN DEFAULT 0,
            views INTEGER DEFAULT 0,
            FOREIGN KEY (course_id) REFERENCES courses(course_id),
            FOREIGN KEY (asked_by) REFERENCES users(user_id)
        )
    ''')

    # Q&A Forum answers
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS question_answers (
            answer_id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL,
            answer_text TEXT NOT NULL,
            answered_by TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_accepted BOOLEAN DEFAULT 0,
            upvotes INTEGER DEFAULT 0,
            FOREIGN KEY (question_id) REFERENCES questions(question_id),
            FOREIGN KEY (answered_by) REFERENCES users(user_id)
        )
    ''')

    # Resources
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS resources (
            resource_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            uploaded_by TEXT NOT NULL,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            downloads INTEGER DEFAULT 0,
            FOREIGN KEY (course_id) REFERENCES courses(course_id),
            FOREIGN KEY (uploaded_by) REFERENCES users(user_id)
        )
    ''')

    # Quizzes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quizzes (
            quiz_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            created_by TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            quiz_date TEXT NOT NULL,
            total_points INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id),
            FOREIGN KEY (created_by) REFERENCES users(user_id)
        )
    ''')

    # Quiz questions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_questions (
            question_id TEXT PRIMARY KEY,
            quiz_id TEXT NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_option TEXT NOT NULL,
            question_order INTEGER,
            FOREIGN KEY (quiz_id) REFERENCES quizzes(quiz_id)
        )
    ''')

    # Quiz attempts
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            attempt_id TEXT PRIMARY KEY,
            quiz_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            answers TEXT,
            score INTEGER,
            total INTEGER,
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'submitted' CHECK(status IN ('submitted', 'graded_zero')),
            FOREIGN KEY (quiz_id) REFERENCES quizzes(quiz_id),
            FOREIGN KEY (student_id) REFERENCES users(user_id)
        )
    ''')

    # Indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_enrollments_student ON enrollments(student_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_enrollments_course ON enrollments(course_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(student_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_course ON attendance(course_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_assignments_course ON assignments(course_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_questions_course ON questions(course_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_announcements_recipient ON announcements(recipient_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student ON quiz_attempts(student_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_quiz_attempts_quiz ON quiz_attempts(quiz_id)')

    conn.commit()
    conn.close()
    print("Database initialized successfully!")


if __name__ == '__main__':
    init_database()
    print("Run populate_demo_db.py next to add sample data.")
