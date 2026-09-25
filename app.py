import os
import psycopg2
from psycopg2.extras import DictCursor
import datetime
import random
from flask import Flask, request, redirect, session, render_template_string, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "mobile_banking_secret_key_2026")

def get_db_connection():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL variable-ni Neon PostgreSQL saaqamee hin jiru!")
    conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users (Staff & Admin)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    # Mobile Banking Customers
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mobile_customers (
            phone TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            pin TEXT NOT NULL,
            wallet_balance REAL DEFAULT 0.0,
            bank_balance REAL DEFAULT 1000.0,
            status TEXT DEFAULT 'ACTIVE'
        )
    """)

    # Transactions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            txn_type TEXT NOT NULL,
            target_account TEXT,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'COMPLETED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Reversals (Auditor Gaafatu, Manager & CEO Approve godhan)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reversals (
            reversal_id TEXT PRIMARY KEY,
            txn_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            manager_approved BOOLEAN DEFAULT FALSE,
            ceo_approved BOOLEAN DEFAULT FALSE,
            status TEXT DEFAULT 'PENDING'
        )
    """)

    # User-oota default
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users VALUES ('auditor1', 'audit123', 'AUDITOR')")
        cursor.execute("INSERT INTO users VALUES ('manager1', 'man123', 'MANAGER')")
        cursor.execute("INSERT INTO users VALUES ('ceo1', 'ceo123', 'CEO')")

    # Maammila fakkeenyaa (Demo Mobile Customer)
    cursor.execute("SELECT COUNT(*) FROM mobile_customers")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO mobile_customers VALUES ('0911223344', 'Chala Abebe', '1234', 5000.0, 25000.0, 'ACTIVE')")

    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"Database init error: {e}")

