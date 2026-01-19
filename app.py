import os
import math
import mysql.connector
import pandas as pd
from flask import Flask, render_template, request, jsonify, session, redirect

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')


# --- DATABASE CONFIGURATION ---
def get_db_connection():
    try:
        if 'DB_HOST' in os.environ:
            # Azure Settings
            conn = mysql.connector.connect(
                host=os.environ.get('DB_HOST'),
                user=os.environ.get('DB_USER'),
                password=os.environ.get('DB_PASS'),
                database=os.environ.get('DB_NAME'),
                port=3306,
                ssl_disabled=True
            )
        else:
            # Localhost Settings
            conn = mysql.connector.connect(
                host='localhost',
                port=3307,  # Check if your MySQL is on 3306 or 3307
                user='root',
                password='root',
                database='archive_db'
            )
        return conn
    except mysql.connector.Error as err:
        print(f"❌ DB Error: {err}")
        return None


# --- ROUTES ---
@app.route('/')
def index():
    is_admin = 'user' in session
    return render_template('index.html', is_admin=is_admin)


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    admin_pass = os.environ.get('ADMIN_PASS', 'admin')
    if data.get('username') == 'admin' and data.get('password') == admin_pass:
        session['user'] = 'admin'
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid Credentials'})


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')


# --- API ENDPOINTS ---

@app.route('/api/documents')
def get_documents():
    conn = get_db_connection()
    if not conn: return jsonify({'data': [], 'pagination': {}}), 500

    cursor = conn.cursor(dictionary=True)
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
            'current_page': page, 'total_pages': total_pages,
            'total_records': total_records, 'has_next': page < total_pages, 'has_prev': page > 1
        }
    })


@app.route('/search', methods=['GET'])
def search_agreement():
    query = request.args.get('q', '').strip()
    if not query: return jsonify(None)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    search_term = f"%{query}%"
    cursor.execute('SELECT * FROM agreements WHERE agreement_number LIKE %s LIMIT 1', (search_term,))

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

        target_sheet = None
        header_row = 0
        for sheet in xls.sheet_names:
            preview = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=10)
            for idx, row in preview.iterrows():
                if 'agreement' in str(row.values).lower():
                    target_sheet = sheet
                    header_row = idx
                    break
            if target_sheet: break

        if not target_sheet: return jsonify({'success': False, 'message': 'Header not found'})

        df = pd.read_excel(xls, sheet_name=target_sheet, header=header_row)
        cols = {str(c).strip().lower(): c for c in df.columns}
        ag_col = next((orig for clean, orig in cols.items() if 'agreement' in clean), None)
        cat_col = next((orig for clean, orig in cols.items() if 'categor' in clean), None)
        box_col = next((orig for clean, orig in cols.items() if 'box' in clean or 'doksl' in clean), None)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        count = 0

        for index, row in df.iterrows():
            ag_num = str(row.get(ag_col, '')).strip()
            cat = str(row.get(cat_col, '')).strip()
            raw_box = str(row.get(box_col, '')).strip() if box_col else ''

            final_type = "UNKNOWN"
            if raw_box and raw_box.lower() != 'nan':
                final_type = ''.join([c for c in raw_box if not c.isdigit()]).strip()
            if (not final_type or final_type == "UNKNOWN") and cat and cat.lower() != 'nan':
                final_type = cat[:3].upper()

            if ag_num and ag_num.lower() != 'nan':
                try:
                    cursor.execute('''
                                   INSERT
                                   IGNORE INTO agreements (agreement_number, category, box_type, status)
                        VALUES (
                                   %s,
                                   %s,
                                   %s,
                                   'Pending'
                                   )
                                   ''', (ag_num, cat, final_type))
                    count += 1
                except:
                    pass

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': f'Uploaded {count} records'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# --- MISSING FUNCTIONS ADDED BELOW ---

@app.route('/get_active_box', methods=['GET'])
def get_active_box():
    box_type = request.args.get('type')
    conn = get_db_connection()
    if not conn: return jsonify({'error': 'db_error'}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT * FROM active_boxes WHERE box_type = %s', (box_type,))
        box = cursor.fetchone()
        return jsonify(box) if box else jsonify({'error': 'not_found'})
    finally:
        cursor.close()
        conn.close()


@app.route('/create_new_box', methods=['POST'])
def create_new_box():
    data = request.json
    box_type = data['box_type']
    new_dok_id = data['new_dok_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute('SELECT current_sequence FROM active_boxes WHERE box_type = %s', (box_type,))
        current = cursor.fetchone()

        if current:
            new_seq = current['current_sequence'] + 1
            new_name = f"{box_type}{new_seq}"
            cursor.execute('''
                           UPDATE active_boxes
                           SET current_sequence = %s,
                               current_box_name = %s,
                               current_dok_id   = %s,
                               item_count       = 0
                           WHERE box_type = %s
                           ''', (new_seq, new_name, new_dok_id, box_type))
        else:
            new_name = f"{box_type}1"
            cursor.execute('''
                           INSERT INTO active_boxes (box_type, current_sequence, current_box_name, current_dok_id,
                                                     item_count)
                           VALUES (%s, 1, %s, %s, 0)
                           ''', (box_type, new_name, new_dok_id))

        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        cursor.close()
        conn.close()


@app.route('/assign_agreement', methods=['POST'])
def assign_agreement():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
                       UPDATE agreements
                       SET assigned_box_name = %s,
                           assigned_dok_id   = %s,
                           status            = 'Archived'
                       WHERE agreement_number = %s
                       ''', (data['box_name'], data['dok_id'], data['agreement_number']))

        cursor.execute('''
                       UPDATE active_boxes
                       SET item_count = item_count + 1
                       WHERE box_type = %s
                       ''', (data['box_type'],))

        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    app.run(debug=True, port=5000)