import os
import datetime
import random
import shutil
import time
import atexit
from io import BytesIO

import psycopg2
from psycopg2 import OperationalError as PostgreSQLOperationalError
from psycopg2.extras import DictCursor

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, send_from_directory, jsonify, send_file
)
from werkzeug.utils import secure_filename

# ================================================================
# APP CONFIG
# ================================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "imana_free_interest_microfinance_secret_key_2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
BACKUP_FOLDER = os.path.join(BASE_DIR, 'backups')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['BACKUP_FOLDER'] = BACKUP_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

NOTIFICATIONS = []

ETHIOPIAN_BANKS = [
    "Commercial Bank of Ethiopia (CBE)", "Cooperative Bank of Oromia (CBO)",
    "Awash Bank", "Dashen Bank", "Bank of Abyssinia", "Hibret Bank",
    "Nib International Bank", "United Bank", "Zemen Bank", "Wegagen Bank",
    "Oromia Bank", "Amhara Bank", "Global Bank Ethiopia",
    "Hijra Bank (Islamic)", "ZamZam Bank (Islamic)", "Siinqee Bank", "Gadaa Bank"
]

# ================================================================
# HELPERS
# ================================================================
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
            return psycopg2.connect(
                database_url, connect_timeout=15,
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
                cursor_factory=CompatiblePostgresCursor,
            )
        except PostgreSQLOperationalError as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise e


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_commission(amount):
    if 1000 <= amount <= 3000: return 50.0
    if 3001 <= amount <= 5000: return 80.0
    if 5001 <= amount <= 10000: return 100.0
    if 10001 <= amount <= 20000: return 200.0
    if 20001 <= amount <= 40000: return 400.0
    if amount > 40001: return 500.0
    return 0.0


def add_notification(message):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    NOTIFICATIONS.insert(0, f"[{now}] {message}")
    if len(NOTIFICATIONS) > 20:
        NOTIFICATIONS.pop()