# HTML Template Mobile Banking Interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mobile Banking API & Portal</title>
    <style>
        body { font-family: sans-serif; background: #f0f2f5; padding: 15px; margin: 0; }
        .card { background: white; padding: 15px; border-radius: 10px; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        h2, h3 { color: #065f46; margin-top: 0; }
        .btn { background: #047857; color: white; border: none; padding: 10px; border-radius: 5px; width: 100%; cursor: pointer; font-weight: bold; }
        input, select { width: 100%; padding: 8px; margin: 5px 0 10px 0; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #ddd; padding: 8px; font-size: 12px; text-align: left; }
        th { background: #047857; color: white; }
    </style>
</head>
<body>
    <div class="card">
        <h2>📱 Mobile Banking Service Engine</h2>
        <p>System-ni kun backend mobile app (APK) fi portal Reversal Audit/CEO utubuu dha.</p>
    </div>
    {% block content %}{% endblock %}
</body>
</html>
"""

# ==========================================
# 📱 API MOBILE BANKING APPLICATION (FOR APK)
# ==========================================

# 1, 2, 3, 4, 5: Transfer, Withdraw, Wallet/Bank, E-topup, Balance & Statement API
@app.route('/api/mobile/transaction', methods=['POST'])
def api_mobile_transaction():
    data = request.json or {}
    phone = data.get('phone')
    pin = data.get('pin')
    txn_type = data.get('txn_type') # SEND_MONEY, WITHDRAW, TRANSFER_WALLET_BANK, ETOPUP
    target = data.get('target', '')
    amount = float(data.get('amount', 0))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM mobile_customers WHERE phone = %s AND pin = %s", (phone, pin))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({'status': 'ERROR', 'message': 'Lakk Bilbilaa ykn PIN dogoggoraa!'}), 401

    if user['status'] != 'ACTIVE':
        conn.close()
        return jsonify({'status': 'ERROR', 'message': 'Akkaawuntiin keessan uggurameera!'}), 403

    if amount <= 0:
        conn.close()
        return jsonify({'status': 'ERROR', 'message': 'Hamma maallaqaa sirrii galchaa!'}), 400

    txn_id = f"TXN{random.randint(100000, 999999)}"

    # 1. Qarshii walitti erguu (P2P Transfer)
    if txn_type == 'SEND_MONEY':
        if user['wallet_balance'] < amount:
            conn.close()
            return jsonify({'status': 'ERROR', 'message': 'Hafteen Wallet gahaa miti!'}), 400
        
        cursor.execute("UPDATE mobile_customers SET wallet_balance = wallet_balance - %s WHERE phone = %s", (amount, phone))
        cursor.execute("UPDATE mobile_customers SET wallet_balance = wallet_balance + %s WHERE phone = %s", (amount, target))

    # 2. Qarshii Baafachuu (Withdrawal)
    elif txn_type == 'WITHDRAW':
        if user['wallet_balance'] < amount:
            conn.close()
            return jsonify({'status': 'ERROR', 'message': 'Hafteen Wallet gahaa miti!'}), 400
        
        cursor.execute("UPDATE mobile_customers SET wallet_balance = wallet_balance - %s WHERE phone = %s", (amount, phone))

    # 3. Wallet fi Bankii birootti erguu / Jijjiirrachuu
    elif txn_type == 'TRANSFER_WALLET_TO_BANK':
        if user['wallet_balance'] < amount:
            conn.close()
            return jsonify({'status': 'ERROR', 'message': 'Hafteen Wallet gahaa miti!'}), 400
        
        cursor.execute("UPDATE mobile_customers SET wallet_balance = wallet_balance - %s, bank_balance = bank_balance + %s WHERE phone = %s", (amount, amount, phone))

    # 4. E-topup (Airtime Guuttachuu)
    elif txn_type == 'ETOPUP':
        if user['wallet_balance'] < amount:
            conn.close()
            return jsonify({'status': 'ERROR', 'message': 'Hafteen Wallet gahaa miti!'}), 400
        
        cursor.execute("UPDATE mobile_customers SET wallet_balance = wallet_balance - %s WHERE phone = %s", (amount, phone))

    else:
        conn.close()
        return jsonify({'status': 'ERROR', 'message': 'Gosti transaction hin beakamu!'}), 400

    # Record Transaction (Pending Manager Hin Gaafatu - Directly Approved/Completed)
    cursor.execute("""
        INSERT INTO transactions (txn_id, phone, txn_type, target_account, amount, status)
        VALUES (%s, %s, %s, %s, %s, 'COMPLETED')
    """, (txn_id, phone, txn_type, target, amount))

    conn.commit()
    conn.close()
    return jsonify({'status': 'SUCCESS', 'message': 'Transaction milkaa'eera!', 'txn_id': txn_id})

# 5. Haftee (Balance) fi Statement ilaallachuu API
@app.route('/api/mobile/statement', methods=['POST'])
def api_mobile_statement():
    data = request.json or {}
    phone = data.get('phone')
    pin = data.get('pin')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT wallet_balance, bank_balance FROM mobile_customers WHERE phone = %s AND pin = %s", (phone, pin))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({'status': 'ERROR', 'message': 'PIN dogoggoraa!'}), 401

    cursor.execute("SELECT txn_id, txn_type, target_account, amount, status, created_at FROM transactions WHERE phone = %s ORDER BY created_at DESC LIMIT 10", (phone,))
    txns = cursor.fetchall()
    conn.close()

    history = []
    for t in txns:
        history.append({
            'txn_id': t['txn_id'],
            'txn_type': t['txn_type'],
            'target': t['target_account'],
            'amount': t['amount'],
            'status': t['status'],
            'date': str(t['created_at'])
        })

    return jsonify({
        'status': 'SUCCESS',
        'wallet_balance': user['wallet_balance'],
        'bank_balance': user['bank_balance'],
        'statement': history
    })

# ==========================================
# 7. AUDITOR REVERSAL REQUEST & CEO APPROVAL
# ==========================================

@app.route('/')
def home():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions ORDER BY created_at DESC LIMIT 15")
    txns = cursor.fetchall()

    cursor.execute("SELECT * FROM reversals ORDER BY status DESC")
    reversals = cursor.fetchall()
    conn.close()

    content = """
    <div class="card">
        <h3>📊 Transaakshinoota Raawwataman</h3>
        <table>
            <tr><th>Txn ID</th><th>Phone</th><th>Type</th><th>Amount</th><th>Date</th></tr>
            {% for t in txns %}
            <tr><td>{{t['txn_id']}}</td><td>{{t['phone']}}</td><td>{{t['txn_type']}}</td><td>{{t['amount']}}</td><td>{{t['created_at']}}</td></tr>
            {% endfor %}
        </table>
    </div>

    <div class="card">
        <h3>⚠️ Auditor: Reversal Request Uumi</h3>
        <form action="/auditor/request_reversal" method="POST">
            <input type="text" name="txn_id" placeholder="Txn ID (Fkn: TXN123456)" required>
            <input type="text" name="reason" placeholder="Sababa Reversal..." required>
            <button class="btn" type="submit">Gaaffii Reversal Ergi</button>
        </form>
    </div>

    <div class="card">
        <h3>🔄 Tarree Reversals (Manager & CEO Approval)</h3>
        <table>
            <tr><th>Rev ID</th><th>Txn ID</th><th>Reason</th><th>Status</th><th>Action</th></tr>
            {% for r in reversals %}
            <tr>
                <td>{{r['reversal_id']}}</td>
                <td>{{r['txn_id']}}</td>
                <td>{{r['reason']}}</td>
                <td><b>{{r['status']}}</b></td>
                <td>
                    {% if not r['manager_approved'] %}
                        <a href="/approve/manager/{{r['reversal_id']}}">✅ Manager Approve</a>
                    {% elif not r['ceo_approved'] %}
                        <a href="/approve/ceo/{{r['reversal_id']}}">👑 CEO Final Approve</a>
                    {% else %}
                        Reversed ✅
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    """
    return render_template_string(HTML_TEMPLATE.replace("{% block content %}{% endblock %}", content), txns=txns, reversals=reversals)

@app.route('/auditor/request_reversal', methods=['POST'])
def auditor_request_reversal():
    txn_id = request.form.get('txn_id')
    reason = request.form.get('reason')
    rev_id = f"REV{random.randint(1000, 9999)}"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reversals (reversal_id, txn_id, reason, requested_by) VALUES (%s, %s, %s, 'AUDITOR')", (rev_id, txn_id, reason))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/approve/<role>/<rev_id>')
def approve_reversal_step(role, rev_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    if role == 'manager':
        cursor.execute("UPDATE reversals SET manager_approved = TRUE, status = 'PENDING_CEO' WHERE reversal_id = %s", (rev_id,))
    elif role == 'ceo':
        cursor.execute("SELECT txn_id FROM reversals WHERE reversal_id = %s", (rev_id,))
        rev = cursor.fetchone()
        if rev:
            cursor.execute("SELECT * FROM transactions WHERE txn_id = %s", (rev['txn_id'],))
            txn = cursor.fetchone()
            if txn:
                # Refund Money back to Customer Wallet
                cursor.execute("UPDATE mobile_customers SET wallet_balance = wallet_balance + %s WHERE phone = %s", (txn['amount'], txn['phone']))
                cursor.execute("UPDATE transactions SET status = 'REVERSED' WHERE txn_id = %s", (txn['txn_id'],))
                cursor.execute("UPDATE reversals SET ceo_approved = TRUE, status = 'APPROVED' WHERE reversal_id = %s", (rev_id,))

    conn.commit()
    conn.close()
    return redirect('/')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
