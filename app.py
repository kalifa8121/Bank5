import os
import random
import datetime
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, request, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "imana_free_interest_microfinance_secret_key")

def get_db_connection():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Customer Accounts
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

    # Transactions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
            txn_type TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            customer_name TEXT,
            target_account TEXT,
            amount REAL NOT NULL,
            commission REAL DEFAULT 0.0,
            ft_reference TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'APPROVED',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Reversals Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reversals (
            reversal_id TEXT PRIMARY KEY,
            txn_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            manager_approved INTEGER DEFAULT 0,
            ceo_approved INTEGER DEFAULT 0,
            status TEXT DEFAULT 'PENDING_APPROVAL',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

init_db()

# --- API ENDPOINTS MOBILE APP-F ---

# 1. Login Maammilaa
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


# 2. Qarshii Walitti Erguu (Transfer - Immediate / Pending Manager Malee)
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
        return jsonify({'success': False, 'message': 'Maammilli sender ykn receiver hin argamne!'}), 404

    if sender['freeze_status'] == 'FROZEN':
        conn.close()
        return jsonify({'success': False, 'message': 'Akkaawuntiin keessan uggurameera!'}), 400

    if sender['balance'] < amount:
        conn.close()
        return jsonify({'success': False, 'message': 'Balansii gahaa hin qabdan!'}), 400

    # Execute Immediate Transfer
    cursor.execute("UPDATE customers SET balance = balance - %s WHERE customer_id = %s", (amount, sender_id))
    cursor.execute("UPDATE customers SET balance = balance + %s WHERE customer_id = %s", (amount, receiver_acc))

    ft_ref = f"FTM{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
    txn_id = f"TXN-MOB-{int(datetime.datetime.now().timestamp())}"

    cursor.execute("""
        INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, amount, ft_reference, status)
        VALUES (%s, 'T24_TRANSFER', %s, %s, %s, %s, %s, 'APPROVED')
    """, (txn_id, sender_id, sender['full_name'], receiver_acc, amount, ft_ref))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Qarshiin milkaa\'inaan ergameera!', 'ft_reference': ft_ref})


# 3. Qarshii Baafachuu (Withdrawal - Immediate)
@app.route('/api/mobile/withdraw', methods=['POST'])
def mobile_withdraw():
    data = request.json or {}
    cust_id = data.get('customer_id')
    amount = float(data.get('amount', 0))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, balance, freeze_status FROM customers WHERE customer_id = %s", (cust_id,))
    cust = cursor.fetchone()

    if not cust or cust['balance'] < amount:
        conn.close()
        return jsonify({'success': False, 'message': 'Balansii gahaa hin qabdan ykn maammilli hin argamne!'}), 400

    cursor.execute("UPDATE customers SET balance = balance - %s WHERE customer_id = %s", (amount, cust_id))
    ft_ref = f"WTHM{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
    txn_id = f"TXN-WTH-{int(datetime.datetime.now().timestamp())}"

    cursor.execute("""
        INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, amount, ft_reference, status)
        VALUES (%s, 'WITHDRAWAL', %s, %s, %s, %s, 'APPROVED')
    """, (txn_id, cust_id, cust['full_name'], amount, ft_ref))

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Qarshii baafachuun milkaa\'eera!', 'ft_reference': ft_ref})


# 4. Top-Up (Airtime Guuttachuu)
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
    return jsonify({'success': True, 'message': f'Airtime {amount} Birr bilbila {phone}-f guutameera!', 'ft_reference': ft_ref})


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
        SELECT txn_id, txn_type, amount, ft_reference, timestamp, target_account 
        FROM transactions 
        WHERE customer_id = %s OR target_account = %s 
        ORDER BY timestamp DESC LIMIT 20
    """, (cust_id, cust_id))
    txns = cursor.fetchall()
    conn.close()

    history = []
    for t in txns:
        history.append({
            'txn_id': t['txn_id'],
            'type': t['txn_type'],
            'amount': t['amount'],
            'ft_reference': t['ft_reference'],
            'timestamp': str(t['timestamp'])
        })

    return jsonify({
        'success': True,
        'customer_id': cust_id,
        'full_name': cust['full_name'],
        'balance': cust['balance'],
        'history': history
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
