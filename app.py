import os
import sqlite3  # kept for legacy backup compatibility
import subprocess

import psycopg2
from psycopg2 import OperationalError as PostgreSQLOperationalError
from psycopg2.extras import DictCursor
import datetime
import random
import shutil
import sys
import time
import atexit
from io import BytesIO

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from flask import Flask, request, redirect, url_for, session, render_template_string, send_from_directory, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "imana_free_interest_microfinance_secret_key")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
BACKUP_FOLDER = os.path.join(BASE_DIR, 'backups')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['BACKUP_FOLDER'] = BACKUP_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

NOTIFICATIONS = []

def compress_and_save_image(file_storage, target_filename, max_size=(300, 300), quality=35):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], target_filename)
    filename = file_storage.filename.lower()
    
    if filename.endswith('.pdf') or not HAS_PIL:
        file_storage.save(filepath)
        return target_filename

    try:
        image = Image.open(file_storage)
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        image.save(filepath, "JPEG", optimize=True, quality=quality)
        return target_filename
    except Exception as e:
        print(f"Image compression error: {e}")
        file_storage.save(filepath)
        return target_filename

def _translate_sql_placeholders(sql):
    return sql.replace("?", "%s")

class CompatiblePostgresCursor(DictCursor):
    def execute(self, query, vars=None):
        return super().execute(_translate_sql_placeholders(query), vars)

    def executemany(self, query, vars_list):
        return super().executemany(_translate_sql_placeholders(query), vars_list)

def get_db_connection(max_retries=10, delay=0.5):
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                database_url,
                connect_timeout=15,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
                cursor_factory=CompatiblePostgresCursor,
            )
            return conn
        except PostgreSQLOperationalError as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise e

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_commission(amount):
    if 1000 <= amount <= 3000:
        return 50.0
    elif 3001 <= amount <= 5000:
        return 80.0
    elif 5001 <= amount <= 10000:
        return 100.0
    elif 10001 <= amount <= 20000:
        return 200.0
    elif 20001 <= amount <= 40000:
        return 400.0
    elif amount > 40001:
        return 500.0
    return 0.0

