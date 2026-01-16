import os
import math
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
from flask import Flask, render_template, request, jsonify, session, redirect

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default-dev-key')

# --- DATABASE CONNECTION ---
def get_db_connection():
    try:
        # Vercel provides the DB URL via environment variable
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Error connecting to DB: {e}")
        return None

# --- ROUTES ---
@app.route('/')
def index():
    is_admin = 'user' in session
    return render_template('index.html', is_admin=is_admin)

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    # In Vercel, set ADMIN_PASS in environment variables for security
    admin_pass = os.environ.get('ADMIN_PASS', 'admin')
    if data.get('username') == 'admin' and data.get('password') == admin_pass:
        session['user'] = 'admin'
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid Credentials'})

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

# --- API & LOGIC ---
@app.route('/api/documents')
def get_documents():
    conn = get_db_connection()
    if not conn: return jsonify({'data': [], 'pagination': {}}), 500

    # Use RealDictCursor to get dictionary results (like MySQL dictionary=True)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page

    cursor.execute('SELECT * FROM agreements ORDER BY id DESC LIMIT %s OFFSET %s', (per_page, offset))
    data = cursor.fetchall()

    cursor.execute('SELECT COUNT(*) as total FROM agreements')
    result = cursor.fetchone()
    total_records = result['total'] if result else 0
    total_pages = math.ceil(total_records / per_page)

    cursor.close()
    conn.close()

    return jsonify({
        'data': data,
        'pagination': {
            'current_page': page,
            'total_pages': total_pages,
            'total_records': total_records,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    })

@app.route('/search', methods=['GET'])
def search_agreement():
    query = request.args.get('q', '').strip()
    if not query: return jsonify(None)

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Postgres uses ILIKE for case-insensitive search
    search_term = f"%{query}%"
    cursor.execute('SELECT * FROM agreements WHERE agreement_number ILIKE %s LIMIT 1', (search_term,))

    agreement = cursor.fetchone()
    cursor.close()
    conn.close()
    return jsonify(agreement) if agreement else jsonify(None)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'user' not in session: return jsonify({'success': False, 'message': 'Unauthorized'})
    if 'file' not in request.files: return jsonify({'success': False, 'message': 'No file'})

    file = request.files['file']
    if file.filename == '': return jsonify({'success': False, 'message': 'No file selected'})

    try:
        engine = 'pyxlsb' if file.filename.endswith('.xlsb') else 'openpyxl'
        xls = pd.ExcelFile(file, engine=engine)

        # ... (Keep your existing Excel sheet logic here to find 'target_sheet') ...
        # For brevity, assuming you implement the same logic as before to get 'df'

        # --- MOCK DATAFRAME LOADING FOR EXAMPLE ---
        # (Paste your previous Excel parsing logic here)
        # ------------------------------------------

        conn = get_db_connection()
        cursor = conn.cursor()

        # POSTGRES SPECIFIC INSERT
        # Postgres does not have "INSERT IGNORE". We use "ON CONFLICT DO NOTHING"
        for index, row in df.iterrows():
            # ... (Your logic to get ag_num, cat, final_type) ...

            cursor.execute('''
                INSERT INTO agreements (agreement_number, category, box_type, status)
                VALUES (%s, %s, %s, 'Pending')
                ON CONFLICT (agreement_number) DO NOTHING
            ''', (ag_num, cat, final_type))

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Upload complete'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ... (Keep create_new_box, get_active_box, assign_agreement logic) ...
# Just remember to switch cursor to: cursor = conn.cursor(cursor_factory=RealDictCursor)

if __name__ == '__main__':
    app.run(debug=True)