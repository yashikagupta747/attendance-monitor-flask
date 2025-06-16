import os
import sqlite3
import face_recognition
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.utils import secure_filename

from utils import preprocess_frame, detect_face

DB_PATH = "attendance.db"
DATASET_DIR = "dataset"
TEMP_DIR = "temp"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.config['UPLOAD_FOLDER'] = DATASET_DIR

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        user_id TEXT UNIQUE,
        registration_date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        date TEXT,
        day_of_week TEXT,
        in_time TEXT,
        out_time TEXT,
        duration TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    conn.commit()
    conn.close()

def ensure_dirs():
    os.makedirs(DATASET_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

def get_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, user_id, registration_date FROM users")
    users = c.fetchall()
    conn.close()
    return users

def add_user(name, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute("INSERT INTO users (name, user_id, registration_date) VALUES (?, ?, ?)",
                  (name, user_id, reg_date))
        conn.commit()
        return True, "User added."
    except sqlite3.IntegrityError:
        return False, "User ID already exists."
    finally:
        conn.close()

def delete_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM attendance WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    for fname in os.listdir(DATASET_DIR):
        if fname.startswith(str(user_id) + "_"):
            os.remove(os.path.join(DATASET_DIR, fname))

def load_known_faces():
    encodings = []
    user_ids = []
    for img_name in os.listdir(DATASET_DIR):
        if img_name.endswith('.jpg'):
            user_id = img_name.split('_')[0]
            img_path = os.path.join(DATASET_DIR, img_name)
            image = face_recognition.load_image_file(img_path)
            encoding = face_recognition.face_encodings(image)
            if encoding:
                encodings.append(encoding[0])
                user_ids.append(user_id)
    return encodings, user_ids

def log_attendance(user_id):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    day_of_week = now.strftime("%A")
    time_str = now.strftime("%H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT in_time, out_time FROM attendance WHERE user_id=? AND date=?", (user_id, date_str))
    result = c.fetchone()
    if not result or not result[0]:
        c.execute("INSERT OR REPLACE INTO attendance (user_id, date, day_of_week, in_time, out_time, duration) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, date_str, day_of_week, time_str, None, None))
        conn.commit()
        conn.close()
        return "IN", time_str
    elif result[0] and not result[1]:
        in_time = datetime.strptime(result[0], "%H:%M:%S")
        out_time = datetime.strptime(time_str, "%H:%M:%S")
        duration = str(out_time - in_time)
        c.execute("UPDATE attendance SET out_time=?, duration=? WHERE user_id=? AND date=?",
                  (time_str, duration, user_id, date_str))
        conn.commit()
        conn.close()
        return "OUT", time_str
    else:
        conn.close()
        return "ALREADY", result[1]

def get_attendance_logs():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT users.name, users.user_id, attendance.date, attendance.day_of_week, attendance.in_time, attendance.out_time, attendance.duration
                 FROM attendance JOIN users ON attendance.user_id = users.user_id
                 ORDER BY attendance.date DESC, attendance.in_time DESC''')
    logs = c.fetchall()
    conn.close()
    return logs

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    users = get_users()
    return render_template('dashboard.html', users=users)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'admin' and password == 'admin':
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/add_user', methods=['POST'])
def add_user_route():
    name = request.form.get('name')
    user_id = request.form.get('user_id')
    if name and user_id:
        success, msg = add_user(name, user_id)
        flash(msg)
    return redirect(url_for('index'))

@app.route('/delete_user/<user_id>', methods=['POST'])
def delete_user_route(user_id):
    delete_user(user_id)
    flash(f"User {user_id} deleted.")
    return redirect(url_for('index'))

@app.route('/register_face', methods=['GET', 'POST'])
def register_face():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        files = request.files.getlist('face_images')
        count = 0
        for file in files:
            if file and allowed_file(file.filename):
                filename = f"{user_id}_{count}.jpg"
                file.save(os.path.join(DATASET_DIR, filename))
                count += 1
                if count == 5:
                    break
        flash(f"Registered {count} face images for {user_id}.")
        return redirect(url_for('index'))
    users = get_users()
    return render_template('register_face.html', users=users)

@app.route('/mark_attendance')
def mark_attendance():
    return render_template('mark_attendance.html')

@app.route('/process_attendance', methods=['POST'])
def process_attendance():
    file = request.files.get('file')
    if not file or not allowed_file(file.filename):
        return jsonify({'status': 'error', 'message': 'No valid file uploaded.'})
    temp_path = os.path.join(TEMP_DIR, secure_filename(file.filename))
    file.save(temp_path)
    image = face_recognition.load_image_file(temp_path)
    face_locations = face_recognition.face_locations(image)
    face_encodings = face_recognition.face_encodings(image, face_locations)
    known_encodings, known_ids = load_known_faces()
    results = []
    for face_encoding in face_encodings:
        matches = face_recognition.compare_faces(known_encodings, face_encoding, tolerance=0.5)
        face_distances = face_recognition.face_distance(known_encodings, face_encoding)
        if len(face_distances) == 0:
            continue
        best_match_index = np.argmin(face_distances)
        if matches[best_match_index]:
            user_id = known_ids[best_match_index]
            status, time = log_attendance(user_id)
            results.append({'user_id': user_id, 'status': status, 'time': time})
    os.remove(temp_path)
    return jsonify({'status': 'success', 'results': results})

@app.route('/reports')
def reports():
    logs = get_attendance_logs()
    return render_template('reports.html', records=logs)

if __name__ == '__main__':
    ensure_dirs()
    init_db()
    app.run(debug=True)
