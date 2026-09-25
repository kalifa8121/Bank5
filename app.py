import os
import html
import json
import random
import datetime
import urllib.request
import urllib.error

from flask import request, redirect, session, render_template_string, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

# app.py owns the database and existing staff system. This module only adds customer mobile banking.
from app import app, get_db_connection, get_commission


def init_mobile_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS mobile_pin_hash TEXT")
    cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS mobile_enabled BOOLEAN DEFAULT FALSE")
    cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS mobile_failed_attempts INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS mobile_locked_until TEXT")
    conn.commit()
    conn.close()


def current_customer():
    cid = session.get("mobile_customer_id")
    if not cid or not session.get("mobile_logged_in"):
        return None
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM customers WHERE customer_id = ? AND status = 'ACTIVE'", (cid,))
    c = cur.fetchone()
    conn.close()
    return c


def provider_post(url, api_key, payload):
    if not url:
        return False, "Provider API URL hin qophoofne."
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"raw": raw}
            ok = 200 <= response.status < 300 and body.get("success", True) is not False
            return ok, body
    except urllib.error.HTTPError as e:
        return False, f"Provider HTTP {e.code}"
    except Exception as e:
        return False, f"Provider connection error: {e}"


def create_mobile_txn(cur, txn_type, customer, amount, target="", bank_name="", commission=0.0,
                      status="PENDING_MANAGER", prefix="MB"):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = int(datetime.datetime.now().timestamp() * 1000)
    txn_id = f"MTXN-{stamp}-{random.randint(100,999)}"
    ref = f"{prefix}{datetime.datetime.now().strftime('%y%j%H%M%S')}{random.randint(100,999)}"
    cur.execute(
        """
        INSERT INTO transactions
        (txn_id, txn_type, customer_id, customer_name, target_account, amount, commission,
         bank_name, ft_reference, status, created_by, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (txn_id, txn_type, customer["customer_id"], customer["full_name"], target,
         amount, commission, bank_name, ref, status, f"MOBILE:{customer['customer_id']}", now),
    )
    return txn_id, ref


MOBILE_LOGIN_HTML = """<!doctype html><html lang='om'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Mobile Banking Login</title><style>body{font-family:Arial;background:#f1f5f9;padding:20px}.card{max-width:420px;margin:50px auto;background:white;padding:24px;border-radius:18px;box-shadow:0 4px 20px #0001}input,button{width:100%;padding:14px;margin:8px 0;border-radius:10px;border:1px solid #ddd;box-sizing:border-box}button{background:#065f46;color:white;font-weight:bold}.err{color:#b91c1c;font-size:13px}</style>
<div class='card'><h2>🏦 Mobile Banking</h2><p>Bilbila fi PIN kee galchi.</p><div class='err'>{{ERROR}}</div><form method='post'><input name='phone' placeholder='Lakkoofsa bilbilaa' required><input name='pin' type='password' inputmode='numeric' placeholder='PIN' required><button>Seeni</button></form></div></html>"""

MOBILE_HOME_HTML = """<!doctype html><html lang='om'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Mobile Banking</title><style>body{font-family:Arial;background:#f1f5f9;margin:0;padding:14px}.top{background:#065f46;color:white;padding:22px;border-radius:18px}.bal{font-size:30px;font-weight:bold}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.btn{background:white;padding:18px;border-radius:14px;text-decoration:none;color:#0f172a;box-shadow:0 2px 8px #0001}.rows{background:white;border-radius:14px;padding:8px}.m-row{display:flex;justify-content:space-between;padding:12px;border-bottom:1px solid #eee}</style>
<div class='top'><div>👋 {{NAME}}</div><div>Balance</div><div class='bal'>{{BALANCE}} Birr</div></div><div class='grid'>
<a class='btn' href='/mobile/send'>💸 Ergi</a><a class='btn' href='/mobile/withdraw'>💵 Baafadhu</a><a class='btn' href='/mobile/wallet'>👛 Wallet</a><a class='btn' href='/mobile/bank'>🏦 Baankii Biroo</a><a class='btn' href='/mobile/etopup'>📱 eTopup</a><a class='btn' href='/mobile/statement'>📄 Statement</a></div>
<div class='rows'><b>Transactions</b>{{ROWS}}</div><p><a href='/mobile/logout'>Logout</a></p></html>"""

MOBILE_FORM_HTML = """<!doctype html><html lang='om'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Mobile Banking</title><style>body{font-family:Arial;background:#f1f5f9;padding:14px}.card{max-width:520px;margin:20px auto;background:white;padding:20px;border-radius:18px}input,button{width:100%;padding:14px;margin:8px 0;box-sizing:border-box;border:1px solid #ddd;border-radius:10px}button{background:#065f46;color:white;font-weight:bold}.msg{padding:10px;background:#ecfdf5;border-radius:10px}</style>
<div class='card'><h2>{{TITLE}}</h2><div class='msg'>{{MSG}}</div><form method='post'>{{FIELDS}}<button>Submit</button></form><p><a href='/mobile'>← Dashboard</a></p></div></html>"""

MOBILE_STATEMENT_HTML = """<!doctype html><html><meta name='viewport' content='width=device-width,initial-scale=1'><title>Statement</title>
<style>body{font-family:Arial;background:#f1f5f9;padding:10px}table{width:100%;background:white;border-collapse:collapse;font-size:12px}th,td{padding:8px;border-bottom:1px solid #eee;text-align:left}</style>
<h2>📄 Statement</h2><table><tr><th>Time</th><th>Type</th><th>Amount</th><th>Status</th><th>Ref</th></tr>{{ROWS}}</table><p><a href='/mobile'>← Dashboard</a></p></html>"""


@app.route("/mobile/login", methods=["GET", "POST"])
def mobile_login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        pin = request.form.get("pin", "").strip()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM customers WHERE phone = ? AND status = 'ACTIVE'", (phone,))
        c = cur.fetchone()
        if not c or not c["mobile_enabled"] or not c["mobile_pin_hash"] or not check_password_hash(c["mobile_pin_hash"], pin):
            conn.close()
            return render_template_string(MOBILE_LOGIN_HTML.replace("{{ERROR}}", "Bilbila ykn PIN dogoggoraa ykn mobile banking hin banamne."))
        session.clear()
        session["mobile_logged_in"] = True
        session["mobile_customer_id"] = c["customer_id"]
        conn.close()
        return redirect("/mobile")
    return render_template_string(MOBILE_LOGIN_HTML.replace("{{ERROR}}", ""))


@app.route("/mobile/logout")
def mobile_logout():
    session.clear()
    return redirect("/mobile/login")


@app.route("/mobile")
def mobile_home():
    c = current_customer()
    if not c:
        return redirect("/mobile/login")
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT txn_type, amount, status, timestamp FROM transactions WHERE customer_id = ? OR target_account = ? ORDER BY timestamp DESC LIMIT 10", (c["customer_id"], c["customer_id"]))
    txns = cur.fetchall(); conn.close()
    rows = "".join(f"<div class='m-row'><b>{html.escape(str(t['txn_type']))}</b><span>{float(t['amount'] or 0):,.2f} Birr<br><small>{html.escape(str(t['status']))} · {html.escape(str(t['timestamp']))}</small></span></div>" for t in txns)
    return render_template_string(MOBILE_HOME_HTML.replace("{{NAME}}", html.escape(c["full_name"])).replace("{{BALANCE}}", f"{float(c['balance'] or 0):,.2f}").replace("{{ROWS}}", rows or "<p>Statement hin jiru.</p>"))


@app.route("/mobile/send", methods=["GET", "POST"])
def mobile_send():
    c = current_customer()
    if not c: return redirect("/mobile/login")
    msg = ""
    if request.method == "POST":
        target = request.form.get("target_account", "").strip(); amount = float(request.form.get("amount", "0") or 0); pin = request.form.get("pin", "").strip()
        if not check_password_hash(c["mobile_pin_hash"], pin): msg = "❌ PIN dogoggoraa."
        elif target == c["customer_id"]: msg = "❌ Ofii keetti erguu hin dandeessu."
        elif amount <= 0: msg = "❌ Amount sirrii galchi."
        else:
            conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT * FROM customers WHERE customer_id = ? AND status='ACTIVE'", (target,)); receiver = cur.fetchone()
            if not receiver: msg = "❌ Akkaawuntii fudhataa hin argamne."
            elif c["freeze_status"] == "FROZEN": msg = "🔒 Akkaawuntiin kee frozen dha."
            elif float(c["balance"] or 0) < amount: msg = "❌ Balance gahaa miti."
            else:
                _, ref = create_mobile_txn(cur, "MOBILE_TRANSFER", c, amount, target, "Internal Mobile Banking", 0.0, "PENDING_MANAGER", "MBT")
                conn.commit(); msg = f"✅ Transfer galmaa’e. Ref: {ref}. Manager approval eegaa jira."
            conn.close()
    fields = '<input name="target_account" placeholder="Account ID / Customer ID" required><input name="amount" type="number" step="0.01" placeholder="Amount" required><input name="pin" type="password" inputmode="numeric" placeholder="PIN" required>'
    return render_template_string(MOBILE_FORM_HTML.replace("{{TITLE}}", "💸 Qarshii Ergi").replace("{{ACTION}}", "/mobile/send").replace("{{FIELDS}}", fields).replace("{{MSG}}", msg))


@app.route("/mobile/withdraw", methods=["GET", "POST"])
def mobile_withdraw():
    c = current_customer()
    if not c: return redirect("/mobile/login")
    msg = ""
    if request.method == "POST":
        amount = float(request.form.get("amount", "0") or 0); pin = request.form.get("pin", "").strip()
        if not check_password_hash(c["mobile_pin_hash"], pin): msg = "❌ PIN dogoggoraa."
        elif amount <= 0: msg = "❌ Amount sirrii galchi."
        elif float(c["balance"] or 0) < amount + get_commission(amount): msg = "❌ Balance gahaa miti."
        else:
            conn = get_db_connection(); cur = conn.cursor(); _, ref = create_mobile_txn(cur, "WITHDRAWAL", c, amount, "", "Mobile Cash-out Request", get_commission(amount), "PENDING_MANAGER", "MWD"); conn.commit(); conn.close(); msg = f"✅ Gaaffiin baafannaa galmaa’e. Ref: {ref}. Approval eegaa jira."
    fields = '<input name="amount" type="number" step="0.01" placeholder="Amount" required><input name="pin" type="password" inputmode="numeric" placeholder="PIN" required>'
    return render_template_string(MOBILE_FORM_HTML.replace("{{TITLE}}", "💵 Qarshii Baafadhu").replace("{{FIELDS}}", fields).replace("{{MSG}}", msg))


def external_transfer(kind):
    c = current_customer()
    if not c: return redirect("/mobile/login")
    msg = ""
    if request.method == "POST":
        target = request.form.get("target", "").strip(); amount = float(request.form.get("amount", "0") or 0); pin = request.form.get("pin", "").strip()
        if not check_password_hash(c["mobile_pin_hash"], pin): msg = "❌ PIN dogoggoraa."
        elif amount <= 0 or not target: msg = "❌ Target fi amount sirrii galchi."
        elif float(c["balance"] or 0) < amount: msg = "❌ Balance gahaa miti."
        elif os.environ.get("MOBILE_LIVE_MODE", "false").lower() != "true": msg = "🧪 Test mode: transfer live hin raawwatamu."
        else:
            url = os.environ.get("BANK_TRANSFER_API_URL" if kind == "bank" else "WALLET_API_URL", "")
            key = os.environ.get("BANK_TRANSFER_API_KEY" if kind == "bank" else "WALLET_API_KEY", "")
            ok, result = provider_post(url, key, {"reference": f"MB-{int(datetime.datetime.now().timestamp())}", "source_customer_id": c["customer_id"], "target": target, "amount": amount, "currency": "ETB"})
            if ok:
                conn = get_db_connection(); cur = conn.cursor(); _, ref = create_mobile_txn(cur, "BANK_TRANSFER" if kind == "bank" else "WALLET_TRANSFER", c, amount, target, "External Provider", 0.0, "APPROVED", "EXT"); cur.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amount, c["customer_id"])); conn.commit(); conn.close(); msg = f"✅ Transfer milkaa’e. Ref: {ref}"
            else: msg = f"❌ Provider: {result}"
    title = "🏦 Gara Baankii Birootti Ergi" if kind == "bank" else "👛 Gara Wallet Ergi"
    fields = '<input name="target" placeholder="Account/Wallet Number" required><input name="amount" type="number" step="0.01" placeholder="Amount" required><input name="pin" type="password" inputmode="numeric" placeholder="PIN" required>'
    return render_template_string(MOBILE_FORM_HTML.replace("{{TITLE}}", title).replace("{{FIELDS}}", fields).replace("{{MSG}}", msg))


@app.route("/mobile/bank", methods=["GET", "POST"])
def mobile_bank(): return external_transfer("bank")

@app.route("/mobile/wallet", methods=["GET", "POST"])
def mobile_wallet(): return external_transfer("wallet")


@app.route("/mobile/etopup", methods=["GET", "POST"])
def mobile_etopup():
    c = current_customer()
    if not c: return redirect("/mobile/login")
    msg = ""
    if request.method == "POST":
        phone = request.form.get("phone", "").strip(); amount = float(request.form.get("amount", "0") or 0); pin = request.form.get("pin", "").strip()
        if not check_password_hash(c["mobile_pin_hash"], pin): msg = "❌ PIN dogoggoraa."
        elif amount <= 0 or not phone: msg = "❌ Phone fi amount sirrii galchi."
        elif float(c["balance"] or 0) < amount: msg = "❌ Balance gahaa miti."
        elif os.environ.get("MOBILE_LIVE_MODE", "false").lower() != "true": msg = "🧪 Test mode: eTopup live hin raawwatamu."
        else:
            ok, result = provider_post(os.environ.get("ETOPUP_API_URL", ""), os.environ.get("ETOPUP_API_KEY", ""), {"reference": f"ETP-{int(datetime.datetime.now().timestamp())}", "customer_id": c["customer_id"], "phone": phone, "amount": amount, "currency": "ETB"})
            if ok:
                conn = get_db_connection(); cur = conn.cursor(); _, ref = create_mobile_txn(cur, "ETOPUP", c, amount, phone, "eTopup Provider", 0.0, "APPROVED", "ETP"); cur.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amount, c["customer_id"])); conn.commit(); conn.close(); msg = f"✅ eTopup milkaa’e. Ref: {ref}"
            else: msg = f"❌ eTopup provider: {result}"
    fields = '<input name="phone" placeholder="Phone Number" required><input name="amount" type="number" step="0.01" placeholder="Amount" required><input name="pin" type="password" inputmode="numeric" placeholder="PIN" required>'
    return render_template_string(MOBILE_FORM_HTML.replace("{{TITLE}}", "📱 eTopup Guuti").replace("{{FIELDS}}", fields).replace("{{MSG}}", msg))


@app.route("/mobile/statement")
def mobile_statement():
    c = current_customer()
    if not c: return redirect("/mobile/login")
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT txn_id, txn_type, amount, commission, ft_reference, status, timestamp, target_account FROM transactions WHERE customer_id=? OR target_account=? ORDER BY timestamp DESC LIMIT 200", (c["customer_id"], c["customer_id"])); txns = cur.fetchall(); conn.close()
    rows = "".join(f"<tr><td>{html.escape(str(t['timestamp']))}</td><td>{html.escape(str(t['txn_type']))}</td><td>{float(t['amount'] or 0):,.2f}</td><td>{html.escape(str(t['status']))}</td><td>{html.escape(str(t['ft_reference']))}</td></tr>" for t in txns)
    return render_template_string(MOBILE_STATEMENT_HTML.replace("{{ROWS}}", rows or "<tr><td colspan='5'>No transactions</td></tr>"))


@app.route("/set_mobile_pin/<cust_id>", methods=["GET", "POST"])
def set_mobile_pin(cust_id):
    if session.get("role") not in ["MANAGER", "CEO"]:
        return "🚫 Manager ykn CEO qofa.", 403
    msg = ""
    if request.method == "POST":
        pin = request.form.get("pin", "").strip(); confirm = request.form.get("confirm", "").strip()
        if len(pin) < 4 or len(pin) > 6 or not pin.isdigit(): msg = "❌ PIN 4-6 digit ta’uu qaba."
        elif pin != confirm: msg = "❌ PIN lama wal hin simne."
        else:
            conn = get_db_connection(); cur = conn.cursor(); cur.execute("UPDATE customers SET mobile_pin_hash=?, mobile_enabled=TRUE, mobile_failed_attempts=0, mobile_locked_until=NULL WHERE customer_id=?", (generate_password_hash(pin), cust_id)); conn.commit(); conn.close(); msg = "✅ Mobile Banking PIN qophaa’eera."
    fields = '<input name="pin" type="password" inputmode="numeric" maxlength="6" placeholder="New PIN" required><input name="confirm" type="password" inputmode="numeric" maxlength="6" placeholder="Confirm PIN" required>'
    return render_template_string(MOBILE_FORM_HTML.replace("{{TITLE}}", "🔐 Customer Mobile PIN").replace("{{FIELDS}}", fields).replace("{{MSG}}", msg))


init_mobile_db()
