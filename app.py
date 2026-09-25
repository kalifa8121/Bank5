import os
import random
import datetime
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, request, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "imana_microfinance_secret_key")

# --- DATABASE CONNECTION ---
def get_db_connection():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Maammiltoota (Customers)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            balance REAL DEFAULT 0.0,
            status TEXT DEFAULT 'ACTIVE',
            freeze_status TEXT DEFAULT 'UNFROZEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Galmee Kaffaltii (Transactions)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
            txn_type TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            customer_name TEXT,
            target_account TEXT,
            target_bank TEXT DEFAULT 'INTERNAL',
            amount REAL NOT NULL,
            ft_reference TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'APPROVED',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 3. Reversals Table (Auditor, Manager, CEO Approval)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reversals (
            reversal_id TEXT PRIMARY KEY,
            txn_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_by_auditor TEXT NOT NULL,
            manager_approved BOOLEAN DEFAULT FALSE,
            ceo_approved BOOLEAN DEFAULT FALSE,
            status TEXT DEFAULT 'PENDING_APPROVAL',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

# Database Table-wwan uumuu
try:
    init_db()
except Exception as e:
    print(f"Database Initialization Error: {e}")


# --- 1. HOME & HEALTH CHECK ENDPOINTS (RENDER 404 FIX) ---

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return jsonify({
        'status': 'online',
        'message': 'Imaanaa Mobile Banking API Server is running successfully!'
    }), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200


# --- 2. MOBILE APP ENDPOINTS ---

# Seensa Maammilaa (Login)
@app.route('/api/mobile/login', methods=['POST'])
def mobile_login():
    data = request.json or {}
    phone = data.get('phone')
    password = data.get('password')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, phone, balance, freeze_status FROM customers WHERE phone = %s AND password = %s", (phone, password))
    user = cursor.fetchone()
    conn.close()

    if user:
        if user['freeze_status'] == 'FROZEN':
            return jsonify({'success': False, 'message': 'Akkaawuntiin keessan uggurameera!'}), 403
        return jsonify({
            'success': True,
            'user': {
                'customer_id': user['customer_id'],
                'full_name': user['full_name'],
                'phone': user['phone'],
                'balance': user['balance']
            }
        })
    return jsonify({'success': False, 'message': 'Lakkoofsa bilbilaa ykn Password dogoggoraa!'}), 401


# 1. Qarshii Walitti Erguu (Transfer - Manager Pending Malee / Immediate)
@app.route('/api/mobile/transfer', methods=['POST'])
def mobile_transfer():
    data = request.json or {}
    sender_id = data.get('sender_id')
    receiver_acc = data.get('receiver_acc')
    amount = float(data.get('amount', 0))

    if amount <= 0:
        return jsonify({'success': False, 'message': 'Hamma maallaqaa sirrii galchaa!'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT full_name, balance, freeze_status FROM customers WHERE customer_id = %s", (sender_id,))
    sender = cursor.fetchone()

    cursor.execute("SELECT full_name, freeze_status FROM customers WHERE customer_id = %s", (receiver_acc,))
    receiver = cursor.fetchone()

    if not sender or not receiver:
        conn.close()
        return jsonify({'success': False, 'message': 'Maammilli ergu ykn fudhatu hin argamne!'}), 404

    if sender['freeze_status'] == 'FROZEN':
        conn.close()
        return jsonify({'success': False, 'message': 'Akkaawuntiin keessan uggurameera!'}), 400

    if sender['balance'] < amount:
        conn.close()
        return jsonify({'success': False, 'message': 'Balansii gahaa hin qabdan!'}), 400

    # Battalatti kaffaltiin ni raawwata
    cursor.execute("UPDATE customers SET balance = balance - %s WHERE customer_id = %s", (amount, sender_id))
    cursor.execute("UPDATE customers SET balance = balance + %s WHERE customer_id = %s", (amount, receiver_acc))

    ft_ref = f"FTM{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
    txn_id = f"TXN-{int(datetime.datetime.now().timestamp())}"

    cursor.execute("""
        INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, target_bank, amount, ft_reference, status)
        VALUES (%s, 'INTERNAL_TRANSFER', %s, %s, %s, 'INTERNAL', %s, %s, 'APPROVED')
    """, (txn_id, sender_id, sender['full_name'], receiver_acc, amount, ft_ref))

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Qarshiin milkaa\'inaan ergameera!', 'ft_reference': ft_ref})


# 2. Qarshii Baafachuu (Withdrawal)
@app.route('/api/mobile/withdraw', methods=['POST'])
def mobile_withdraw():
    data = request.json or {}
    cust_id = data.get('customer_id')
    amount = float(data.get('amount', 0))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, balance FROM customers WHERE customer_id = %s", (cust_id,))
    cust = cursor.fetchone()

    if not cust or cust['balance'] < amount:
        conn.close()
        return jsonify({'success': False, 'message': 'Balansii gahaa hin qabdan!'}), 400

    cursor.execute("UPDATE customers SET balance = balance - %s WHERE customer_id = %s", (amount, cust_id))
    ft_ref = f"WTH{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
    txn_id = f"TXN-WTH-{int(datetime.datetime.now().timestamp())}"

    cursor.execute("""
        INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, amount, ft_reference, status)
        VALUES (%s, 'WITHDRAWAL', %s, %s, %s, %s, 'APPROVED')
    """, (txn_id, cust_id, cust['full_name'], amount, ft_ref))

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Qarshii baafachuun milkaa\'eera!', 'ft_reference': ft_ref})