# ================================================================
# DB INIT
# ================================================================
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password TEXT NOT NULL,
            role TEXT NOT NULL, status TEXT DEFAULT 'ACTIVE'
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", [
            ('ceo', 'ceo999', 'CEO', 'ACTIVE'),
            ('manager1', 'manager123', 'MANAGER', 'ACTIVE'),
            ('maker1', 'maker123', 'MAKER', 'ACTIVE'),
            ('auditor1', 'auditor123', 'AUDITOR', 'ACTIVE'),
            ('officer1', 'officer123', 'LOAN_OFFICER', 'ACTIVE'),
            ('ext_agent1', 'agent123', 'EXTERNAL_AGENT', 'ACTIVE'),
        ])

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY, full_name TEXT, phone TEXT,
            gender TEXT DEFAULT 'Dhiira', account_type TEXT DEFAULT 'WADIA',
            photo_path TEXT, signature_path TEXT, national_id_path TEXT DEFAULT '',
            balance REAL DEFAULT 0.0, status TEXT DEFAULT 'PENDING_APPROVAL',
            freeze_status TEXT DEFAULT 'UNFROZEN', freeze_reason TEXT DEFAULT '',
            mobile_pin TEXT DEFAULT '1234', mobile_status TEXT DEFAULT 'INACTIVE',
            pending_pin_reset TEXT DEFAULT '', created_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY, txn_type TEXT, customer_id TEXT,
            customer_name TEXT, target_account TEXT, amount REAL,
            commission REAL DEFAULT 0.0, bank_name TEXT, ft_reference TEXT,
            status TEXT DEFAULT 'PENDING_MANAGER', created_by TEXT,
            timestamp TEXT, audited_status TEXT DEFAULT 'OPEN', reason TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reversals (
            reversal_id TEXT PRIMARY KEY, txn_id TEXT NOT NULL,
            reason TEXT NOT NULL, requested_by TEXT NOT NULL,
            manager_approved INTEGER DEFAULT 0, ceo_approved INTEGER DEFAULT 0,
            status TEXT DEFAULT 'PENDING_APPROVAL', timestamp TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS islamic_financing (
            loan_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, customer_name TEXT,
            financing_type TEXT NOT NULL, principal_amount REAL NOT NULL,
            profit_margin REAL DEFAULT 0.0, total_repayment REAL NOT NULL,
            tenure_months INTEGER, monthly_installment REAL,
            status TEXT DEFAULT 'PENDING_MANAGER', manager_approved INTEGER DEFAULT 0,
            ceo_approved INTEGER DEFAULT 0, agent_notes TEXT, created_by TEXT, timestamp TEXT
        )
    """)

    for stmt in [
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reason TEXT DEFAULT ''",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS mobile_pin TEXT DEFAULT '1234'",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS mobile_status TEXT DEFAULT 'INACTIVE'",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS pending_pin_reset TEXT DEFAULT ''",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS national_id_path TEXT DEFAULT ''",
    ]:
        cursor.execute(stmt)

    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"⚠️ [DB INIT WARNING]: {e}")


def get_bank_capital():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE status='APPROVED' AND txn_type IN ('DEPOSIT','MOBILE_TOPUP_REC')")
    total_deposit = cursor.fetchone()[0] or 0.0
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE status='APPROVED' AND txn_type IN ('WITHDRAWAL','T24_TRANSFER','RTGS_TRANSFER','WALLET_TOPUP','AIRTIME_TOPUP')")
    total_withdraw = cursor.fetchone()[0] or 0.0
    cursor.execute("SELECT SUM(balance) FROM customers WHERE status='ACTIVE'")
    total_cust_balance = cursor.fetchone()[0] or 0.0
    cursor.execute("SELECT SUM(commission) FROM transactions WHERE status='APPROVED'")
    total_commission = cursor.fetchone()[0] or 0.0
    cursor.execute("SELECT SUM(balance) FROM customers WHERE status='ACTIVE' AND account_type='MUDARABA'")
    total_mudaraba = cursor.fetchone()[0] or 0.0
    mud_gross = total_mudaraba * 0.10
    net_capital = total_deposit - total_withdraw + total_commission
    conn.close()
    return (max(0.0, net_capital), total_deposit, total_withdraw, total_cust_balance,
            total_commission, total_mudaraba, mud_gross, mud_gross * 0.50, mud_gross * 0.50)


# ================================================================
# HTML LAYOUT
# ================================================================
HTML_LAYOUT = """
<!DOCTYPE html>
<html lang="om">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Imana Free Interest Microfinance</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background-color: #f1f5f9; padding-bottom: 80px; color: #0f172a; }
        nav { background: linear-gradient(135deg, #065f46, #047857); color: white; padding: 12px 16px; position: sticky; top: 0; z-index: 50; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        .logo-container { display: flex; align-items: center; gap: 10px; }
        .logo-svg { width: 32px; height: 32px; fill: #fbbf24; }
        nav h1 { font-size: 15px; font-weight: 800; }
        .role-badge { background: #0284c7; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }
        .container { max-width: 600px; margin: 0 auto; padding: 16px; }
        .notification-bar { background: #fef3c7; color: #92400e; padding: 8px 12px; border-radius: 8px; font-size: 11px; margin-bottom: 12px; font-weight: bold; border: 1px solid #fde68a; }
        .card-net { background: linear-gradient(135deg, #064e3b, #047857); color: white; border-radius: 16px; padding: 20px; box-shadow: 0 10px 15px -3px rgba(6,78,59,0.3); margin-bottom: 20px; }
        .card-ceo-profit { background: linear-gradient(135deg, #4c1d95, #6b21a8); color: white; border-radius: 16px; padding: 20px; box-shadow: 0 10px 15px -3px rgba(76,29,149,0.3); margin-bottom: 20px; }
        .card-mobile-header { background: linear-gradient(135deg, #1e3a8a, #2563eb); color: white; border-radius: 16px; padding: 20px; box-shadow: 0 10px 15px -3px rgba(37,99,235,0.3); margin-bottom: 20px; }
        .net-title { font-size: 12px; opacity: 0.9; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
        .net-amount { font-size: 30px; font-weight: 800; color: #fbbf24; }
        .net-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; border-top: 1px solid rgba(255,255,255,0.2); font-size: 12px; padding-top: 12px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .btn-card { background: white; padding: 16px; border-radius: 12px; border: 1px solid #e2e8f0; display: flex; flex-direction: column; align-items: center; text-decoration: none; color: #334155; font-weight: bold; font-size: 13px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .btn-card span.icon { font-size: 26px; margin-bottom: 8px; }
        .btn-card-ceo { background: #faf5ff; border-color: #e9d5ff; color: #581c87; }
        .btn-card-auditor { background: #fff7ed; border-color: #ffedd5; color: #c2410c; }
        .btn-card-mobile { background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8; }
        .btn-card-loan { background: #f0fdf4; border-color: #bbf7d0; color: #15803d; }
        .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; background: white; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-around; padding: 10px 0; z-index: 50; }
        .bottom-nav a { text-align: center; color: #64748b; text-decoration: none; font-size: 11px; flex: 1; font-weight: 500; }
        .bottom-nav a span.icon { display: block; font-size: 18px; margin-bottom: 2px; }
        .box { background: white; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 16px; }
        .form-group { margin-bottom: 12px; position: relative; }
        .form-group label { display: block; font-size: 12px; font-weight: bold; color: #475569; margin-bottom: 4px; }
        .input-field { width: 100%; padding: 11px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; outline: none; }
        .btn-submit { width: 100%; background: #047857; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: bold; font-size: 14px; cursor: pointer; }
        .badge { padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; display: inline-block; }
        .badge-pending { background: #fef3c7; color: #92400e; }
        .badge-active { background: #dcfce7; color: #166534; }
        .badge-danger { background: #fee2e2; color: #991b1b; }
        .badge-frozen { background: #dbeafe; color: #1e40af; }
        .item-card { background: white; border-radius: 12px; padding: 14px; margin-bottom: 12px; border: 1px solid #e2e8f0; }
        .img-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin: 10px 0; }
        .img-grid img { width: 100%; height: 60px; object-fit: cover; border-radius: 6px; border: 1px solid #e2e8f0; }
        .btn-action { padding: 8px 14px; border-radius: 6px; color: white; text-decoration: none; font-size: 12px; font-weight: bold; display: inline-block; border:none; cursor:pointer; }
        .btn-blue { background: #2563eb; }
        .btn-green { background: #16a34a; }
        .btn-red { background: #dc2626; }
        .btn-purple { background: #7c3aed; }
        .btn-orange { background: #ea580c; }
        .pwd-toggle { position: absolute; right: 10px; top: 32px; cursor: pointer; user-select: none; font-size: 14px; }
        @media print { .bottom-nav, nav, .no-print { display: none !important; } body { padding-bottom: 0; background: white; } }
    </style>
</head>
<body>
    <nav class="no-print">
        <div class="logo-container">
            <svg class="logo-svg" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            <h1>Imana Free Interest Microfinance</h1>
        </div>
        {% if session.get('role') %}
            <div style="font-size:12px;">
                <b>{{ session['username'] }}</b> <span class="role-badge">{{ session['role'] }}</span>
                <a href="/change_password" style="color:#fde047; margin-left:8px; text-decoration:none;">🔑</a>
                <a href="/logout" style="color:#fca5a5; margin-left:8px; text-decoration:none;">Logout</a>
            </div>
        {% elif session.get('mobile_cust_id') %}
            <div style="font-size:12px;">
                📱 <b>{{ session['mobile_name'] }}</b>
                <a href="/mobile_change_pin" style="color:#fde047; margin-left:8px; text-decoration:none;">🔑</a>
                <a href="/mobile_logout" style="color:#fca5a5; margin-left:8px; text-decoration:none;">Logout</a>
            </div>
        {% else %}
            <a href="/mobile_login" style="color:#fbbf24; font-size:12px; font-weight:bold; text-decoration:none;">📱 Mobile Banking</a>
        {% endif %}
    </nav>

    <div class="container">
        {% if notifications %}<div class="notification-bar no-print">🔔 {{ notifications[0] }}</div>{% endif %}
        {% block content %}{% endblock %}
    </div>

    {% if session.get('role') %}
    <div class="bottom-nav no-print">
        <a href="/"><span class="icon">🏠</span>Dashboard</a>
        {% if session['role'] == 'MAKER' %}
            <a href="/register"><span class="icon">👤</span>Galmee</a>
            <a href="/transaction"><span class="icon">💸</span>Kaffaltii</a>
            <a href="/maker_receipts"><span class="icon">🧾</span>Nagahee</a>
        {% elif session['role'] == 'EXTERNAL_AGENT' %}
            <a href="/agent_register"><span class="icon">👤</span>Agent Galmee</a>
            <a href="/agent_transaction"><span class="icon">💸</span>Agent Txn</a>
        {% elif session['role'] == 'MANAGER' %}
            <a href="/pending"><span class="icon">📋</span>Approvals</a>
            <a href="/reversals_list"><span class="icon">🔄</span>Reversals</a>
            <a href="/print_receipt_search"><span class="icon">🖨️</span>Nagahee</a>
        {% elif session['role'] == 'AUDITOR' %}
            <a href="/pending"><span class="icon">📋</span>View</a>
            <a href="/auditor_reversal_request"><span class="icon">⚠️</span>Reversal</a>
            <a href="/auditor_eod"><span class="icon">📊</span>EOD</a>
        {% elif session['role'] == 'CEO' %}
            <a href="/ceo_commission"><span class="icon">💰</span>Commission</a>
            <a href="/reversals_list"><span class="icon">🔄</span>Reversals</a>
            <a href="/manage_users"><span class="icon">⚙️</span>Hojjattoota</a>
        {% endif %}
    </div>
    {% elif session.get('mobile_cust_id') %}
    <div class="bottom-nav no-print">
        <a href="/mobile_dashboard"><span class="icon">📱</span>Dasshbordii</a>
        <a href="/mobile_transfer"><span class="icon">🔄</span>Transfer</a>
        <a href="/mobile_rtgs"><span class="icon">🏛️</span>RTGS</a>
        <a href="/mobile_topup"><span class="icon">⚡</span>Topup</a>
        <a href="/mobile_statement"><span class="icon">📜</span>Statement</a>
    </div>
    {% endif %}

    <script>
    function togglePasswordVisibility(inputId, toggleIconId) {
        var input = document.getElementById(inputId);
        var icon = document.getElementById(toggleIconId);
        if (input.type === "password") { input.type = "text"; icon.textContent = "🙈"; }
        else { input.type = "password"; icon.textContent = "👁️"; }
    }

    function playAlertSound() {
        try {
            var AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return;
            var ctx = new AC();
            if (ctx.state === 'suspended') ctx.resume();
            var now = ctx.currentTime;
            [660, 880, 1320].forEach(function(freq, i) {
                var osc = ctx.createOscillator(), gain = ctx.createGain();
                osc.connect(gain); gain.connect(ctx.destination);
                osc.type = 'sine'; osc.frequency.value = freq;
                var start = now + i * 0.18;
                gain.gain.setValueAtTime(0.0001, start);
                gain.gain.exponentialRampToValueAtTime(0.35, start + 0.02);
                gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.16);
                osc.start(start); osc.stop(start + 0.17);
            });
        } catch (e) { console.log('Audio not available', e); }
    }
    </script>
</body>
</html>
"""


# ================================================================
# STATIC / API
# ================================================================
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/get_customer/<cust_id>')
def api_get_customer(cust_id):
    if 'role' not in session and 'mobile_cust_id' not in session:
        return jsonify({'error': 'Unauthorized', 'success': False}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT customer_id, full_name, phone, photo_path, signature_path, national_id_path, "
        "freeze_status, freeze_reason, balance FROM customers WHERE customer_id = ?", (cust_id,)
    )
    cust = cursor.fetchone()
    conn.close()

    if cust:
        return jsonify({
            'success': True,
            'customer_id': cust['customer_id'],
            'full_name': cust['full_name'],
            'phone': cust['phone'],
            'photo_path': cust['photo_path'],
            'signature_path': cust['signature_path'],
            'national_id_path': cust.get('national_id_path', ''),
            'freeze_status': cust['freeze_status'],
            'freeze_reason': cust['freeze_reason'],
            'balance': cust['balance']
        })
    return jsonify({'success': False, 'message': 'Maammilli hin argamne'})


@app.route('/api/get_txn/<txn_id>')
def api_get_txn(txn_id):
    if 'role' not in session:
        return jsonify({'success': False}), 401
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE txn_id = ? OR ft_reference = ?", (txn_id, txn_id))
    t = cursor.fetchone()
    conn.close()
    if t:
        return jsonify({'success': True, 'txn_id': t['txn_id'], 'ft_reference': t['ft_reference'],
                        'customer_name': t['customer_name'], 'amount': t['amount'], 'txn_type': t['txn_type']})
    return jsonify({'success': False})


@app.route('/api/check_new_transactions')
def api_check_new_transactions():
    if 'mobile_cust_id' not in session:
        return jsonify({'success': False}), 401
    since = request.args.get('since', '').strip() or '1970-01-01 00:00:00'
    cust_id = session['mobile_cust_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM transactions WHERE customer_id = ? "
        "AND txn_type = 'MOBILE_TOPUP_REC' AND status = 'APPROVED' AND timestamp > ?",
        (cust_id, since)
    )
    count = cursor.fetchone()[0] or 0
    conn.close()
    return jsonify({
        'success': True,
        'new_count': count,
        'server_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


# ================================================================
# AUTH
# ================================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, role, status FROM users WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()
        if user:
            if user['status'] == 'BLOCKED':
                error = "🚫 Akkaawunttii keessan UGGURAMEERA!"
            else:
                session.clear()
                session['username'] = user['username']
                session['role'] = user['role']
                return redirect('/')
        else:
            error = "Username ykn Password dogoggoraa!"

    err_html = f"<p style='color:red; font-size:12px; text-align:center; margin-bottom:12px;'>{error}</p>" if error else ""
    content = f"""
    <div class="box" style="margin-top:30px; text-align:center;">
        <div style="font-size:40px; margin-bottom:10px;">🏦</div>
        <h2 style="font-size:17px; color:#065f46;">Imana Free Interest Microfinance</h2>
        <p style="font-size:12px; color:#64748b; margin-bottom:16px;">Seensa Systema</p>
        {err_html}
        <form method="POST">
            <div class="form-group" style="text-align:left;">
                <label>Username</label>
                <input type="text" name="username" placeholder="ceo, manager1, maker1..." class="input-field" required>
            </div>
            <div class="form-group" style="text-align:left;">
                <label>Password</label>
                <input type="password" id="login_password" name="password" class="input-field" required>
                <span id="login_pwd_toggle" class="pwd-toggle" onclick="togglePasswordVisibility('login_password','login_pwd_toggle')">👁️</span>
            </div>
            <button type="submit" class="btn-submit">Seeni</button>
        </form>
        <div style="margin-top:20px; border-top:1px solid #e2e8f0; padding-top:15px;">
            <a href="/mobile_login" style="color:#2563eb; font-weight:bold; font-size:13px; text-decoration:none;">📲 Seensa Mobile Banking Maammilaa</a>
        </div>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'role' not in session:
        return redirect('/login')
    msg, msg_type = None, "green"
    if request.method == 'POST':
        old_pwd = request.form.get('old_password', '').strip()
        new_pwd = request.form.get('new_password', '').strip()
        confirm_pwd = request.form.get('confirm_password', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE username = ?", (session['username'],))
        user = cursor.fetchone()
        if not user or user['password'] != old_pwd:
            msg, msg_type = "❌ Password duraanii dogoggoraa!", "red"
        elif new_pwd != confirm_pwd:
            msg, msg_type = "❌ Password haaraa fi Mirkaneessaan wal hin simne!", "red"
        elif len(new_pwd) < 4:
            msg, msg_type = "❌ Minimum 4 characters!", "red"
        else:
            cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_pwd, session['username']))
            conn.commit()
            msg = "✅ Password jijjiirameera!"
        conn.close()

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46; margin-bottom:12px;">🔑 Password Jijjiiri</h2>
        {f"<p style='background:{'#dcfce7' if msg_type=='green' else '#fee2e2'}; color:{'#166534' if msg_type=='green' else '#991b1b'}; padding:10px; border-radius:6px; font-size:12px; margin-bottom:12px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group"><label>Password Duraanii</label><input type="password" name="old_password" required class="input-field"></div>
            <div class="form-group"><label>Password Haaraa</label><input type="password" name="new_password" required class="input-field"></div>
            <div class="form-group"><label>Mirkaneessi</label><input type="password" name="confirm_password" required class="input-field"></div>
            <button type="submit" class="btn-submit">💾 Jijjiiri</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# DASHBOARD
# ================================================================
@app.route('/')
def dashboard():
    if 'role' not in session:
        return redirect('/login')

    net_cap, deposits, withdraws, cust_bal, total_comm, mud_dep, mud_gross, mud_ceo, mud_cust = get_bank_capital()
    role = session['role']

    maker_btns = """
        <a href="/register" class="btn-card"><span class="icon">👤</span><span>Galmee Maammilaa</span></a>
        <a href="/transaction" class="btn-card"><span class="icon">💸</span><span>Deposit / Transfer / Withdraw</span></a>
        <a href="/maker_receipts" class="btn-card"><span class="icon">🧾</span><span>Nagahee</span></a>
    """ if role == 'MAKER' else ""

    agent_btns = """
        <a href="/agent_register" class="btn-card btn-card-ceo"><span class="icon">👤</span><span>Agent Maammila Uumi</span></a>
        <a href="/agent_transaction" class="btn-card btn-card-ceo"><span class="icon">💸</span><span>Agent Txn (10% Comm)</span></a>
    """ if role == 'EXTERNAL_AGENT' else ""

    manager_btns = """
        <a href="/pending" class="btn-card"><span class="icon">🔍</span><span>Approvals</span></a>
        <a href="/reversals_list" class="btn-card"><span class="icon">🔄</span><span>Reversals</span></a>
        <a href="/print_receipt_search" class="btn-card"><span class="icon">🖨️</span><span>Nagahee Barbaadi</span></a>
    """ if role == 'MANAGER' else ""

    auditor_btns = """
        <a href="/pending" class="btn-card btn-card-auditor"><span class="icon">📋</span><span>View Approvals</span></a>
        <a href="/auditor_reversal_request" class="btn-card btn-card-auditor"><span class="icon">⚠️</span><span>Reversal Gaafachu</span></a>
        <a href="/auditor_eod" class="btn-card btn-card-auditor"><span class="icon">📊</span><span>EOD Cufiinsa</span></a>
    """ if role == 'AUDITOR' else ""

    loan_btn = """
        <a href="/islamic_loan" class="btn-card btn-card-loan"><span class="icon">📜</span><span>Mudaraba & Murabaha</span></a>
    """ if role in ['LOAN_OFFICER', 'CEO', 'MANAGER'] else ""

    ceo_btns = """
        <a href="/ceo_commission" class="btn-card btn-card-ceo"><span class="icon">💰</span><span>Commission Filter</span></a>
        <a href="/ceo_mudaraba_list" class="btn-card btn-card-ceo"><span class="icon">🤝</span><span>Mudaraba List</span></a>
        <a href="/reversals_list" class="btn-card btn-card-ceo"><span class="icon">🔄</span><span>Reversals</span></a>
        <a href="/manage_users" class="btn-card btn-card-ceo"><span class="icon">⚙️</span><span>Hojjattoota</span></a>
    """ if role == 'CEO' else ""

    ceo_header = f"""
        <div class="card-ceo-profit">
            <div class="net-title">📊 CEO Private: Mudaraba 50/50</div>
            <div class="net-amount">{mud_ceo:,.2f} Birr</div>
            <div class="net-grid">
                <div>📈 Kuusaa Mudaraba: <b>{mud_dep:,.2f}</b></div>
                <div>🤝 Qooda Maammiltootaa: <b>{mud_cust:,.2f}</b></div>
            </div>
        </div>
        <div class="card-net">
            <div class="net-title">Waliigala Kaabitaala Baankii</div>
            <div class="net-amount">{net_cap:,.2f} Birr</div>
            <div class="net-grid">
                <div>📥 Deposit: <b>{deposits:,.2f}</b></div>
                <div>📤 Withdraw/FT/RTGS: <b>{withdraws:,.2f}</b></div>
            </div>
        </div>
    """ if role == 'CEO' else ""

    content = f"""
    {ceo_header}
    <h3 style="font-size:14px; margin-bottom:12px; color:#475569;">Menu Hojii ({role})</h3>
    <div class="grid-2">
        {maker_btns}{agent_btns}{manager_btns}{auditor_btns}{loan_btn}
        <a href="/customers" class="btn-card"><span class="icon">👥</span><span>Listii Maammiltootaa</span></a>
        {ceo_btns}
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# CUSTOMER REGISTRATION
# ================================================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'role' not in session or session['role'] not in ['MAKER', 'MANAGER', 'CEO']:
        return "🚫 Hayyama Hin Qabdan!", 403

    msg = None
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        gender = request.form.get('gender', 'Dhiira')
        account_type = request.form.get('account_type', 'WADIA')
        enable_mobile = request.form.get('enable_mobile')
        initial_balance = max(0.0, float(request.form.get('initial_balance', 0.0)))
        photo_file = request.files.get('photo')
        sig_file = request.files.get('signature')
        natid_file = request.files.get('national_id')

        if not (photo_file and sig_file and allowed_file(photo_file.filename) and allowed_file(sig_file.filename)):
            msg = "❌ Suuraa fi mallattoo galchuun barbaachisa!"
        else:
            ts = int(datetime.datetime.now().timestamp())
            photo_name = compress_and_save_image(photo_file, f"face_{ts}_" + secure_filename(photo_file.filename))
            sig_name = compress_and_save_image(sig_file, f"sig_{ts}_" + secure_filename(sig_file.filename))
            natid_name = ""
            if natid_file and natid_file.filename and allowed_file(natid_file.filename):
                natid_name = compress_and_save_image(natid_file, f"nat_{ts}_" + secure_filename(natid_file.filename))

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(CAST(customer_id AS BIGINT)) FROM customers WHERE customer_id >= '100099008800'")
            max_id = cursor.fetchone()[0]
            START_ID = 100099008800
            cust_id = str(START_ID) if max_id is None or max_id < START_ID else str(max_id + 1)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mob_status = 'PENDING_APPROVAL' if enable_mobile else 'INACTIVE'

            cursor.execute("""
                INSERT INTO customers (customer_id, full_name, phone, gender, account_type,
                    photo_path, signature_path, national_id_path, balance, status,
                    mobile_pin, mobile_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'PENDING_APPROVAL', '1234', ?, ?)
            """, (cust_id, full_name, phone, gender, account_type, photo_name, sig_name, natid_name, mob_status, now))

            if initial_balance > 0:
                ft_ref = f"INIT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
                txn_id = f"TXN-INIT-{ts}-{random.randint(1000, 9999)}"
                cursor.execute("""
                    INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name,
                        amount, commission, bank_name, ft_reference, status, created_by, timestamp)
                    VALUES (?, 'DEPOSIT', ?, ?, ?, 0.0, 'Imana Core Bank', ?, 'PENDING_MANAGER', ?, ?)
                """, (txn_id, cust_id, full_name, initial_balance, ft_ref, session['username'], now))

            conn.commit()
            conn.close()
            msg = f"✅ {full_name} galmaa'eera! (Acc: {cust_id}, Mobile: {mob_status}). Manager approval eegaa jira."
            add_notification(f"Maammilli haaraan ({full_name}) galmaa'eera.")

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46; margin-bottom:12px;">👤 Galmee Maammila Haaraa</h2>
        {f"<p style='background:#dcfce7; color:#166534; padding:10px; border-radius:6px; font-size:12px; margin-bottom:12px;'>{msg}</p>" if msg else ""}
        <form method="POST" enctype="multipart/form-data">
            <div class="form-group"><label>Maqaa Guutuu</label><input type="text" name="full_name" required class="input-field"></div>
            <div class="form-group"><label>Lakkoofsa Bilbilaa</label><input type="text" name="phone" required class="input-field"></div>
            <div class="form-group"><label>Saala</label><select name="gender" class="input-field"><option>Dhiira</option><option>Dubartii</option></select></div>
            <div class="form-group"><label>Gosa Akkaawuntii</label>
                <select name="account_type" class="input-field">
                    <option value="WADIA">Wadia Savings</option>
                    <option value="MUDARABA">Mudaraba (50/50)</option>
                </select>
            </div>
            <div class="form-group" style="background:#eff6ff; padding:12px; border-radius:8px;">
                <label><input type="checkbox" name="enable_mobile" value="1" checked> 📲 Mobile Banking Request</label>
                <p style="font-size:11px; color:#64748b;">PIN: 1234 — Manager approval booda hojjeta</p>
            </div>
            <div class="form-group"><label>Balansii Jalqabaa (Birr)</label><input type="number" step="0.01" min="0" name="initial_balance" value="0.00" required class="input-field"></div>
            <div class="form-group"><label>📸 Suuraa Fuula</label><input type="file" name="photo" accept="image/*" required class="input-field"></div>
            <div class="form-group"><label>✍️ Mallattoo</label><input type="file" name="signature" accept="image/*" required class="input-field"></div>
            <div class="form-group"><label>🪪 National ID (Optional)</label><input type="file" name="national_id" accept="image/*,pdf" class="input-field"></div>
            <button type="submit" class="btn-submit">💾 Galmeessi</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# MAKER TRANSACTION — FIXED LINE 869 (double braces in JS)
# ================================================================
@app.route('/transaction', methods=['GET', 'POST'])
def transaction():
    if 'role' not in session or session['role'] != 'MAKER':
        return "🚫 Shoora MAKER qofatu transaction raawwachuu danda'a", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, balance, freeze_status FROM customers WHERE status='ACTIVE'")
    customers = cursor.fetchall()

    msg, msg_type = None, "green"
    created_txn_id = None

    if request.method == 'POST':
        txn_type = request.form.get('txn_type')
        cust_id = request.form.get('customer_id', '').strip()
        target_acc = request.form.get('target_account', '').strip()
        amount = float(request.form.get('amount', 0.0))
        confirm_amount = float(request.form.get('confirm_amount', 0.0))
        bank_name = request.form.get('bank_name', 'Imana Microfinance Core')
        reason = request.form.get('reason', '').strip()

        cursor.execute("SELECT full_name, balance, freeze_status FROM customers WHERE customer_id = ?", (cust_id,))
        cust = cursor.fetchone()

        if amount != confirm_amount:
            msg, msg_type = "❌ Hammi maallaqaa galchitan wal hin simne!", "red"
        elif not cust:
            msg, msg_type = "❌ Maammilli hin argamne!", "red"
        elif cust['freeze_status'] == 'FROZEN' and txn_type in ['WITHDRAWAL', 'T24_TRANSFER']:
            msg, msg_type = "🔒 Akkaawuntiin UGGURAMEERA!", "red"
        elif amount <= 0:
            msg, msg_type = "❌ Hamma sirrii galchaa!", "red"
        else:
            commission = 0.0
            if txn_type == 'WITHDRAWAL':
                commission = get_commission(amount)
            elif txn_type == 'T24_TRANSFER':
                commission = round(amount * 0.02, 2)

            total_req = amount + commission
            if txn_type in ['WITHDRAWAL', 'T24_TRANSFER'] and cust['balance'] < total_req:
                msg, msg_type = f"❌ Balansii gahaa miti! Jiru: {cust['balance']:,.2f}, Barbaadamu: {total_req:,.2f}", "red"
            else:
                ts = int(datetime.datetime.now().timestamp())
                prefix = {'DEPOSIT': 'TT', 'WITHDRAWAL': 'WITH', 'T24_TRANSFER': 'FT'}.get(txn_type, 'TXN')
                ft_ref = f"{prefix}{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                txn_id = f"TXN-{ts}-{random.randint(1000, 9999)}"
                created_txn_id = txn_id

                cursor.execute("""
                    INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name,
                        target_account, amount, commission, bank_name, ft_reference,
                        status, created_by, timestamp, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_MANAGER', ?, ?, ?)
                """, (txn_id, txn_type, cust_id, cust['full_name'], target_acc,
                      amount, commission, bank_name, ft_ref, session['username'], now, reason))

                conn.commit()
                msg = f"✅ Ref: {ft_ref} galmaa'eera. Manager approval eegaa jira."
                add_notification(f"Maker txn: {ft_ref}")

    conn.close()
    cust_options = "".join([f'<option value="{c["customer_id"]}">{c["full_name"]} - {c["customer_id"]}</option>' for c in customers])

    receipt_btn = f'<div style="margin-top:10px;"><a href="/receipt/{created_txn_id}" target="_blank" class="btn-action btn-purple">🖨️ Nagahee Maxxansi</a></div>' if created_txn_id else ''

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46; margin-bottom:12px;">💸 Transaction (Maker)</h2>
        {f"<p style='background:{'#dcfce7' if msg_type=='green' else '#fee2e2'}; color:{'#166534' if msg_type=='green' else '#991b1b'}; padding:10px; border-radius:6px; font-size:12px; margin-bottom:12px;'>{msg}{receipt_btn}</p>" if msg else ""}

        <form method="POST">
            <div class="form-group">
                <label>Gosa Transaction</label>
                <select name="txn_type" id="txn_type" class="input-field" onchange="toggleTargetAcc()">
                    <option value="DEPOSIT">Deposit</option>
                    <option value="WITHDRAWAL">Withdrawal</option>
                    <option value="T24_TRANSFER">T24 Transfer (2% Comm)</option>
                </select>
            </div>

            <div class="form-group">
                <label>Maammila Filadhu (Anti-Fraud Verify)</label>
                <input list="cust_list" name="customer_id" id="customer_id_select" required class="input-field" oninput="fetchCustomerVerification()" placeholder="Maqaa ykn ID...">
                <datalist id="cust_list">{cust_options}</datalist>
            </div>

            <div id="verification_box" style="display:none; background:#f0fdf4; border:1px solid #bbf7d0; padding:12px; border-radius:8px; margin-bottom:12px;">
                <h4 style="font-size:11px; color:#166534; margin-bottom:6px;">🛡️ VERIFY MAAMMILAA</h4>
                <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                    <img id="v_photo" src="" style="width:60px; height:60px; border-radius:6px; object-fit:cover;">
                    <img id="v_signature" src="" style="width:100px; height:50px; border-radius:4px; object-fit:contain; background:white;">
                    <a id="v_national_id" href="#" target="_blank" class="btn-action btn-blue" style="display:none;">🪪 ID</a>
                    <div style="font-size:11px;">
                        <p><b>Maqaa:</b> <span id="v_name"></span></p>
                        <p><b>Bilbila:</b> <span id="v_phone"></span></p>
                        <p><b>Balance:</b> <span id="v_balance"></span> Birr</p>
                        <p><b>Status:</b> <span id="v_status"></span></p>
                    </div>
                </div>
            </div>

            <div class="form-group" id="target_acc_group" style="display:none;">
                <label>Account ID Nama Itti Ergamu</label>
                <input type="text" name="target_account" id="target_account_input" placeholder="Account ID" class="input-field" oninput="verifyTargetAccount()">
                <div id="target_verify_res" style="font-size:11px; font-weight:bold; margin-top:4px;"></div>
            </div>

            <div class="form-group"><label>Hamma Maallaqaa</label><input type="number" step="0.01" name="amount" required class="input-field"></div>
            <div class="form-group"><label>Hamma Mirkaneessi</label><input type="number" step="0.01" name="confirm_amount" required class="input-field"></div>
            <div class="form-group"><label>Sababa</label><textarea name="reason" rows="2" class="input-field"></textarea></div>
            <button type="submit" class="btn-submit">⚡ Transaction Raawwadhu</button>
        </form>
    </div>

    <script>
    function toggleTargetAcc() {{
        var type = document.getElementById('txn_type').value;
        document.getElementById('target_acc_group').style.display = (type === 'T24_TRANSFER') ? 'block' : 'none';
    }}
    function verifyTargetAccount() {{
        var id = document.getElementById('target_account_input').value;
        var res = document.getElementById('target_verify_res');
        if (id.length < 5) {{ res.innerHTML = ''; return; }}
        fetch('/api/get_customer/' + id).then(r => r.json()).then(d => {{
            if (d.success) res.innerHTML = '<span style="color:#047857;">✅ ' + d.full_name + '</span>';
            else res.innerHTML = '<span style="color:#dc2626;">❌ Account hin argamne!</span>';
        }});
    }}
    function fetchCustomerVerification() {{
        var id = document.getElementById('customer_id_select').value;
        var box = document.getElementById('verification_box');
        if (id.length < 5) {{ box.style.display = 'none'; return; }}
        fetch('/api/get_customer/' + id).then(r => r.json()).then(d => {{
            if (d.success) {{
                document.getElementById('v_name').innerText = d.full_name;
                document.getElementById('v_phone').innerText = d.phone;
                document.getElementById('v_balance').innerText = Number(d.balance || 0).toLocaleString(undefined, {{minimumFractionDigits: 2}});
                document.getElementById('v_photo').src = d.photo_path ? '/uploads/' + d.photo_path : '';
                document.getElementById('v_photo').style.display = d.photo_path ? '' : 'none';
                document.getElementById('v_signature').src = d.signature_path ? '/uploads/' + d.signature_path : '';
                document.getElementById('v_signature').style.display = d.signature_path ? '' : 'none';
                const idLink = document.getElementById('v_national_id');
                if (d.national_id_path) {{ idLink.href = '/uploads/' + d.national_id_path; idLink.style.display = ''; }}
                else {{ idLink.style.display = 'none'; }}
                document.getElementById('v_status').innerHTML = d.freeze_status === 'FROZEN' ? '<b style="color:red;">FROZEN</b>' : '<b style="color:green;">ACTIVE</b>';
                box.style.display = 'block';
            }} else {{ box.style.display = 'none'; }}
        }});
    }}
    </script>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/maker_receipts')
def maker_receipts():
    if 'role' not in session or session['role'] != 'MAKER':
        return "🚫 Shoora MAKER qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT txn_id, ft_reference, txn_type, customer_name, amount, status, timestamp, reason FROM transactions WHERE created_by = ? ORDER BY timestamp DESC LIMIT 100", (session['username'],))
    txns = cursor.fetchall()
    conn.close()

    cards = ""
    for t in txns:
        cards += f"""
        <div class="item-card">
            <div style="display:flex; justify-content:space-between;">
                <span style="font-size:12px; font-weight:bold;">{t['ft_reference']}</span>
                <span class="badge badge-active">{t['status']}</span>
            </div>
            <div style="font-size:13px; font-weight:bold;">{t['txn_type']}: {t['amount']:,.2f} Birr</div>
            <div style="font-size:11px; color:#64748b;">{t['customer_name']} | {t['timestamp']}</div>
            <div style="text-align:right; margin-top:8px;"><a href="/receipt/{t['txn_id']}" target="_blank" class="btn-action btn-purple">🖨️</a></div>
        </div>
        """
    content = f"<h2 style='font-size:16px; color:#065f46;'>🧾 Nagaheewwan Keessan</h2>{cards or '<p>Hin jiru.</p>'}"
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# APPROVAL ROUTES
# ================================================================
@app.route('/approve_customer/<cust_id>')
def approve_customer(cust_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET status = 'ACTIVE' WHERE customer_id = ?", (cust_id,))
    conn.commit()
    conn.close()
    add_notification(f"✅ Maammilli {cust_id} mirkanaa'eera.")
    return redirect('/pending')


@app.route('/reject_customer/<cust_id>')
def reject_customer(cust_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET status = 'REJECTED' WHERE customer_id = ?", (cust_id,))
    conn.commit()
    conn.close()
    add_notification(f"❌ Maammilli {cust_id} kuffifameera.")
    return redirect('/pending')


@app.route('/approve_transaction/<txn_id>')
def approve_transaction(txn_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,))
    txn = cursor.fetchone()

    if txn and txn['status'] == 'PENDING_MANAGER':
        cursor.execute("UPDATE transactions SET status = 'APPROVED' WHERE txn_id = ?", (txn_id,))
        t_type = txn['txn_type']
        amt = txn['amount'] or 0.0
        comm = txn['commission'] or 0.0
        cust_id = txn['customer_id']
        target = txn['target_account']

        if t_type == 'DEPOSIT':
            cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (amt, cust_id))
        elif t_type == 'WITHDRAWAL':
            cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amt + comm, cust_id))
        elif t_type == 'T24_TRANSFER':
            cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amt + comm, cust_id))
            if target:
                cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (amt, target))
        conn.commit()
        add_notification(f"✅ Txn {txn_id} ({t_type}) mirkanaa'eera.")

    conn.close()
    return redirect('/pending')


@app.route('/reject_transaction/<txn_id>')
def reject_transaction(txn_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,))
    txn = cursor.fetchone()

    if txn and txn['status'] == 'PENDING_MANAGER':
        cursor.execute("UPDATE transactions SET status = 'REJECTED' WHERE txn_id = ?", (txn_id,))
        if txn['txn_type'] == 'RTGS_TRANSFER':
            cursor.execute(
                "UPDATE customers SET balance = balance + ? WHERE customer_id = ?",
                ((txn['amount'] or 0.0) + (txn['commission'] or 0.0), txn['customer_id'])
            )
        conn.commit()
        add_notification(f"❌ Txn {txn_id} kuffifameera.")

    conn.close()
    return redirect('/pending')


@app.route('/approve_mobile_banking/<cust_id>')
def approve_mobile_banking(cust_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET mobile_status = 'ACTIVE' WHERE customer_id = ?", (cust_id,))
    conn.commit()
    conn.close()
    add_notification(f"✅ Mobile Banking {cust_id} mirkanaa'eera.")
    return redirect('/pending')


@app.route('/reject_mobile_banking/<cust_id>')
def reject_mobile_banking(cust_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET mobile_status = 'INACTIVE' WHERE customer_id = ?", (cust_id,))
    conn.commit()
    conn.close()
    add_notification(f"❌ Mobile Banking {cust_id} kuffifameera.")
    return redirect('/pending')


@app.route('/approve_pin_reset/<cust_id>')
def approve_pin_reset(cust_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pending_pin_reset FROM customers WHERE customer_id = ?", (cust_id,))
    row = cursor.fetchone()
    if row and row['pending_pin_reset']:
        cursor.execute("UPDATE customers SET mobile_pin = ?, pending_pin_reset = '' WHERE customer_id = ?",
                       (row['pending_pin_reset'], cust_id))
        conn.commit()
        add_notification(f"✅ PIN reset {cust_id} mirkanaa'eera.")
    conn.close()
    return redirect('/pending')


@app.route('/reject_pin_reset/<cust_id>')
def reject_pin_reset(cust_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET pending_pin_reset = '' WHERE customer_id = ?", (cust_id,))
    conn.commit()
    conn.close()
    add_notification(f"❌ PIN reset {cust_id} kuffifameera.")
    return redirect('/pending')


@app.route('/pending')
def pending():
    if 'role' not in session or session['role'] not in ['MANAGER', 'AUDITOR', 'CEO']:
        return "🚫 Hayyama Hin Qabdan!", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE status = 'PENDING_APPROVAL' ORDER BY created_at DESC")
    pending_custs = cursor.fetchall()
    cursor.execute("SELECT * FROM customers WHERE mobile_status = 'PENDING_APPROVAL' AND status = 'ACTIVE' ORDER BY created_at DESC")
    pending_mobiles = cursor.fetchall()
    cursor.execute("SELECT * FROM customers WHERE pending_pin_reset IS NOT NULL AND pending_pin_reset != '' ORDER BY created_at DESC")
    pending_pins = cursor.fetchall()
    cursor.execute("SELECT * FROM transactions WHERE status = 'PENDING_MANAGER' ORDER BY timestamp DESC")
    pending_txns = cursor.fetchall()
    conn.close()

    user_role = session.get('role')

    cust_html = ""
    for c in pending_custs:
        btns = f"""
            <div style="margin-top:8px;">
                <a href="/approve_customer/{c['customer_id']}" class="btn-action btn-green">✅ Mirkaneessi</a>
                <a href="/reject_customer/{c['customer_id']}" class="btn-action btn-red" onclick="return confirm('Sassaabuu?')">❌ Kuffisi</a>
            </div>
        """ if user_role == 'MANAGER' else ""
        cust_html += f"""
        <div class="item-card">
            <div style="font-size:13px; font-weight:bold;">{c['full_name']} (Acc: {c['customer_id']})</div>
            <div style="font-size:11px; color:#64748b;">Phone: {c['phone']} | {c['account_type']} | Bal: {c['balance']:,.2f}</div>
            <div style="font-size:11px; color:#1d4ed8;">📲 Mobile: {c['mobile_status']}</div>
            <div class="img-grid">
                <a href="/uploads/{c['photo_path']}" target="_blank"><img src="/uploads/{c['photo_path']}"></a>
                <a href="/uploads/{c['signature_path']}" target="_blank"><img src="/uploads/{c['signature_path']}"></a>
            </div>
            {btns}
        </div>
        """

    mob_html = ""
    for m in pending_mobiles:
        btns = f"""
            <div style="margin-top:8px;">
                <a href="/approve_mobile_banking/{m['customer_id']}" class="btn-action btn-green">📲 Approve</a>
                <a href="/reject_mobile_banking/{m['customer_id']}" class="btn-action btn-red">❌ Reject</a>
            </div>
        """ if user_role in ['MANAGER', 'CEO'] else ""
        mob_html += f"""
        <div class="item-card" style="border-left:4px solid #2563eb;">
            <div style="font-size:13px; font-weight:bold; color:#1e3a8a;">📱 {m['full_name']} ({m['customer_id']})</div>
            <div style="font-size:11px;">Phone: {m['phone']} | PIN: {m['mobile_pin']}</div>
            {btns}
        </div>
        """

    pin_html = ""
    for p in pending_pins:
        btns = f"""
            <div style="margin-top:8px;">
                <a href="/approve_pin_reset/{p['customer_id']}" class="btn-action btn-green">✅ Approve PIN Reset</a>
                <a href="/reject_pin_reset/{p['customer_id']}" class="btn-action btn-red">❌ Reject</a>
            </div>
        """ if user_role in ['MANAGER', 'CEO'] else ""
        pin_html += f"""
        <div class="item-card" style="border-left:4px solid #7c3aed;">
            <div style="font-size:13px; font-weight:bold; color:#6b21a8;">🔑 PIN Reset: {p['full_name']} ({p['customer_id']})</div>
            <div style="font-size:11px;">PIN Pending: <b>{p['pending_pin_reset']}</b></div>
            {btns}
        </div>
        """

    txn_html = ""
    for t in pending_txns:
        btns = f"""
            <div style="margin-top:8px;">
                <a href="/approve_transaction/{t['txn_id']}" class="btn-action btn-green">✅ Approve</a>
                <a href="/reject_transaction/{t['txn_id']}" class="btn-action btn-red" onclick="return confirm('Kuffisuu?')">❌ Reject</a>
            </div>
        """ if user_role == 'MANAGER' else ""
        txn_html += f"""
        <div class="item-card">
            <div style="font-size:13px; font-weight:bold; color:#047857;">{t['txn_type']} — {t['amount']:,.2f} Birr</div>
            <div style="font-size:11px;">{t['customer_name']} ({t['customer_id']})</div>
            <div style="font-size:11px; color:#64748b;">Ref: {t['ft_reference']} | Comm: {t['commission']:,.2f} | Bank: {t['bank_name'] or '-'}</div>
            <div style="font-size:10px; color:#94a3b8;">By: {t['created_by']} | {t['timestamp']} | Reason: {t['reason'] or '-'}</div>
            {btns}
        </div>
        """

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46; margin-bottom:12px;">📋 Approvals ({user_role})</h2>
        <h3 style="font-size:13px; color:#1e3a8a;">📲 Mobile Banking ({len(pending_mobiles)})</h3>
        {mob_html or '<p style="font-size:12px; color:#64748b; margin-bottom:12px;">Hin jiru.</p>'}
        <h3 style="font-size:13px; color:#6b21a8;">🔑 PIN Reset ({len(pending_pins)})</h3>
        {pin_html or '<p style="font-size:12px; color:#64748b; margin-bottom:12px;">Hin jiru.</p>'}
        <h3 style="font-size:13px; color:#334155;">👥 Maammiltoota ({len(pending_custs)})</h3>
        {cust_html or '<p style="font-size:12px; color:#64748b; margin-bottom:12px;">Hin jiru.</p>'}
        <h3 style="font-size:13px; color:#334155;">💸 Transactions ({len(pending_txns)})</h3>
        {txn_html or '<p style="font-size:12px; color:#64748b;">Hin jiru.</p>'}
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# CUSTOMER LIST
# ================================================================
@app.route('/customers')
def customers():
    if 'role' not in session:
        return redirect('/login')

    search = request.args.get('search', '').strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    if search:
        cursor.execute("SELECT * FROM customers WHERE customer_id LIKE ? OR full_name LIKE ? OR phone LIKE ? ORDER BY created_at DESC",
                       (f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        cursor.execute("SELECT * FROM customers ORDER BY created_at DESC LIMIT 100")
    custs = cursor.fetchall()
    conn.close()

    user_role = session.get('role')
    rows = ""
    for c in custs:
        photo = f'<a href="/uploads/{c["photo_path"]}" target="_blank"><img src="/uploads/{c["photo_path"]}" style="width:54px;height:54px;object-fit:cover;border-radius:7px;"></a>' if c['photo_path'] else '-'
        natid = f'<a href="/uploads/{c["national_id_path"]}" target="_blank" class="btn-action btn-blue" style="font-size:10px;">🪪</a>' if c.get('national_id_path') else '-'

        mobile_btn = ""
        pin_btn = ""
        if user_role in ['MANAGER', 'MAKER', 'CEO']:
            if c['mobile_status'] == 'INACTIVE':
                mobile_btn = f'<a href="/enable_mobile_service/{c["customer_id"]}" class="btn-action btn-blue" style="font-size:10px;">📲 Request</a>'
            elif c['mobile_status'] == 'PENDING_APPROVAL':
                mobile_btn = '<span class="badge badge-pending">Mobile Pending</span>'
            else:
                mobile_btn = '<span class="badge badge-active">Mobile Active</span>'

            if c.get('pending_pin_reset'):
                pin_btn = '<span class="badge badge-pending">🔑 PIN Pending</span>'
            else:
                pin_btn = f'''<form method="POST" action="/reset_customer_pin/{c["customer_id"]}" style="display:inline;" onsubmit="return confirm('PIN reset request?')"><button type="submit" class="btn-action btn-purple" style="font-size:10px;">🔑 Reset</button></form>'''

        edit_btn = f'<a href="/edit_customer/{c["customer_id"]}" class="btn-action btn-orange" style="font-size:10px;">✏️</a>' if user_role == 'MANAGER' else ''
        freeze_btn = f'<a href="/freeze_customer/{c["customer_id"]}" class="btn-action btn-red" style="font-size:10px;">🔒</a>' if user_role == 'CEO' else ''

        rows += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:6px; font-weight:bold;">{c['customer_id']}</td>
            <td style="padding:6px;">{c['full_name']}<div style="font-size:10px; color:#64748b;">{c['phone'] or '-'}</div></td>
            <td style="padding:6px;">{photo}</td>
            <td style="padding:6px;">{natid}</td>
            <td style="padding:6px;"><span class="badge badge-active">{c['account_type']}</span></td>
            <td style="padding:6px; font-weight:bold; color:#065f46;">{c['balance']:,.2f}</td>
            <td style="padding:6px;"><span class="badge {'badge-frozen' if c['freeze_status']=='FROZEN' else 'badge-active'}">{c['freeze_status']}</span></td>
            <td style="padding:6px; text-align:right;">
                <a href="/statement/{c['customer_id']}" class="btn-action btn-blue" style="font-size:10px;">📜</a>
                {edit_btn}{freeze_btn}{mobile_btn}{pin_btn}
            </td>
        </tr>
        """

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46; margin-bottom:12px;">👥 Maammiltoota</h2>
        <form method="GET" style="display:flex; gap:8px; margin-bottom:12px;">
            <input type="text" name="search" value="{search}" placeholder="Maqaa, Acc, Phone..." class="input-field" style="flex:1;">
            <button type="submit" class="btn-action btn-blue">🔍</button>
        </form>
        <div style="overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; text-align:left;">
                <thead>
                    <tr style="background:#f8fafc; font-size:11px; color:#64748b;">
                        <th style="padding:6px;">Acc</th><th style="padding:6px;">Maqaa</th>
                        <th style="padding:6px;">Suuraa</th><th style="padding:6px;">ID</th>
                        <th style="padding:6px;">Type</th><th style="padding:6px;">Balance</th>
                        <th style="padding:6px;">Status</th><th style="padding:6px; text-align:right;">Actions</th>
                    </tr>
                </thead>
                <tbody>{rows or '<tr><td colspan="8" style="text-align:center; padding:16px;">Hin jiru.</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/enable_mobile_service/<cust_id>')
def enable_mobile_service(cust_id):
    if 'role' not in session or session['role'] not in ['MAKER', 'MANAGER', 'CEO']:
        return "🚫 Hayyama Hin Qabdan!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET mobile_status = 'PENDING_APPROVAL' WHERE customer_id = ?", (cust_id,))
    conn.commit()
    conn.close()
    add_notification(f"Maker ({session['username']}) Mobile Banking request for {cust_id}.")
    return redirect('/customers')


@app.route('/reset_customer_pin/<cust_id>', methods=['POST', 'GET'])
def reset_customer_pin(cust_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'MAKER', 'CEO']:
        return "🚫 Hayyama Hin Qabdan!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    if session['role'] == 'MAKER':
        cursor.execute("UPDATE customers SET pending_pin_reset = '1234' WHERE customer_id = ?", (cust_id,))
        conn.commit()
        add_notification(f"Maker ({session['username']}) PIN reset request for {cust_id}.")
    else:
        cursor.execute("UPDATE customers SET mobile_pin = '1234', pending_pin_reset = '' WHERE customer_id = ?", (cust_id,))
        conn.commit()
        add_notification(f"PIN reset for {cust_id} by {session['username']}.")
    conn.close()
    return redirect('/customers')


@app.route('/edit_customer/<cust_id>', methods=['GET', 'POST'])
def edit_customer(cust_id):
    if 'role' not in session or session['role'] != 'MANAGER':
        return "🚫 Manager Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
    customer = cursor.fetchone()
    if not customer:
        conn.close()
        return "Maammilli Hin Argamne", 404

    msg = None
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        gender = request.form.get('gender')
        account_type = request.form.get('account_type')
        photo_file = request.files.get('photo')
        sig_file = request.files.get('signature')
        natid_file = request.files.get('national_id')

        photo_name = customer['photo_path']
        sig_name = customer['signature_path']
        natid_name = customer.get('national_id_path', '')
        ts = int(datetime.datetime.now().timestamp())

        if photo_file and photo_file.filename and allowed_file(photo_file.filename):
            photo_name = compress_and_save_image(photo_file, f"face_edit_{ts}_" + secure_filename(photo_file.filename))
        if sig_file and sig_file.filename and allowed_file(sig_file.filename):
            sig_name = compress_and_save_image(sig_file, f"sig_edit_{ts}_" + secure_filename(sig_file.filename))
        if natid_file and natid_file.filename and allowed_file(natid_file.filename):
            natid_name = compress_and_save_image(natid_file, f"nat_edit_{ts}_" + secure_filename(natid_file.filename))

        cursor.execute("""
            UPDATE customers SET full_name=?, phone=?, gender=?, account_type=?,
                photo_path=?, signature_path=?, national_id_path=?
            WHERE customer_id=?
        """, (full_name, phone, gender, account_type, photo_name, sig_name, natid_name, cust_id))
        conn.commit()
        msg = "✅ Jijjiirameera!"
        cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
        customer = cursor.fetchone()
    conn.close()

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46;">✏️ Edit Maammila</h2>
        {f"<p style='background:#dcfce7; padding:10px; border-radius:6px;'>{msg}</p>" if msg else ""}
        <form method="POST" enctype="multipart/form-data">
            <div class="form-group"><label>Maqaa</label><input type="text" name="full_name" value="{customer['full_name']}" required class="input-field"></div>
            <div class="form-group"><label>Phone</label><input type="text" name="phone" value="{customer['phone']}" required class="input-field"></div>
            <div class="form-group"><label>Saala</label>
                <select name="gender" class="input-field">
                    <option {'selected' if customer['gender']=='Dhiira' else ''}>Dhiira</option>
                    <option {'selected' if customer['gender']=='Dubartii' else ''}>Dubartii</option>
                </select>
            </div>
            <div class="form-group"><label>Type</label>
                <select name="account_type" class="input-field">
                    <option value="WADIA" {'selected' if customer['account_type']=='WADIA' else ''}>WADIA</option>
                    <option value="MUDARABA" {'selected' if customer['account_type']=='MUDARABA' else ''}>MUDARABA</option>
                </select>
            </div>
            <div class="form-group"><label>Suuraa Haaraa</label><input type="file" name="photo" accept="image/*" class="input-field"></div>
            <div class="form-group"><label>Mallattoo Haaraa</label><input type="file" name="signature" accept="image/*" class="input-field"></div>
            <div class="form-group"><label>National ID</label><input type="file" name="national_id" accept="image/*,pdf" class="input-field"></div>
            <button type="submit" class="btn-submit">💾 Save</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/freeze_customer/<cust_id>', methods=['GET', 'POST'])
def freeze_customer(cust_id):
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 CEO Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
    c = cursor.fetchone()
    if not c:
        conn.close()
        return "Hin Argamne", 404
    msg = None
    if request.method == 'POST':
        new_status = request.form.get('freeze_status')
        reason = request.form.get('freeze_reason', '').strip()
        cursor.execute("UPDATE customers SET freeze_status=?, freeze_reason=? WHERE customer_id=?", (new_status, reason, cust_id))
        conn.commit()
        msg = f"✅ {new_status}!"
        cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
        c = cursor.fetchone()
    conn.close()
    content = f"""
    <div class="box">
        <h2 style="font-size:16px;">🔒 Freeze / Unfreeze</h2>
        <p style="font-size:12px;">{c['full_name']} ({c['customer_id']}) — Amma: <b>{c['freeze_status']}</b></p>
        {f"<p style='background:#dcfce7; padding:10px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group">
                <select name="freeze_status" class="input-field">
                    <option value="FROZEN" {'selected' if c['freeze_status']=='FROZEN' else ''}>FROZEN</option>
                    <option value="UNFROZEN" {'selected' if c['freeze_status']=='UNFROZEN' else ''}>UNFROZEN</option>
                </select>
            </div>
            <div class="form-group"><label>Sababa</label><textarea name="freeze_reason" rows="3" required class="input-field">{c['freeze_reason']}</textarea></div>
            <button type="submit" class="btn-submit">Save</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# RECEIPT / STATEMENT / SEARCH
# ================================================================
@app.route('/print_receipt_search', methods=['GET', 'POST'])
def print_receipt_search():
    if 'role' not in session or session['role'] not in ['MANAGER', 'AUDITOR', 'CEO', 'MAKER']:
        return "🚫 Hayyama Qabu Qofa!", 403
    txn = None
    msg = None
    if request.method == 'POST':
        s = request.form.get('txn_search_id', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE txn_id = ? OR ft_reference = ?", (s, s))
        txn = cursor.fetchone()
        conn.close()
        if not txn:
            msg = "❌ Hin argamne!"
    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46;">🖨️ Nagahee Barbaadi</h2>
        {f"<p style='color:#991b1b;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group"><label>Txn ID ykn FT Ref</label><input type="text" name="txn_search_id" required class="input-field"></div>
            <button type="submit" class="btn-submit">🔍 Barbaadi</button>
        </form>
    </div>
    """
    if txn:
        content += f"""
        <div class="item-card" style="border-left:4px solid #7c3aed;">
            <div><b>Ref:</b> {txn['ft_reference']}</div>
            <div><b>Maammila:</b> {txn['customer_name']}</div>
            <div><b>{txn['txn_type']}:</b> {txn['amount']:,.2f} Birr</div>
            <div><b>Status:</b> {txn['status']}</div>
            <div style="text-align:right;"><a href="/receipt/{txn['txn_id']}" target="_blank" class="btn-action btn-purple">🖨️ Print</a></div>
        </div>
        """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/receipt/<txn_id>')
def print_receipt(txn_id):
    if 'role' not in session:
        return redirect('/login')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,))
    txn = cursor.fetchone()
    if not txn:
        conn.close()
        return "Nagaheen Hin Argamne", 404
    cursor.execute("SELECT phone, balance FROM customers WHERE customer_id = ?", (txn['customer_id'],))
    cust = cursor.fetchone()
    target_name = ""
    if txn['txn_type'] == 'T24_TRANSFER' and txn['target_account']:
        cursor.execute("SELECT full_name FROM customers WHERE customer_id = ?", (txn['target_account'],))
        tc = cursor.fetchone()
        if tc:
            target_name = tc['full_name']
    conn.close()
    phone = cust['phone'] if cust else ""
    sender_info = f"{txn['customer_name']} ({txn['customer_id']})"
    receiver_info = f"{target_name} ({txn['target_account']})" if target_name else (txn['target_account'] or "-")
    return f"""
    <!DOCTYPE html><html><head><title>Receipt - {txn['ft_reference']}</title>
    <style>
        body {{ font-family: sans-serif; padding: 20px; max-width: 500px; margin: 0 auto; border: 1px solid #cbd5e1; border-radius: 8px; }}
        .header {{ text-align: center; border-bottom: 2px solid #065f46; padding-bottom: 10px; margin-bottom: 15px; }}
        .row {{ display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 8px; border-bottom: 1px dashed #e2e8f0; padding-bottom: 4px; }}
        .btn-print {{ background: #065f46; color: white; border: none; padding: 10px; width: 100%; font-weight: bold; cursor: pointer; border-radius: 6px; margin-top: 15px; }}
        @media print {{ .btn-print {{ display: none; }} }}
    </style></head><body>
        <div class="header"><h2 style="color:#065f46;">IMANA MICROFINANCE</h2><p style="font-size:11px;">NAGAHEE KAFFALTII</p></div>
        <div class="row"><span>FT Ref:</span><b>{txn['ft_reference']}</b></div>
        <div class="row"><span>Txn ID:</span><b>{txn['txn_id']}</b></div>
        <div class="row"><span>Guyyaa:</span><b>{txn['timestamp']}</b></div>
        <div class="row"><span>Gosa:</span><b>{txn['txn_type']}</b></div>
        <div class="row"><span>Sender:</span><b>{sender_info}</b></div>
        <div class="row"><span>Receiver:</span><b>{receiver_info}</b></div>
        <div class="row"><span>Bilbila:</span><b>{phone}</b></div>
        <div class="row"><span>Hamma:</span><b style="color:#065f46;">{txn['amount']:,.2f} Birr</b></div>
        <div class="row"><span>Commission:</span><b>{txn['commission']:,.2f} Birr</b></div>
        <div class="row"><span>Sababa:</span><b>{txn['reason'] or '-'}</b></div>
        <div class="row"><span>Status:</span><b>{txn['status']}</b></div>
        <div class="row"><span>Maker:</span><b>{txn['created_by']}</b></div>
        <div style="margin-top:30px; display:flex; justify-content:space-between; font-size:11px;">
            <div>__________________<br>Maker</div><div>__________________<br>Maammilaa</div>
        </div>
        <button onclick="window.print()" class="btn-print">🖨️ Print</button>
    </body></html>"""


@app.route('/statement/<cust_id>')
def statement(cust_id):
    if 'role' not in session:
        return redirect('/login')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
    c = cursor.fetchone()
    if not c:
        conn.close()
        return "Hin Argamne", 404
    cursor.execute("""
        SELECT txn_id, txn_type, amount, commission, ft_reference, status, created_by, timestamp, customer_id, target_account
        FROM transactions WHERE (customer_id = ? OR target_account = ?) AND status = 'APPROVED'
        ORDER BY timestamp ASC
    """, (cust_id, cust_id))
    txns = cursor.fetchall()
    conn.close()

    running = 0.0
    rows = ""
    for t in txns:
        amount = t['amount']
        comm = t['commission']
        t_type = t['txn_type']
        if t_type == 'DEPOSIT' or (t_type == 'T24_TRANSFER' and t['target_account'] == cust_id):
            running += amount
            impact = f"+{amount:,.2f}"
        elif t_type == 'WITHDRAWAL':
            running -= (amount + comm)
            impact = f"-{(amount + comm):,.2f}"
        elif t_type == 'T24_TRANSFER' and t['customer_id'] == cust_id:
            running -= amount
            impact = f"-{amount:,.2f}"
        else:
            impact = f"{amount:,.2f}"
        rows += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:11px;">
            <td style="padding:8px;">{t['timestamp']}</td>
            <td style="padding:8px;">{t['ft_reference']}</td>
            <td style="padding:8px;">{t_type}</td>
            <td style="padding:8px;">{impact}</td>
            <td style="padding:8px; font-weight:bold; color:#065f46;">{running:,.2f} Birr</td>
        </tr>
        """
    content = f"""
    <div class="box">
        <div style="display:flex; justify-content:space-between;">
            <div>
                <h2 style="font-size:16px; color:#065f46;">📜 Statement</h2>
                <p><b>{c['full_name']}</b> ({c['customer_id']})</p>
                <p style="font-size:11px; color:#64748b;">Balance: <b>{c['balance']:,.2f} Birr</b> | {c['account_type']}</p>
            </div>
            <button onclick="window.print()" class="btn-action btn-purple no-print">🖨️</button>
        </div>
    </div>
    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse;">
            <thead><tr style="background:#f8fafc; font-size:11px;">
                <th style="padding:8px;">Guyyaa</th><th style="padding:8px;">Ref</th>
                <th style="padding:8px;">Type</th><th style="padding:8px;">Sochii</th>
                <th style="padding:8px;">Balance</th>
            </tr></thead>
            <tbody>{rows or '<tr><td colspan="5" style="text-align:center; padding:16px;">Hin jiru.</td></tr>'}</tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# AUDITOR
# ================================================================
@app.route('/auditor_eod', methods=['GET', 'POST'])
def auditor_eod():
    if 'role' not in session or session['role'] != 'AUDITOR':
        return "🚫 Auditor Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    msg = None
    if request.method == 'POST':
        cursor.execute("UPDATE transactions SET audited_status = 'CLOSED' WHERE audited_status = 'OPEN' AND status = 'APPROVED'")
        conn.commit()
        msg = "✅ EOD Closed!"
    cursor.execute("""
        SELECT created_by,
            SUM(CASE WHEN txn_type='DEPOSIT' THEN amount ELSE 0 END) as total_dep,
            SUM(CASE WHEN txn_type='WITHDRAWAL' THEN amount ELSE 0 END) as total_with
        FROM transactions WHERE audited_status = 'OPEN' AND status = 'APPROVED'
        GROUP BY created_by
    """)
    data = cursor.fetchall()
    conn.close()

    rows = ""
    total = 0.0
    for r in data:
        net = r['total_dep'] - r['total_with']
        total += net
        rows += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px;">{r['created_by']}</td>
            <td style="padding:8px; color:#047857;">+{r['total_dep']:,.2f}</td>
            <td style="padding:8px; color:#dc2626;">-{r['total_with']:,.2f}</td>
            <td style="padding:8px; font-weight:bold;">{net:,.2f}</td>
        </tr>"""

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#c2410c;">📊 EOD</h2>
        {f"<p style='background:#dcfce7; padding:10px;'>{msg}</p>" if msg else ""}
    </div>
    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%;">
            <thead><tr style="background:#f8fafc; font-size:11px;">
                <th style="padding:8px;">Maker</th><th style="padding:8px;">Deposit</th>
                <th style="padding:8px;">Withdraw</th><th style="padding:8px;">Net</th>
            </tr></thead>
            <tbody>{rows or '<tr><td colspan="4" style="text-align:center; padding:16px;">Hin jiru.</td></tr>'}</tbody>
        </table>
    </div>
    <div class="box" style="text-align:center;">
        <p><b>Waliigala: {total:,.2f} Birr</b></p>
        <form method="POST"><button class="btn-submit" style="background:#ea580c;" onclick="return confirm('Cufiinsa?')">🔒 Close EOD</button></form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/auditor_reversal_request', methods=['GET', 'POST'])
def auditor_reversal_request():
    if 'role' not in session or session['role'] != 'AUDITOR':
        return "🚫 Auditor Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    msg = None
    if request.method == 'POST':
        txn_id = request.form.get('txn_id', '').strip()
        reason = request.form.get('reason', '').strip()
        cursor.execute("SELECT txn_id FROM transactions WHERE txn_id = ? OR ft_reference = ?", (txn_id, txn_id))
        row = cursor.fetchone()
        if not row:
            msg = "❌ Txn hin argamne!"
        else:
            rev_id = f"REV-{int(datetime.datetime.now().timestamp())}"
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO reversals (reversal_id, txn_id, reason, requested_by, status, timestamp)
                VALUES (?, ?, ?, ?, 'PENDING_MANAGER', ?)
            """, (rev_id, row['txn_id'], reason, session['username'], now))
            conn.commit()
            msg = f"✅ Reversal request for {row['txn_id']} dhiyaateera!"
    conn.close()
    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#c2410c;">⚠️ Reversal Gaafachu</h2>
        {f"<p style='background:#dcfce7; padding:10px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group"><label>Txn ID ykn FT Ref</label><input type="text" name="txn_id" required class="input-field"></div>
            <div class="form-group"><label>Sababa</label><textarea name="reason" rows="3" required class="input-field"></textarea></div>
            <button type="submit" class="btn-submit" style="background:#c2410c;">🚀 Ergi</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/reversals_list')
def reversals_list():
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Manager ykn CEO Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reversals ORDER BY timestamp DESC")
    revs = cursor.fetchall()
    conn.close()
    rows = ""
    for r in revs:
        actions = ""
        if session['role'] == 'MANAGER' and r['manager_approved'] == 0:
            actions = f'<a href="/approve_reversal/manager/{r["reversal_id"]}" class="btn-action btn-blue">✅ Manager</a>'
        elif session['role'] == 'CEO' and r['manager_approved'] == 1 and r['ceo_approved'] == 0:
            actions = f'<a href="/approve_reversal/ceo/{r["reversal_id"]}" class="btn-action btn-purple">✅ CEO</a>'
        rows += f"""
        <div class="item-card">
            <div><b>Rev:</b> {r['reversal_id']} | <b>Txn:</b> {r['txn_id']}</div>
            <div style="font-size:12px;"><b>Sababa:</b> {r['reason']}</div>
            <div style="font-size:11px; color:#64748b;">By: {r['requested_by']} | {r['status']}</div>
            <div style="margin-top:8px;">{actions}</div>
        </div>"""
    content = f"<h2 style='font-size:16px; color:#7c3aed;'>🔄 Reversals</h2>{rows or '<p>Hin jiru.</p>'}"
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/approve_reversal/<role_type>/<rev_id>')
def approve_reversal(role_type, rev_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return redirect('/login')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reversals WHERE reversal_id = ?", (rev_id,))
    rev = cursor.fetchone()
    if rev:
        if role_type == 'manager' and session['role'] == 'MANAGER':
            cursor.execute("UPDATE reversals SET manager_approved = 1, status = 'PENDING_CEO' WHERE reversal_id = ?", (rev_id,))
        elif role_type == 'ceo' and session['role'] == 'CEO':
            cursor.execute("UPDATE reversals SET ceo_approved = 1, status = 'APPROVED' WHERE reversal_id = ?", (rev_id,))
            cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (rev['txn_id'],))
            t = cursor.fetchone()
            if t and t['status'] == 'APPROVED':
                if t['txn_type'] == 'DEPOSIT':
                    cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (t['amount'], t['customer_id']))
                elif t['txn_type'] == 'WITHDRAWAL':
                    cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (t['amount'] + t['commission'], t['customer_id']))
                elif t['txn_type'] == 'T24_TRANSFER':
                    cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (t['amount'] + t['commission'], t['customer_id']))
                    if t['target_account']:
                        cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (t['amount'], t['target_account']))
                cursor.execute("UPDATE transactions SET status = 'REVERSED' WHERE txn_id = ?", (t['txn_id'],))
        conn.commit()
    conn.close()
    return redirect('/reversals_list')


# ================================================================
# CEO / MANAGER
# ================================================================
@app.route('/ceo_commission')
def ceo_commission():
    if 'role' not in session or session['role'] not in ['CEO', 'MANAGER']:
        return "🚫 CEO ykn MANAGER Qofa!", 403
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    filter_type = request.args.get('filter_type', 'ALL')
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT txn_id, ft_reference, customer_name, amount, commission, txn_type, timestamp, created_by FROM transactions WHERE status='APPROVED'"
    params = []
    if filter_type != 'ALL':
        query += " AND txn_type = ?"
        params.append(filter_type)
    if start_date:
        query += " AND timestamp >= ?"
        params.append(start_date + " 00:00:00")
    if end_date:
        query += " AND timestamp <= ?"
        params.append(end_date + " 23:59:59")
    query += " ORDER BY timestamp DESC"
    cursor.execute(query, params)
    txns = cursor.fetchall()
    conn.close()

    total_amt = sum([t['amount'] for t in txns])
    total_comm = sum([t['commission'] for t in txns])
    rows = ""
    for t in txns:
        rows += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:11px;">
            <td style="padding:6px;">{t['timestamp']}</td>
            <td style="padding:6px;">{t['ft_reference']}</td>
            <td style="padding:6px;">{t['customer_name']}</td>
            <td style="padding:6px;">{t['txn_type']}</td>
            <td style="padding:6px;">{t['amount']:,.2f}</td>
            <td style="padding:6px; color:#047857;">+{t['commission']:,.2f}</td>
        </tr>"""

    content = f"""
    <div class="card-ceo-profit">
        <div class="net-title">💰 Commission ({session['role']})</div>
        <div class="net-amount">{total_comm:,.2f} Birr</div>
        <p style="font-size:11px;">Total Txn: {total_amt:,.2f} Birr</p>
    </div>
    <div class="box">
        <form method="GET" style="display:flex; gap:6px; flex-wrap:wrap;">
            <select name="filter_type" class="input-field" style="flex:1;">
                <option value="ALL">Hunda</option>
                <option value="DEPOSIT">Deposit</option>
                <option value="WITHDRAWAL">Withdrawal</option>
                <option value="T24_TRANSFER">Transfer</option>
                <option value="RTGS_TRANSFER">RTGS</option>
            </select>
            <input type="date" name="start_date" value="{start_date}" class="input-field" style="flex:1;">
            <input type="date" name="end_date" value="{end_date}" class="input-field" style="flex:1;">
            <button type="submit" class="btn-action btn-purple">🔍</button>
        </form>
    </div>
    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse;">
            <thead><tr style="background:#f8fafc; font-size:11px;">
                <th style="padding:6px;">Date</th><th style="padding:6px;">Ref</th>
                <th style="padding:6px;">Maammila</th><th style="padding:6px;">Type</th>
                <th style="padding:6px;">Amount</th><th style="padding:6px;">Comm</th>
            </tr></thead>
            <tbody>{rows or '<tr><td colspan="6" style="text-align:center; padding:16px;">Hin jiru.</td></tr>'}</tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/ceo_mudaraba_list')
def ceo_mudaraba_list():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 CEO Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE account_type='MUDARABA' AND status='ACTIVE'")
    custs = cursor.fetchall()
    conn.close()
    rows = ""
    total = 0.0
    for c in custs:
        bal = c['balance']
        total += bal
        cust_profit = (bal * 0.10) * 0.50
        ceo_profit = (bal * 0.10) * 0.50
        rows += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px;">{c['customer_id']}</td>
            <td style="padding:8px;">{c['full_name']}</td>
            <td style="padding:8px; color:#065f46;">{bal:,.2f}</td>
            <td style="padding:8px; color:#6b21a8;">+{cust_profit:,.2f}</td>
            <td style="padding:8px; color:#047857;">+{ceo_profit:,.2f}</td>
        </tr>"""
    content = f"""
    <div class="card-ceo-profit">
        <div class="net-title">🔒 Mudaraba 50/50</div>
        <div class="net-amount">{total:,.2f} Birr</div>
    </div>
    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%;">
            <thead><tr style="background:#f8fafc; font-size:11px;">
                <th style="padding:8px;">Acc</th><th style="padding:8px;">Maqaa</th>
                <th style="padding:8px;">Balance</th><th style="padding:8px;">Cust 50%</th>
                <th style="padding:8px;">CEO 50%</th>
            </tr></thead>
            <tbody>{rows or '<tr><td colspan="5" style="text-align:center; padding:16px;">Hin jiru.</td></tr>'}</tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/manage_users', methods=['GET', 'POST'])
def manage_users():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 CEO Qofa!", 403
    msg = None
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        action = request.form.get('action')
        uname = request.form.get('username')
        if action == 'add':
            try:
                cursor.execute("INSERT INTO users (username, password, role, status) VALUES (?, ?, ?, 'ACTIVE')",
                               (uname, request.form.get('password', '').strip(), request.form.get('role')))
                conn.commit()
                msg = f"✅ {uname} galmaa'eera!"
            except Exception:
                msg = f"❌ Username '{uname}' duraan jira!"
        elif action == 'change_role':
            cursor.execute("UPDATE users SET role = ? WHERE username = ?", (request.form.get('new_role'), uname))
            conn.commit()
            msg = f"🔄 Role jijjiirameera."
        elif action == 'reset_password':
            pwd = request.form.get('new_password', '').strip()
            if pwd:
                cursor.execute("UPDATE users SET password = ? WHERE username = ?", (pwd, uname))
                conn.commit()
                msg = f"🔑 Password reset!"
        elif action == 'block':
            cursor.execute("UPDATE users SET status = 'BLOCKED' WHERE username = ?", (uname,))
            conn.commit()
            msg = f"🚫 Blocked."
        elif action == 'unblock':
            cursor.execute("UPDATE users SET status = 'ACTIVE' WHERE username = ?", (uname,))
            conn.commit()
            msg = f"✅ Unblocked."

    cursor.execute("SELECT username, role, status FROM users")
    users = cursor.fetchall()
    conn.close()

    rows = ""
    for u in users:
        if u['username'] == 'ceo':
            st = '<b>Master Admin</b>'
        else:
            st = f"""
            <form method="POST" style="display:inline;"><input type="hidden" name="username" value="{u['username']}">
                <input type="hidden" name="action" value="change_role">
                <select name="new_role" onchange="this.form.submit()">
                    {''.join([f'<option value="{r}" {"selected" if u["role"]==r else ""}>{r}</option>' for r in ['MAKER','MANAGER','AUDITOR','LOAN_OFFICER','EXTERNAL_AGENT']])}
                </select>
            </form>
            <form method="POST" style="display:inline;"><input type="hidden" name="username" value="{u['username']}">
                <input type="hidden" name="action" value="reset_password">
                <input type="text" name="new_password" placeholder="pwd" style="width:70px; font-size:10px;">
                <button class="btn-action btn-blue" style="font-size:10px;">Reset</button>
            </form>
            <form method="POST" style="display:inline;"><input type="hidden" name="username" value="{u['username']}">
                <input type="hidden" name="action" value="{'unblock' if u['status']=='BLOCKED' else 'block'}">
                <button class="btn-action {'btn-green' if u['status']=='BLOCKED' else 'btn-red'}" style="font-size:10px;">{'Unblock' if u['status']=='BLOCKED' else 'Block'}</button>
            </form>
            """
        rows += f"<tr style='border-bottom:1px solid #e2e8f0; font-size:12px;'><td style='padding:8px;'>{u['username']}</td><td style='padding:8px;'><span class='role-badge'>{u['role']}</span></td><td style='padding:8px;'>{u['status']}</td><td style='padding:8px; text-align:right;'>{st}</td></tr>"

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#581c87;">⚙️ Bulchiinsa Hojjattootaa</h2>
        {f"<p style='background:#dcfce7; padding:10px;'>{msg}</p>" if msg else ""}
        <form method="POST" style="margin-bottom:20px;">
            <input type="hidden" name="action" value="add">
            <div class="form-group"><label>Username</label><input type="text" name="username" required class="input-field"></div>
            <div class="form-group"><label>Password</label><input type="password" name="password" required class="input-field"></div>
            <div class="form-group"><label>Role</label>
                <select name="role" class="input-field">
                    <option value="MAKER">MAKER</option><option value="MANAGER">MANAGER</option>
                    <option value="AUDITOR">AUDITOR</option><option value="LOAN_OFFICER">LOAN_OFFICER</option>
                    <option value="EXTERNAL_AGENT">EXTERNAL_AGENT</option>
                </select>
            </div>
            <button type="submit" class="btn-submit" style="background:#7c3aed;">➕ Uumi</button>
        </form>
        <table style="width:100%;">
            <thead><tr style="background:#f8fafc; font-size:11px;">
                <th style="padding:8px;">Username</th><th style="padding:8px;">Role</th>
                <th style="padding:8px;">Status</th><th style="padding:8px; text-align:right;">Actions</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# EXTERNAL AGENT
# ================================================================
@app.route('/agent_register', methods=['GET', 'POST'])
def agent_register():
    if 'role' not in session or session['role'] != 'EXTERNAL_AGENT':
        return "🚫 External Agent Qofa!", 403
    msg = None
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        gender = request.form.get('gender', 'Dhiira')
        account_type = request.form.get('account_type', 'WADIA')
        initial_balance = max(0.0, float(request.form.get('initial_balance', 0.0)))
        photo_file = request.files.get('photo')
        sig_file = request.files.get('signature')

        if photo_file and sig_file and allowed_file(photo_file.filename) and allowed_file(sig_file.filename):
            ts = int(datetime.datetime.now().timestamp())
            photo_name = compress_and_save_image(photo_file, f"agent_face_{ts}_" + secure_filename(photo_file.filename))
            sig_name = compress_and_save_image(sig_file, f"agent_sig_{ts}_" + secure_filename(sig_file.filename))

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(CAST(customer_id AS BIGINT)) FROM customers WHERE customer_id >= '100099008800'")
            max_id = cursor.fetchone()[0]
            START_ID = 100099008800
            cust_id = str(START_ID) if max_id is None or max_id < START_ID else str(max_id + 1)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                INSERT INTO customers (customer_id, full_name, phone, gender, account_type,
                    photo_path, signature_path, balance, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 'PENDING_APPROVAL', ?)
            """, (cust_id, full_name, phone, gender, account_type, photo_name, sig_name, now))

            if initial_balance > 0:
                ft_ref = f"AGNT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
                agent_comm = round(initial_balance * 0.10, 2)
                txn_id = f"TXN-AGENT-{ts}-{random.randint(1000, 9999)}"
                cursor.execute("""
                    INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name,
                        amount, commission, bank_name, ft_reference, status, created_by, timestamp)
                    VALUES (?, 'DEPOSIT', ?, ?, ?, ?, 'External Agent Branch', ?, 'PENDING_MANAGER', ?, ?)
                """, (txn_id, cust_id, full_name, initial_balance, agent_comm, ft_ref, session['username'], now))

            conn.commit()
            conn.close()
            msg = f"✅ {full_name} galmaa'eera! (Acc: {cust_id})"
            add_notification(f"Agent ({session['username']}) customer created.")

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#7c3aed;">👤 External Agent: Galmee</h2>
        {f"<p style='background:#dcfce7; padding:10px;'>{msg}</p>" if msg else ""}
        <form method="POST" enctype="multipart/form-data">
            <div class="form-group"><label>Maqaa</label><input type="text" name="full_name" required class="input-field"></div>
            <div class="form-group"><label>Phone</label><input type="text" name="phone" required class="input-field"></div>
            <div class="form-group"><label>Saala</label><select name="gender" class="input-field"><option>Dhiira</option><option>Dubartii</option></select></div>
            <div class="form-group"><label>Type</label>
                <select name="account_type" class="input-field">
                    <option value="WADIA">WADIA</option><option value="MUDARABA">MUDARABA</option>
                </select>
            </div>
            <div class="form-group"><label>Initial Balance</label><input type="number" step="0.01" min="0" name="initial_balance" value="0.00" required class="input-field"></div>
            <div class="form-group"><label>📸 Suuraa</label><input type="file" name="photo" accept="image/*" required class="input-field"></div>
            <div class="form-group"><label>✍️ Mallattoo</label><input type="file" name="signature" accept="image/*" required class="input-field"></div>
            <button type="submit" class="btn-submit" style="background:#7c3aed;">💾 Galmeessi</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/agent_transaction', methods=['GET', 'POST'])
def agent_transaction():
    if 'role' not in session or session['role'] != 'EXTERNAL_AGENT':
        return "🚫 External Agent Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name FROM customers WHERE status='ACTIVE'")
    customers = cursor.fetchall()
    msg = None
    if request.method == 'POST':
        cust_id = request.form.get('customer_id')
        amount = float(request.form.get('amount', 0))
        txn_type = request.form.get('txn_type')
        cursor.execute("SELECT full_name FROM customers WHERE customer_id = ?", (cust_id,))
        cust = cursor.fetchone()
        if cust and amount > 0:
            agent_comm = round(amount * 0.10, 2)
            ts = int(datetime.datetime.now().timestamp())
            ft_ref = f"AGTX{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            txn_id = f"TXN-AGNT-{ts}-{random.randint(1000, 9999)}"
            cursor.execute("""
                INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name,
                    amount, commission, bank_name, ft_reference, status, created_by, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, 'External Agent Branch', ?, 'PENDING_MANAGER', ?, ?)
            """, (txn_id, txn_type, cust_id, cust['full_name'], amount, agent_comm, ft_ref, session['username'], now))
            conn.commit()
            msg = f"✅ {txn_type} {amount:,.2f} Birr galmaa'eera (10% Comm: {agent_comm:,.2f})."
    conn.close()
    options = "".join([f'<option value="{c["customer_id"]}">{c["full_name"]}</option>' for c in customers])
    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#7c3aed;">💸 Agent Transaction</h2>
        {f"<p style='background:#dcfce7; padding:10px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group"><label>Gosa</label>
                <select name="txn_type" class="input-field">
                    <option value="DEPOSIT">Deposit</option>
                    <option value="WITHDRAWAL">Withdrawal</option>
                </select>
            </div>
            <div class="form-group"><label>Maammila</label>
                <select name="customer_id" class="input-field" required>{options}</select>
            </div>
            <div class="form-group"><label>Amount</label><input type="number" step="0.01" name="amount" required class="input-field"></div>
            <button type="submit" class="btn-submit" style="background:#7c3aed;">⚡ Ergi</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# ISLAMIC LOAN
# ================================================================
@app.route('/islamic_loan', methods=['GET', 'POST'])
def islamic_loan():
    if 'role' not in session or session['role'] not in ['LOAN_OFFICER', 'CEO', 'MANAGER']:
        return "🚫 Hayyama Qofa!", 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name FROM customers WHERE status='ACTIVE'")
    customers = cursor.fetchall()
    msg = None
    if request.method == 'POST':
        cust_id = request.form.get('customer_id')
        fin_type = request.form.get('financing_type')
        principal = float(request.form.get('principal_amount', 0))
        tenure = int(request.form.get('tenure_months', 12))
        notes = request.form.get('agent_notes', '')
        cursor.execute("SELECT full_name FROM customers WHERE customer_id = ?", (cust_id,))
        cust = cursor.fetchone()
        if cust and principal > 0:
            profit_margin = principal * 0.05 * (tenure / 12)
            total_repay = principal + profit_margin
            monthly = total_repay / tenure
            loan_id = f"LOAN-{int(datetime.datetime.now().timestamp())}"
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO islamic_financing (loan_id, customer_id, customer_name, financing_type,
                    principal_amount, profit_margin, total_repayment, tenure_months,
                    monthly_installment, agent_notes, created_by, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (loan_id, cust_id, cust['full_name'], fin_type, principal, profit_margin,
                  total_repay, tenure, monthly, notes, session['username'], now))
            conn.commit()
            msg = f"✅ Loan {loan_id} galmaa'eera!"
    cursor.execute("SELECT * FROM islamic_financing ORDER BY timestamp DESC LIMIT 50")
    loans = cursor.fetchall()
    conn.close()
    options = "".join([f'<option value="{c["customer_id"]}">{c["full_name"]}</option>' for c in customers])
    loans_html = ""
    for l in loans:
        loans_html += f"""
        <div class="item-card">
            <div style="font-size:12px; font-weight:bold; color:#15803d;">{l['financing_type']} | {l['loan_id']}</div>
            <div style="font-size:12px;">{l['customer_name']} — {l['principal_amount']:,.2f} Birr / {l['tenure_months']} months</div>
            <div style="font-size:11px;">Status: {l['status']} | Monthly: {l['monthly_installment']:,.2f}</div>
        </div>"""
    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#15803d;">📜 Islamic Financing</h2>
        {f"<p style='background:#dcfce7; padding:10px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group"><label>Gosa</label>
                <select name="financing_type" class="input-field">
                    <option value="MUDARABA_FINANCING">Mudaraba</option>
                    <option value="MURABAHA_GOODS">Murabaha</option>
                </select>
            </div>
            <div class="form-group"><label>Maammila</label><select name="customer_id" class="input-field" required>{options}</select></div>
            <div class="form-group"><label>Principal</label><input type="number" step="0.01" name="principal_amount" required class="input-field"></div>
            <div class="form-group"><label>Tenure (months)</label><input type="number" name="tenure_months" value="12" required class="input-field"></div>
            <div class="form-group"><label>Notes</label><textarea name="agent_notes" rows="2" class="input-field"></textarea></div>
            <button type="submit" class="btn-submit" style="background:#15803d;">🚀 Galmeessi</button>
        </form>
    </div>
    <div class="box">
        <h3 style="font-size:13px;">📋 Tarree</h3>
        {loans_html or '<p style="font-size:12px;">Hin jiru.</p>'}
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# MOBILE BANKING
# ================================================================
@app.route('/mobile_login', methods=['GET', 'POST'])
def mobile_login():
    msg = None
    if request.method == 'POST':
        cust_id = request.form.get('customer_id', '').strip()
        pin = request.form.get('mobile_pin', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT customer_id, full_name, phone, balance, status, freeze_status, mobile_pin, mobile_status FROM customers WHERE customer_id = ?", (cust_id,))
        cust = cursor.fetchone()
        conn.close()

        if cust:
            if cust['status'] != 'ACTIVE':
                msg = "❌ Akkaawunttiin mirkanaa'uu qaba."
            elif cust['mobile_status'] == 'PENDING_APPROVAL':
                msg = "⏱️ Mobile Banking gaaffiin Manager eegaa jira."
            elif cust['mobile_status'] != 'ACTIVE':
                msg = "❌ Mobile Banking hin banamne."
            elif cust['freeze_status'] == 'FROZEN':
                msg = "🚫 Akkaawunttiin uggurameera."
            elif cust['mobile_pin'] != pin:
                msg = "❌ PIN dogoggoraa!"
            else:
                session.clear()
                session['mobile_cust_id'] = cust['customer_id']
                session['mobile_name'] = cust['full_name']
                session['mobile_phone'] = cust['phone']
                session['mobile_last_check'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return redirect('/mobile_dashboard')
        else:
            msg = "❌ Akkaawuntii hin argamne!"

    content = f"""
    <div class="box" style="margin-top:20px; text-align:center;">
        <div style="font-size:45px; margin-bottom:10px;">📱</div>
        <h2 style="font-size:18px; color:#1e3a8a;">Mobile Banking</h2>
        {f"<p style='background:#fee2e2; color:#991b1b; padding:10px; border-radius:8px; font-size:12px; margin-bottom:12px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group" style="text-align:left;">
                <label>Account No</label>
                <input type="text" name="customer_id" placeholder="100099008800" class="input-field" required>
            </div>
            <div class="form-group" style="text-align:left;">
                <label>PIN (default: 1234)</label>
                <input type="password" name="mobile_pin" maxlength="6" class="input-field" required>
            </div>
            <button type="submit" class="btn-submit" style="background:#1d4ed8;">📲 Seeni</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/mobile_logout')
def mobile_logout():
    session.clear()
    return redirect('/mobile_login')


@app.route('/mobile_dashboard')
def mobile_dashboard():
    if 'mobile_cust_id' not in session:
        return redirect('/mobile_login')

    cust_id = session['mobile_cust_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, phone, balance, account_type FROM customers WHERE customer_id = ?", (cust_id,))
    cust = cursor.fetchone()
    cursor.execute("SELECT txn_id, txn_type, amount, bank_name, status, timestamp, ft_reference FROM transactions WHERE customer_id = ? ORDER BY timestamp DESC LIMIT 5", (cust_id,))
    recent = cursor.fetchall()

    play_incoming = False
    last_check = session.get('mobile_last_check') or '1970-01-01 00:00:00'
    cursor.execute(
        "SELECT COUNT(*) FROM transactions WHERE customer_id = ? AND txn_type = 'MOBILE_TOPUP_REC' AND status = 'APPROVED' AND timestamp > ?",
        (cust_id, last_check)
    )
    if (cursor.fetchone()[0] or 0) > 0:
        play_incoming = True
    session['mobile_last_check'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.close()

    rows = ""
    for t in recent:
        color = "#16a34a" if t['txn_type'] in ['DEPOSIT', 'MOBILE_TOPUP_REC'] else "#dc2626"
        sign = "+" if t['txn_type'] in ['DEPOSIT', 'MOBILE_TOPUP_REC'] else "-"
        rows += f"""
        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f5f9; font-size:12px;">
            <div><b>{t['txn_type']}</b><div style="font-size:10px; color:#64748b;">{t['timestamp']}</div></div>
            <div style="text-align:right;"><b style="color:{color};">{sign}{t['amount']:,.2f}</b></div>
        </div>"""

    sound_script = "window.addEventListener('DOMContentLoaded', playAlertSound);" if play_incoming else ""

    content = f"""
    <div class="card-mobile-header">
        <div class="net-title">Baga Nagaan Dhuftan 👋</div>
        <div style="font-size:20px; font-weight:bold;">{cust['full_name']}</div>
        <div style="font-size:11px; opacity:0.9;">Acc: <b>{cust['customer_id']}</b> ({cust['account_type']})</div>
        <div style="margin-top:16px; border-top:1px solid rgba(255,255,255,0.2); padding-top:12px;">
            <div class="net-title">Current Balance</div>
            <div class="net-amount">{cust['balance']:,.2f} Birr</div>
        </div>
    </div>
    <h3 style="font-size:14px; margin-bottom:10px;">⚡ Tajaajila</h3>
    <div class="grid-2" style="margin-bottom:20px;">
        <a href="/mobile_transfer" class="btn-card btn-card-mobile"><span class="icon">🔄</span><span>Transfer</span></a>
        <a href="/mobile_rtgs" class="btn-card btn-card-mobile"><span class="icon">🏛️</span><span>RTGS Bank</span></a>
        <a href="/mobile_topup" class="btn-card btn-card-mobile"><span class="icon">⚡</span><span>Wallet/Topup</span></a>
        <a href="/mobile_statement" class="btn-card btn-card-mobile"><span class="icon">📜</span><span>Statement</span></a>
        <a href="/mobile_change_pin" class="btn-card btn-card-mobile"><span class="icon">🔑</span><span>PIN Jijjiiri</span></a>
    </div>
    <div class="box">
        <h3 style="font-size:13px; margin-bottom:10px;">📊 Recent Transactions</h3>
        {rows or '<p style="text-align:center; color:#94a3b8;">Hin jiru.</p>'}
    </div>

    <script>
    var _lastCheck = "{session.get('mobile_last_check', '')}";
    {sound_script}
    setInterval(function() {{
        fetch('/api/check_new_transactions?since=' + encodeURIComponent(_lastCheck))
            .then(r => r.json())
            .then(d => {{ if (d.success && d.new_count > 0) playAlertSound();
                          if (d.server_time) _lastCheck = d.server_time; }})
            .catch(() => {{}});
    }}, 20000);
    </script>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/mobile_transfer', methods=['GET', 'POST'])
def mobile_transfer():
    if 'mobile_cust_id' not in session:
        return redirect('/mobile_login')

    msg = None
    sender_id = session['mobile_cust_id']

    if request.method == 'POST':
        target_acc = request.form.get('target_account', '').strip()
        amount = float(request.form.get('amount', 0.0))
        pin = request.form.get('pin', '').strip()
        reason = request.form.get('reason', 'Mobile Internal Transfer')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT customer_id, balance, mobile_pin, freeze_status, full_name FROM customers WHERE customer_id = ?", (sender_id,))
        sender = cursor.fetchone()
        cursor.execute("SELECT customer_id, full_name, status, freeze_status FROM customers WHERE customer_id = ?", (target_acc,))
        receiver = cursor.fetchone()

        if not sender or sender['mobile_pin'] != pin:
            msg = "❌ PIN dogoggoraa!"
        elif sender['freeze_status'] == 'FROZEN':
            msg = "🚫 Akkaawuntiin uggurameera."
        elif not receiver or receiver['status'] != 'ACTIVE':
            msg = "❌ Simataa hin argamne ykn active miti!"
        elif receiver['freeze_status'] == 'FROZEN':
            msg = "❌ Simataan uggurameera!"
        elif target_acc == sender_id:
            msg = "❌ Ofii keessanitti erguu hin dandeessan!"
        elif amount <= 0:
            msg = "❌ Hamma sirrii galchaa!"
        elif sender['balance'] < amount:
            msg = "❌ Balance gahaa hin qabdan!"
        else:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ft_ref = f"FT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
            txn_out_id = f"TXN-MOB-{random.randint(100000, 999999)}"
            txn_in_id = f"TXN-MOB-REC-{random.randint(100000, 999999)}"

            cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amount, sender_id))
            cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (amount, target_acc))

            cursor.execute("""
                INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account,
                    amount, commission, bank_name, ft_reference, status, created_by, timestamp, reason)
                VALUES (?, 'T24_TRANSFER', ?, ?, ?, ?, 0.0, 'Imana Microfinance', ?, 'APPROVED', 'MOBILE_APP', ?, ?)
            """, (txn_out_id, sender_id, sender['full_name'], target_acc, amount, ft_ref, now, reason))

            cursor.execute("""
                INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account,
                    amount, commission, bank_name, ft_reference, status, created_by, timestamp, reason)
                VALUES (?, 'MOBILE_TOPUP_REC', ?, ?, ?, ?, 0.0, 'Imana Microfinance', ?, 'APPROVED', 'MOBILE_APP', ?, ?)
            """, (txn_in_id, target_acc, receiver['full_name'], sender_id, amount, ft_ref, now, f"Irraa: {sender['full_name']}"))

            conn.commit()
            conn.close()

            add_notification(f"Mobile Transfer: {sender['full_name']} → {receiver['full_name']} ({amount:,.2f}).")
            return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", f"""
                <div class="box" style="text-align:center;">
                    <div style="font-size:50px;">✅</div>
                    <h2 style="color:#166534; font-size:18px;">Dabarsii Milkaa'inaa!</h2>
                    <p style="margin-top:8px;">Hamma: <b>{amount:,.2f} Birr</b></p>
                    <p style="font-size:12px; color:#64748b;">Simataa: <b>{receiver['full_name']}</b> ({target_acc})</p>
                    <p style="font-size:11px; color:#94a3b8;">Ref: <b>{ft_ref}</b></p>
                    <a href="/mobile_dashboard" class="btn-submit" style="display:block; margin-top:16px; text-decoration:none; background:#2563eb;">Gara Dashboard</a>
                    <script>window.addEventListener('DOMContentLoaded', playAlertSound);</script>
                </div>
            """), notifications=NOTIFICATIONS)

        conn.close()

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#1e3a8a;">🔄 Transfer</h2>
        {f"<p style='background:#fee2e2; color:#991b1b; padding:10px; border-radius:8px; font-size:12px;'>{msg}</p>" if msg else ""}
        <form method="POST" onsubmit="return checkVerification();">
            <div class="form-group">
                <label>Lakkoofsa Akkaawuntii Simataa</label>
                <input type="text" name="target_account" id="target_account_input" oninput="debouncedVerify(this)" placeholder="100099008800" class="input-field" required autocomplete="off">
                <div id="verify_status" style="margin-top:8px;"></div>
            </div>
            <div class="form-group"><label>Hamma (Birr)</label><input type="number" step="0.01" min="1" name="amount" required class="input-field"></div>
            <div class="form-group"><label>Sababa</label><input type="text" name="reason" class="input-field"></div>
            <div class="form-group"><label>PIN</label><input type="password" name="pin" maxlength="6" required class="input-field"></div>
            <button type="submit" class="btn-submit" style="background:#2563eb;">🚀 Dabarsi</button>
        </form>
    </div>
    <script>
    var _lastVerifiedAcc = null;
    var _verifyTimer = null;
    function debouncedVerify(input) {{
        clearTimeout(_verifyTimer);
        var acc = input.value.trim();
        _lastVerifiedAcc = null;
        if (acc.length < 6) {{ document.getElementById('verify_status').innerHTML = ''; return; }}
        _verifyTimer = setTimeout(() => verifyAccount(acc), 400);
    }}
    function verifyAccount(acc) {{
        var box = document.getElementById('verify_status');
        box.innerHTML = '<span style="color:#64748b;">🔍 Verify jira...</span>';
        fetch('/api/get_customer/' + encodeURIComponent(acc))
            .then(r => r.json())
            .then(d => {{
                if (d.success) {{
                    _lastVerifiedAcc = acc;
                    var photoUrl = d.photo_path ? ('/uploads/' + d.photo_path) : '';
                    var photoHtml = photoUrl
                        ? '<img src="' + photoUrl + '" style="width:56px;height:56px;border-radius:50%;object-fit:cover;border:2px solid #16a34a;">'
                        : '<div style="width:56px;height:56px;border-radius:50%;background:#e2e8f0;display:flex;align-items:center;justify-content:center;font-size:20px;">👤</div>';
                    var frozenWarn = d.freeze_status === 'FROZEN'
                        ? '<div style="background:#fee2e2;color:#991b1b;padding:6px;border-radius:6px;margin-top:6px;font-weight:bold;">🚫 FROZEN!</div>' : '';
                    box.innerHTML =
                        '<div style="display:flex;gap:10px;align-items:center;background:#f0fdf4;border:1px solid #86efac;padding:10px;border-radius:8px;">' +
                            photoHtml +
                            '<div style="font-size:12px;">' +
                                '<div style="color:#166534;font-weight:bold;">✅ ' + d.full_name + '</div>' +
                                '<div>📞 ' + d.phone + '</div>' +
                                '<div>Acc: ' + d.customer_id + '</div>' +
                            '</div></div>' + frozenWarn;
                }} else {{
                    _lastVerifiedAcc = null;
                    box.innerHTML = '<div style="background:#fee2e2;color:#991b1b;padding:10px;border-radius:8px;font-size:12px;font-weight:bold;">❌ Akkaawuntii hin argamne!</div>';
                }}
            }})
            .catch(() => {{ _lastVerifiedAcc = null; }});
    }}
    function checkVerification() {{
        var acc = document.getElementById('target_account_input').value.trim();
        if (acc.length >= 6 && _lastVerifiedAcc !== acc) {{
            alert('Maqaa fi suuraa simataa duraan verify godhaa!');
            return false;
        }}
        return true;
    }}
    </script>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/mobile_rtgs', methods=['GET', 'POST'])
def mobile_rtgs():
    if 'mobile_cust_id' not in session:
        return redirect('/mobile_login')
    msg = None
    sender_id = session['mobile_cust_id']
    if request.method == 'POST':
        selected_bank = request.form.get('bank_name')
        target_acc = request.form.get('target_account', '').strip()
        target_name = request.form.get('target_name', '').strip()
        amount = float(request.form.get('amount', 0.0))
        pin = request.form.get('pin', '').strip()
        rtgs_fee = 10.0
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT customer_id, balance, mobile_pin, freeze_status, full_name FROM customers WHERE customer_id = ?", (sender_id,))
        sender = cursor.fetchone()
        total = amount + rtgs_fee
        if not sender or sender['mobile_pin'] != pin:
            msg = "❌ PIN dogoggoraa!"
        elif sender['freeze_status'] == 'FROZEN':
            msg = "🚫 Akkaawuntiin uggurameera."
        elif amount <= 0:
            msg = "❌ Hamma sirrii!"
        elif sender['balance'] < total:
            msg = f"❌ Total: {total:,.2f} (Amount {amount:,.2f} + Fee {rtgs_fee})"
        else:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ft_ref = f"RTGS{datetime.datetime.now().strftime('%y%j')}{random.randint(100000, 999999)}"
            txn_id = f"TXN-RTGS-{random.randint(100000, 999999)}"
            cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (total, sender_id))
            cursor.execute("""
                INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account,
                    amount, commission, bank_name, ft_reference, status, created_by, timestamp, reason)
                VALUES (?, 'RTGS_TRANSFER', ?, ?, ?, ?, ?, ?, ?, 'PENDING_MANAGER', 'MOBILE_APP', ?, ?)
            """, (txn_id, sender_id, sender['full_name'], target_acc, amount, rtgs_fee, selected_bank, ft_ref, now,
                  f"Gara: {selected_bank} | Simataa: {target_name} ({target_acc})"))
            conn.commit()
            conn.close()
            add_notification(f"RTGS: {sender['full_name']} → {selected_bank} ({amount:,.2f}).")
            return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", f"""
                <div class="box" style="text-align:center;">
                    <div style="font-size:50px;">🏛️</div>
                    <h2 style="color:#065f46;">RTGS Ergameera!</h2>
                    <div style="background:#f8fafc; padding:12px; border-radius:8px; margin:12px 0; text-align:left; font-size:12px;">
                        <div>Bankii: <b>{selected_bank}</b></div>
                        <div>Maqaa Simataa: <b>{target_name}</b></div>
                        <div>Acc: <b>{target_acc}</b></div>
                        <div>Amount: <b>{amount:,.2f} Birr</b></div>
                        <div>Fee: <b>{rtgs_fee:,.2f} Birr</b></div>
                        <div>Ref: <b>{ft_ref}</b></div>
                    </div>
                    <p style="font-size:11px; color:#92400e; background:#fef3c7; padding:6px; border-radius:4px;">⏱️ Manager approval eegaa jira</p>
                    <a href="/mobile_dashboard" class="btn-submit" style="display:block; margin-top:16px; text-decoration:none; background:#047857;">Gara Dashboard</a>
                </div>
            """), notifications=NOTIFICATIONS)
        conn.close()

    bank_options = "".join([f"<option value='{b}'>{b}</option>" for b in ETHIOPIAN_BANKS])
    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46;">🏛️ RTGS Interbank</h2>
        {f"<p style='background:#fee2e2; color:#991b1b; padding:10px; border-radius:8px; font-size:12px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group"><label>Bankii</label><select name="bank_name" class="input-field" required>{bank_options}</select></div>
            <div class="form-group"><label>Maqaa Simataa</label><input type="text" name="target_name" required class="input-field"></div>
            <div class="form-group"><label>Account Simataa</label><input type="text" name="target_account" required class="input-field"></div>
            <div class="form-group"><label>Amount (min 10)</label><input type="number" step="0.01" min="10" name="amount" required class="input-field"></div>
            <div class="form-group"><label>PIN</label><input type="password" name="pin" maxlength="6" required class="input-field"></div>
            <button type="submit" class="btn-submit" style="background:#047857;">🏛️ Ergi RTGS</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/mobile_topup', methods=['GET', 'POST'])
def mobile_topup():
    if 'mobile_cust_id' not in session:
        return redirect('/mobile_login')
    msg = None
    sender_id = session['mobile_cust_id']
    if request.method == 'POST':
        topup_type = request.form.get('topup_type')
        phone = request.form.get('phone', '').strip()
        amount = float(request.form.get('amount', 0.0))
        pin = request.form.get('pin', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT customer_id, balance, mobile_pin, freeze_status, full_name FROM customers WHERE customer_id = ?", (sender_id,))
        sender = cursor.fetchone()
        if not sender or sender['mobile_pin'] != pin:
            msg = "❌ PIN dogoggoraa!"
        elif sender['freeze_status'] == 'FROZEN':
            msg = "🚫 Uggurameera."
        elif amount <= 0:
            msg = "❌ Hamma sirrii!"
        elif sender['balance'] < amount:
            msg = "❌ Balance gahaa miti!"
        else:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ft_ref = f"TP{datetime.datetime.now().strftime('%y%j')}{random.randint(100000, 999999)}"
            txn_id = f"TXN-TOPUP-{random.randint(100000, 999999)}"
            cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amount, sender_id))
            cursor.execute("""
                INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account,
                    amount, commission, bank_name, ft_reference, status, created_by, timestamp, reason)
                VALUES (?, 'WALLET_TOPUP', ?, ?, ?, ?, 0.0, ?, ?, 'APPROVED', 'MOBILE_APP', ?, ?)
            """, (txn_id, sender_id, sender['full_name'], phone, amount, topup_type, ft_ref, now,
                  f"Topup: {topup_type} → {phone}"))
            conn.commit()
            conn.close()
            add_notification(f"Topup: {sender['full_name']} {topup_type} ({amount:,.2f}).")
            return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", f"""
                <div class="box" style="text-align:center;">
                    <div style="font-size:50px;">⚡</div>
                    <h2 style="color:#166534;">Topup Milkaa'eera!</h2>
                    <p><b>{topup_type}</b> → {phone}</p>
                    <p style="font-size:16px; font-weight:bold; color:#047857;">{amount:,.2f} Birr</p>
                    <p style="font-size:11px;">Ref: <b>{ft_ref}</b></p>
                    <a href="/mobile_dashboard" class="btn-submit" style="display:block; margin-top:16px; text-decoration:none; background:#7c3aed;">Gara Dashboard</a>
                </div>
            """), notifications=NOTIFICATIONS)
        conn.close()

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#7c3aed;">⚡ Wallet & Airtime Topup</h2>
        {f"<p style='background:#fee2e2; color:#991b1b; padding:10px; border-radius:8px; font-size:12px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group"><label>Tajaajila</label>
                <select name="topup_type" class="input-field" required>
                    <option value="TELEBIRR_WALLET">Telebirr</option>
                    <option value="CBE_BIRR_WALLET">CBE Birr</option>
                    <option value="SAFARICOM_MPESA">M-PESA</option>
                    <option value="ETHIO_TELECOM_AIRTIME">Ethio Telecom Airtime</option>
                    <option value="SAFARICOM_AIRTIME">Safaricom Airtime</option>
                </select>
            </div>
            <div class="form-group"><label>Phone</label><input type="text" name="phone" value="{session.get('mobile_phone', '')}" required class="input-field"></div>
            <div class="form-group"><label>Hamma</label><input type="number" step="1" min="5" name="amount" required class="input-field"></div>
            <div class="form-group"><label>PIN</label><input type="password" name="pin" maxlength="6" required class="input-field"></div>
            <button type="submit" class="btn-submit" style="background:#7c3aed;">⚡ Topup</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/mobile_statement')
def mobile_statement():
    if 'mobile_cust_id' not in session:
        return redirect('/mobile_login')
    cust_id = session['mobile_cust_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
    cust = cursor.fetchone()
    cursor.execute("SELECT * FROM transactions WHERE customer_id = ? ORDER BY timestamp DESC", (cust_id,))
    txns = cursor.fetchall()
    conn.close()
    rows = ""
    for t in txns:
        color = "#16a34a" if t['txn_type'] in ['DEPOSIT', 'MOBILE_TOPUP_REC'] else "#dc2626"
        sign = "+" if t['txn_type'] in ['DEPOSIT', 'MOBILE_TOPUP_REC'] else "-"
        rows += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:6px;">{t['timestamp']}</td>
            <td style="padding:6px;">{t['ft_reference']}</td>
            <td style="padding:6px;">{t['txn_type']}</td>
            <td style="padding:6px; color:{color};"><b>{sign}{t['amount']:,.2f}</b></td>
            <td style="padding:6px;"><span class="badge badge-active">{t['status']}</span></td>
        </tr>"""
    content = f"""
    <div class="box">
        <h2 style="font-size:16px;">📜 Statement</h2>
        <p style="font-size:12px;">{cust['full_name']} ({cust['customer_id']})</p>
        <p style="font-size:14px; color:#16a34a; font-weight:bold;">Balance: {cust['balance']:,.2f} Birr</p>
        <button onclick="window.print()" class="btn-action btn-purple no-print" style="margin-top:8px;">🖨️ Print</button>
    </div>
    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse;">
            <thead><tr style="background:#f8fafc; font-size:11px;">
                <th style="padding:6px;">Guyyaa</th><th style="padding:6px;">Ref</th>
                <th style="padding:6px;">Type</th><th style="padding:6px;">Amount</th>
                <th style="padding:6px;">Status</th>
            </tr></thead>
            <tbody>{rows or '<tr><td colspan="5" style="text-align:center; padding:16px;">Hin jiru.</td></tr>'}</tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


@app.route('/mobile_change_pin', methods=['GET', 'POST'])
def mobile_change_pin():
    if 'mobile_cust_id' not in session:
        return redirect('/mobile_login')
    msg, msg_type = None, "green"
    cust_id = session['mobile_cust_id']
    if request.method == 'POST':
        old_pin = request.form.get('old_pin', '').strip()
        new_pin = request.form.get('new_pin', '').strip()
        confirm = request.form.get('confirm_pin', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT mobile_pin FROM customers WHERE customer_id = ?", (cust_id,))
        cust = cursor.fetchone()
        if not cust or cust['mobile_pin'] != old_pin:
            msg, msg_type = "❌ PIN duraanii dogoggoraa!", "red"
        elif new_pin != confirm:
            msg, msg_type = "❌ PIN haaraa fi confirm wal hin simne!", "red"
        elif len(new_pin) != 4 or not new_pin.isdigit():
            msg, msg_type = "❌ PIN digiti 4 ta'uu qaba!", "red"
        else:
            cursor.execute("UPDATE customers SET mobile_pin = ? WHERE customer_id = ?", (new_pin, cust_id))
            conn.commit()
            msg = "✅ PIN jijjiirameera!"
        conn.close()

    content = f"""
    <div class="box">
        <h2 style="font-size:16px;">🔑 PIN Jijjiiri</h2>
        {f"<p style='background:{'#dcfce7' if msg_type=='green' else '#fee2e2'}; color:{'#166534' if msg_type=='green' else '#991b1b'}; padding:10px; border-radius:6px; font-size:12px;'>{msg}</p>" if msg else ""}
        <form method="POST">
            <div class="form-group"><label>PIN Duraanii</label><input type="password" name="old_pin" maxlength="6" required class="input-field"></div>
            <div class="form-group"><label>PIN Haaraa (4 digit)</label><input type="password" name="new_pin" maxlength="4" required class="input-field"></div>
            <div class="form-group"><label>Confirm PIN</label><input type="password" name="confirm_pin" maxlength="4" required class="input-field"></div>
            <button type="submit" class="btn-submit" style="background:#1d4ed8;">💾 Jijjiiri</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)


# ================================================================
# ENTRY POINT
# ================================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