def add_notification(message):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    NOTIFICATIONS.insert(0, f"[{now}] {message}")
    if len(NOTIFICATIONS) > 20:
        NOTIFICATIONS.pop()

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE'
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ('ceo', 'ceo999', 'CEO', 'ACTIVE'),
            ('manager1', 'manager123', 'MANAGER', 'ACTIVE'),
            ('maker1', 'maker123', 'MAKER', 'ACTIVE'),
            ('auditor1', 'auditor123', 'AUDITOR', 'ACTIVE')
        ]
        cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", default_users)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            full_name TEXT,
            phone TEXT,
            gender TEXT DEFAULT 'Dhiira',
            account_type TEXT DEFAULT 'WADIA',
            photo_path TEXT,
            signature_path TEXT,
            national_id_path TEXT DEFAULT '',
            balance REAL DEFAULT 0.0,
            status TEXT DEFAULT 'PENDING_APPROVAL',
            freeze_status TEXT DEFAULT 'UNFROZEN',
            freeze_reason TEXT DEFAULT '',
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
            txn_type TEXT,
            customer_id TEXT,
            customer_name TEXT,
            target_account TEXT,
            amount REAL,
            commission REAL DEFAULT 0.0,
            bank_name TEXT,
            ft_reference TEXT,
            status TEXT DEFAULT 'PENDING_MANAGER',
            created_by TEXT,
            timestamp TEXT,
            audited_status TEXT DEFAULT 'OPEN'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reversals (
            reversal_id TEXT PRIMARY KEY,
            txn_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            manager_approved INTEGER DEFAULT 0,
            ceo_approved INTEGER DEFAULT 0,
            status TEXT DEFAULT 'PENDING_APPROVAL',
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# =========================================================================
#             ⚙️ MOBILE BANKING API ENDPOINTS (FOR CUSTOMERS)
# =========================================================================

# 1. MOBILE LOGIN (Maammilli lakk bilbilaa fi Acc ID'n kanaan seena)
@app.route('/api/mobile/login', methods=['POST'])
def mobile_login():
    data = request.json or {}
    customer_id = data.get('customer_id', '').strip()
    phone = data.get('phone', '').strip()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, phone, balance, freeze_status, status FROM customers WHERE customer_id = ? AND phone = ?", (customer_id, phone))
    cust = cursor.fetchone()
    conn.close()
    
    if cust:
        if cust['status'] != 'ACTIVE':
            return jsonify({'success': False, 'message': 'Akkaawuntiin keessan eeyyama manager eegaa jira!'})
        if cust['freeze_status'] == 'FROZEN':
            return jsonify({'success': False, 'message': 'Akkaawuntiin keessan uggurameera! CEO qunnamaa.'})
            
        return jsonify({
            'success': True,
            'message': 'Milkaa\'inaan seentaniittu',
            'customer': {
                'customer_id': cust['customer_id'],
                'full_name': cust['full_name'],
                'phone': cust['phone'],
                'balance': cust['balance']
            }
        })
    return jsonify({'success': False, 'message': 'Lakkoofsa Herregaa ykn Bilbilaa dogoggora!'})

# 2. HAFTEE FI STATEMENT ILAALUU (Balance & Statement View)
@app.route('/api/mobile/statement', methods=['POST'])
def mobile_statement():
    data = request.json or {}
    customer_id = data.get('customer_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance, freeze_status FROM customers WHERE customer_id = ?", (customer_id,))
    cust = cursor.fetchone()
    
    if not cust:
        conn.close()
        return jsonify({'success': False, 'message': 'Maammilli hin argamne'})
        
    cursor.execute("""
        SELECT txn_type, amount, ft_reference, status, timestamp 
        FROM transactions 
        WHERE (customer_id = ? OR target_account = ?) AND status = 'APPROVED'
        ORDER BY timestamp DESC LIMIT 10
    """, (customer_id, customer_id))
    txns = cursor.fetchall()
    conn.close()
    
    txn_list = []
    for t in txns:
        txn_list.append({
            'txn_type': t['txn_type'],
            'amount': t['amount'],
            'ft_reference': t['ft_reference'],
            'status': t['status'],
            'timestamp': t['timestamp']
        })
        
    return jsonify({
        'success': True,
        'balance': cust['balance'],
        'statement': txn_list
    })

# 3. QARSHII WALITTI ERGUU (Transfer - PENDING KAN HIN GAAFANNE)
@app.route('/api/mobile/transfer', methods=['POST'])
def mobile_transfer():
    data = request.json or {}
    sender_id = data.get('sender_id')
    receiver_id = data.get('receiver_id')
    amount = float(data.get('amount', 0.0))
    
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Hamma maallaqaa sirrii galchaa'})
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT full_name, balance, freeze_status, status FROM customers WHERE customer_id = ?", (sender_id,))
    sender = cursor.fetchone()
    cursor.execute("SELECT full_name, balance, freeze_status, status FROM customers WHERE customer_id = ?", (receiver_id,))
    receiver = cursor.fetchone()
    
    if not sender or sender['status'] != 'ACTIVE' or sender['freeze_status'] == 'FROZEN':
        conn.close()
        return jsonify({'success': False, 'message': 'Akkaawuntiin keessan hojii irra hin jiru ykn uggurameera.'})
    if not receiver or receiver['status'] != 'ACTIVE' or receiver['freeze_status'] == 'FROZEN':
        conn.close()
Use code with caution.return jsonify({'success': False, 'message': 'Akkaawuntiin qarshii itti ergitani argame hin jiru ykn uggurameera.'})if sender['balance'] < amount:conn.close()return jsonify({'success': False, 'message': 'Balansii gahaa hin qabdani!'})# Kutaa kaffaltii (Direct update - eeyyama dabalataa hin gaafatu)cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amount, sender_id))cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (amount, receiver_id))ft_ref = f"MOB-FT-{int(time.time())}"now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")txn_id = f"TXN-MOB-{random.randint(100000,999999)}"cursor.execute("""INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, amount, commission, bank_name, ft_reference, status, created_by, timestamp)VALUES (?, 'T24_TRANSFER', ?, ?, ?, ?, 0.0, 'Mobile App', ?, 'APPROVED', 'MOBILE_USER', ?)""", (txn_id, sender_id, sender['full_name'], receiver_id, amount, ft_ref, now))conn.commit()conn.close()return jsonify({'success': True, 'message': f'Qarshiin {amount} milkaa'inaan ergameera. Ref: {ft_ref}', 'ft_reference': ft_ref})4. QARSHII BAAFATA / AGENT (Withdraw via Mobile API)@app.route('/api/mobile/withdraw', methods=['POST'])def mobile_withdraw():data = request.json or {}customer_id = data.get('customer_id')amount = float(data.get('amount', 0.0))if amount <= 0:return jsonify({'success': False, 'message': 'Hamma maallaqaa sirrii galchaa'})conn = get_db_connection()cursor = conn.cursor()cursor.execute("SELECT full_name, balance, freeze_status, status FROM customers WHERE customer_id = ?", (customer_id,))cust = cursor.fetchone()if not cust or cust['status'] != 'ACTIVE' or cust['freeze_status'] == 'FROZEN':conn.close()return jsonify({'success': False, 'message': 'Akkaawuntiin hin jiru ykn uggurameera.'})commission = get_commission(amount)total_deduct = amount + commissionif cust['balance'] < total_deduct:conn.close()return jsonify({'success': False, 'message': f'Balansii gahaa miti! Barbaadamu: {total_deduct}'})cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (total_deduct, customer_id))ft_ref = f"MOB-WITH-{int(time.time())}"now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")txn_id = f"TXN-W-{random.randint(100000,999999)}"cursor.execute("""INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, amount, commission, bank_name, ft_reference, status, created_by, timestamp)VALUES (?, 'WITHDRAWAL', ?, ?, ?, ?, 'Mobile Agent', ?, 'APPROVED', 'MOBILE_USER', ?)""", (txn_id, customer_id, cust['full_name'], amount, commission, ft_ref, now))conn.commit()conn.close()return jsonify({'success': True, 'message': f'Baafanni {amount} Birr milkaa'eera. Comishiniin: {commission}', 'ft_reference': ft_ref})5. ETOPUP / CARD GUUTTACHUU (Airtime TopUp)@app.route('/api/mobile/etopup', methods=['POST'])def mobile_etopup():data = request.json or {}customer_id = data.get('customer_id')target_phone = data.get('target_phone')amount = float(data.get('amount', 0.0))if amount <= 0:return jsonify({'success': False, 'message': 'Hamma maallaqaa sirrii galchaa'})conn = get_db_connection()cursor = conn.cursor()cursor.execute("SELECT full_name, balance, freeze_status, status FROM customers WHERE customer_id = ?", (customer_id,))cust = cursor.fetchone()if not cust or cust['status'] != 'ACTIVE' or cust['freeze_status'] == 'FROZEN':conn.close()return jsonify({'success': False, 'message': 'Akkaawuntiin hin jiru ykn uggurameera.'})if cust['balance'] < amount:conn.close()return jsonify({'success': False, 'message': 'Balansii gahaa hin qabdani!'})cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amount, customer_id))ft_ref = f"MOB-TOP-{int(time.time())}"now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")txn_id = f"TXN-TP-{random.randint(100000,999999)}"cursor.execute("""INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, amount, commission, bank_name, ft_reference, status, created_by, timestamp)VALUES (?, 'ETOPUP', ?, ?, ?, ?, 0.0, 'EthioTelecom Mobile', ?, 'APPROVED', 'MOBILE_USER', ?)""", (txn_id, customer_id, cust['full_name'], target_phone, amount, ft_ref, now))conn.commit()conn.close()print(f"📱 [ETOPUP SUCCESS]: {amount} Birr card sent to {target_phone}")return jsonify({'success': True, 'message': f'Kardii {amount} Birr milkaa'inaan guuttataniittu lakkoofsa {target_phone} irratti.', 'ft_reference': ft_ref})=========================================================================🛠️ BACKEND REVERSAL SYSTEM (AUDITOR -> MANAGER -> CEO)=========================================================================6. REVERSALS MANAGER & CEO WEB VIEW & APPROVALS@app.route('/reversals_list')def reversals_list():if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:return "🚫 Hayyama Manager ykn CEO Qofa!", 403conn = get_db_connection()cursor = conn.cursor()cursor.execute("SELECT * FROM reversals ORDER BY timestamp DESC")revs = cursor.fetchall()conn.close()rows_html = ""for r in revs:actions = ""if session['role'] == 'MANAGER' and r['manager_approved'] == 0:actions = f'<a href="/approve_reversal/manager/{r["reversal_id"]}" class="btn-action btn-blue">✅ Manager Approve'elif session['role'] == 'CEO' and r['manager_approved'] == 1 and r['ceo_approved'] == 0:actions = f'<a href="/approve_reversal/ceo/{r["reversal_id"]}" class="btn-action btn-purple">✅ CEO Final Approve'rows_html += f"""Rev ID: {r['reversal_id']} | Txn ID: {r['txn_id']}Sababa Dogongoraa: {r['reason']}Auditor Gaafate: {r['requested_by']} | Status: {r['status']}{actions}"""return f"""🔄 Reversal Verification Portal (Manager & CEO)🏠 Gara Dashboard deebi'i{rows_html}"""@app.route('/approve_reversal/<role_type>/<rev_id>')def approve_reversal(role_type, rev_id):if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:return redirect('/login')conn = get_db_connection()cursor = conn.cursor()cursor.execute("SELECT * FROM reversals WHERE reversal_id = ?", (rev_id,))rev = cursor.fetchone()if rev:if role_type == 'manager' and session['role'] == 'MANAGER':cursor.execute("UPDATE reversals SET manager_approved = 1, status = 'PENDING_CEO' WHERE reversal_id = ?", (rev_id,))elif role_type == 'ceo' and session['role'] == 'CEO':cursor.execute("UPDATE reversals SET ceo_approved = 1, status = 'APPROVED' WHERE reversal_id = ?", (rev_id,))cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (rev['txn_id'],))t = cursor.fetchone()if t:# Reversal logic (Deebisii herrega sirreessi)if t['txn_type'] in ['WITHDRAWAL', 'ETOPUP']:cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (t['amount'] + t['commission'], t['customer_id']))elif t['txn_type'] == 'T24_TRANSFER':cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (t['amount'], t['customer_id']))cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (t['amount'], t['target_account']))cursor.execute("UPDATE transactions SET status = 'REVERSED' WHERE txn_id = ?", (t['txn_id'],))conn.commit()conn.close()return redirect('/reversals_list')KUDDEEN WEB PORTAL DURAANII@app.route('/login', methods=['GET', 'POST'])def login():if request.method == 'POST':username = request.form.get('username')password = request.form.get('password')conn = get_db_connection()cursor = conn.cursor()cursor.execute("SELECT username, role FROM users WHERE username = ? AND password = ?", (username, password))user = cursor.fetchone()conn.close()if user:session['username'] = user['username']session['role'] = user['role']return redirect('/')return '''Backend Staff LoginUsername: Password: Login'''@app.route('/')def dashboard():if 'role' not in session: return redirect('/login')return f"""🏦 Welcome Dashboard ({session['role']})🔄 View Reversal Requests (Manager/CEO)Logout"""@app.route('/logout')def logout():session.clear()return redirect('/login')if name == 'main':app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