# 3. Wallet fi Bankii Birootti Erguu (Other Bank Transfer)
@app.route('/api/mobile/other-bank-transfer', methods=['POST'])
def other_bank_transfer():
    data = request.json or {}
    sender_id = data.get('sender_id')
    target_bank = data.get('target_bank') # e.g. CBE, Telebirr, Awash
    target_acc = data.get('target_acc')
    amount = float(data.get('amount', 0))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, balance FROM customers WHERE customer_id = %s", (sender_id,))
    sender = cursor.fetchone()

    if not sender or sender['balance'] < amount:
        conn.close()
        return jsonify({'success': False, 'message': 'Balansii gahaa hin qabdan!'}), 400

    cursor.execute("UPDATE customers SET balance = balance - %s WHERE customer_id = %s", (amount, sender_id))
    ft_ref = f"EXT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
    txn_id = f"TXN-EXT-{int(datetime.datetime.now().timestamp())}"

    cursor.execute("""
        INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, target_bank, amount, ft_reference, status)
        VALUES (%s, 'OTHER_BANK_TRANSFER', %s, %s, %s, %s, %s, %s, 'APPROVED')
    """, (txn_id, sender_id, sender['full_name'], target_acc, target_bank, amount, ft_ref))

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'Gara {target_bank} kaffaltiin ergameera!', 'ft_reference': ft_ref})


# 4. ETopUp Guuttachuu (Airtime)
@app.route('/api/mobile/topup', methods=['POST'])
def mobile_topup():
    data = request.json or {}
    cust_id = data.get('customer_id')
    phone = data.get('phone')
    amount = float(data.get('amount', 0))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, balance FROM customers WHERE customer_id = %s", (cust_id,))
    cust = cursor.fetchone()

    if not cust or cust['balance'] < amount:
        conn.close()
        return jsonify({'success': False, 'message': 'Balansii gahaa hin qabdan!'}), 400

    cursor.execute("UPDATE customers SET balance = balance - %s WHERE customer_id = %s", (amount, cust_id))
    ft_ref = f"TOP{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
    txn_id = f"TXN-TOP-{int(datetime.datetime.now().timestamp())}"

    cursor.execute("""
        INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, amount, ft_reference, status)
        VALUES (%s, 'ETOPUP', %s, %s, %s, %s, %s, 'APPROVED')
    """, (txn_id, cust_id, cust['full_name'], phone, amount, ft_ref))

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'Airtime {amount} ETB bilbila {phone}-f ergameera!', 'ft_reference': ft_ref})


# 5. Haftee fi Statement Laallachuu
@app.route('/api/mobile/statement/<cust_id>', methods=['GET'])
def mobile_statement(cust_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, balance FROM customers WHERE customer_id = %s", (cust_id,))
    cust = cursor.fetchone()

    if not cust:
        conn.close()
        return jsonify({'success': False, 'message': 'Maammilli hin argamne!'}), 404

    cursor.execute("""
        SELECT txn_id, txn_type, amount, ft_reference, target_bank, target_account, timestamp 
        FROM transactions 
        WHERE customer_id = %s OR target_account = %s 
        ORDER BY timestamp DESC LIMIT 20
    """, (cust_id, cust_id))
    txns = cursor.fetchall()
    conn.close()

    history = [dict(t) for t in txns]
    return jsonify({
        'success': True,
        'customer_id': cust_id,
        'full_name': cust['full_name'],
        'balance': cust['balance'],
        'history': history
    })


# --- 3. AUDITOR, MANAGER FI CEO WORKFLOW (REVERSAL) ---

# Auditor Reversal Request Uumuu
@app.route('/api/audit/request-reversal', methods=['POST'])
def audit_request_reversal():
    data = request.json or {}
    txn_id = data.get('txn_id')
    reason = data.get('reason')
    auditor_id = data.get('auditor_id')

    reversal_id = f"REV-{int(datetime.datetime.now().timestamp())}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reversals (reversal_id, txn_id, reason, requested_by_auditor, status)
        VALUES (%s, %s, %s, %s, 'PENDING_APPROVAL')
    """, (reversal_id, txn_id, reason, auditor_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Gaaffiin Reversal Manaajeraa fi CEO-f ergameera.', 'reversal_id': reversal_id})


# Manager ykn CEO Reversal Approve Gochuu
@app.route('/api/admin/approve-reversal', methods=['POST'])
def approve_reversal():
    data = request.json or {}
    reversal_id = data.get('reversal_id')
    role = data.get('role') # 'MANAGER' ykn 'CEO'

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reversals WHERE reversal_id = %s", (reversal_id,))
    rev = cursor.fetchone()

    if not rev:
        conn.close()
        return jsonify({'success': False, 'message': 'Reversal ID hin argamne!'}), 404

    if role == 'MANAGER':
        cursor.execute("UPDATE reversals SET manager_approved = TRUE WHERE reversal_id = %s", (reversal_id,))
    elif role == 'CEO':
        cursor.execute("UPDATE reversals SET ceo_approved = TRUE WHERE reversal_id = %s", (reversal_id,))

    conn.commit()

    # Checking Status (Lameenuu Approve yoo godhan)
    cursor.execute("SELECT * FROM reversals WHERE reversal_id = %s", (reversal_id,))
    updated_rev = cursor.fetchone()

    if updated_rev['manager_approved'] and updated_rev['ceo_approved']:
        cursor.execute("SELECT * FROM transactions WHERE txn_id = %s", (updated_rev['txn_id'],))
        txn = cursor.fetchone()

        if txn:
            cursor.execute("UPDATE customers SET balance = balance + %s WHERE customer_id = %s", (txn['amount'], txn['customer_id']))
            if txn['target_account'] and txn['target_bank'] == 'INTERNAL':
                cursor.execute("UPDATE customers SET balance = balance - %s WHERE customer_id = %s", (txn['amount'], txn['target_account']))

            cursor.execute("UPDATE reversals SET status = 'COMPLETED' WHERE reversal_id = %s", (reversal_id,))
            cursor.execute("UPDATE transactions SET status = 'REVERSED' WHERE txn_id = %s", (txn['txn_id'],))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': 'Reversal Approve ta’ee maallaqni maammilaatti deebi’era!'})

    conn.close()
    return jsonify({'success': True, 'message': f'{role} Approval galmeeffameera.'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
