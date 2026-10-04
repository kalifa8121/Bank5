import os
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from io import BytesIO

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key")
database_url = os.environ.get("DATABASE_URL", "").strip()

if not database_url:
    raise RuntimeError("DATABASE_URL is missing. Add your Neon PostgreSQL connection string in Render Environment Variables.")

# Some providers give postgres://; SQLAlchemy expects postgresql://.
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB per uploaded media item

db = SQLAlchemy(app)

ALLOWED_MEDIA = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "audio/webm", "audio/ogg", "audio/mpeg", "audio/wav",
    "video/webm", "video/mp4", "video/ogg",
    "application/pdf"
}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="employee")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    room = db.Column(db.String(120), nullable=False, default="general", index=True)
    kind = db.Column(db.String(20), nullable=False, default="text")
    text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    sender = db.relationship("User", foreign_keys=[sender_id])

class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(100), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Signal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(120), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, nullable=True, index=True)
    kind = db.Column(db.String(30), nullable=False)  # offer, answer, candidate, leave
    payload = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

@app.get("/")
def index():
    if not current_user():
        return redirect(url_for("login"))
    return redirect(url_for("chat"))

@app.route("/register", methods=["GET", "POST"])
def register():
    # Registration is intentionally open for a fresh internal test system.
    # For production, close this route and create users through an admin panel.
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")

        if not username or not display_name or len(password) < 6:
            flash("Username, maqaa mul'ataa fi password (min 6) guuti.", "error")
            return redirect(url_for("register"))

        if db.session.scalar(db.select(User).where(User.username == username)):
            flash("Username kun duraan jira.", "error")
            return redirect(url_for("register"))

        user_count = db.session.scalar(db.select(db.func.count(User.id))) or 0
        role = "manager" if user_count == 0 else "employee"

        user = User(
            username=username,
            display_name=display_name,
            role=role,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.commit()
        flash("Account uumame. Amma seeni.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).where(User.username == username))

        if not user or not check_password_hash(user.password_hash, password):
            flash("Username ykn password sirrii miti.", "error")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        return redirect(url_for("chat"))

    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/chat")
@login_required
def chat():
    users = db.session.scalars(db.select(User).order_by(User.display_name)).all()
    return render_template("chat.html", user=current_user(), users=users)

@app.get("/api/messages")
@login_required
def api_messages():
    room = request.args.get("room", "general")[:120]
    after = request.args.get("after", "0")
    try:
        after_id = int(after)
    except ValueError:
        after_id = 0

    rows = db.session.scalars(
        db.select(Message)
        .where(Message.room == room, Message.id > after_id)
        .order_by(Message.id.asc())
        .limit(100)
    ).all()

    out = []
    for m in rows:
        media = db.session.scalar(db.select(Media).where(Media.message_id == m.id))
        out.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "sender": m.sender.display_name if m.sender else "Unknown",
            "kind": m.kind,
            "text": m.text or "",
            "created_at": m.created_at.isoformat(),
            "media_id": media.id if media else None,
            "media_url": url_for("media", media_id=media.id) if media else None,
            "mimetype": media.mimetype if media else None,
        })
    return jsonify({"messages": out, "current_user_id": current_user().id})

@app.post("/api/messages")
@login_required
def api_send_message():
    user = current_user()
    room = request.form.get("room", "general")[:120]
    text = request.form.get("text", "").strip()
    kind = request.form.get("kind", "text").strip().lower()

    upload = request.files.get("file")
    if not text and not upload:
        return jsonify({"error": "Message ykn media tokko kenni."}), 400

    if kind not in {"text", "photo", "audio", "video", "file"}:
        kind = "text"

    msg = Message(
        sender_id=user.id,
        room=room,
        kind=kind,
        text=text[:5000] if text else None
    )
    db.session.add(msg)
    db.session.flush()

    if upload and upload.filename:
        mimetype = (upload.mimetype or "").lower()
        if mimetype not in ALLOWED_MEDIA:
            db.session.rollback()
            return jsonify({"error": f"File type hin hayyamamne: {mimetype}"}), 400

        data = upload.read()
        if not data:
            db.session.rollback()
            return jsonify({"error": "File duwwaa dha."}), 400

        media = Media(
            message_id=msg.id,
            filename=secure_filename(upload.filename) or f"media-{uuid.uuid4().hex}",
            mimetype=mimetype,
            data=data,
            size=len(data),
        )
        db.session.add(media)

    db.session.commit()
    return jsonify({"ok": True, "message_id": msg.id})

@app.get("/media/<int:media_id>")
@login_required
def media(media_id):
    item = db.session.get(Media, media_id)
    if not item:
        return "Media not found", 404
    return send_file(
        BytesIO(item.data),
        mimetype=item.mimetype,
        download_name=item.filename,
        max_age=3600
    )

@app.get("/api/users")
@login_required
def api_users():
    users = db.session.scalars(db.select(User).order_by(User.display_name)).all()
    return jsonify([
        {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role}
        for u in users
    ])

@app.get("/call")
@login_required
def call():
    room = request.args.get("room", "general")[:120]
    return render_template("call.html", user=current_user(), room=room)

@app.get("/api/signals")
@login_required
def get_signals():
    room = request.args.get("room", "general")[:120]
    after = request.args.get("after", "0")

    try:
        after_id = int(after)
    except ValueError:
        after_id = 0

    current_id = current_user().id

    rows = db.session.scalars(
        db.select(Signal)
        .where(
            Signal.room == room,
            Signal.id > after_id,
            Signal.sender_id != current_id,
            db.or_(
                Signal.receiver_id == current_id,
                Signal.receiver_id.is_(None)
            )
        )
        .order_by(Signal.id.asc())
        .limit(100)
    ).all()

    return jsonify([
        {
            "id": s.id,
            "kind": s.kind,
            "payload": s.payload,
            "sender_id": s.sender_id,
            "receiver_id": s.receiver_id
        }
        for s in rows
    ])
@app.post("/api/signals")
@login_required
def post_signal():
    data = request.get_json(silent=True) or {}

    room = str(data.get("room", "general"))[:120]
    kind = str(data.get("kind", ""))[:30]
    payload = data.get("payload", "")

    if kind not in {"offer", "answer", "candidate", "leave"}:
        return jsonify({"error": "Signal type hin sirre."}), 400

    receiver_id = data.get("receiver_id")

    if receiver_id in (None, "", "null"):
        receiver_id = None
    else:
        try:
            receiver_id = int(receiver_id)
        except (TypeError, ValueError):
            return jsonify({"error": "Receiver ID hin sirre."}), 400

        if receiver_id == current_user().id:
            return jsonify({"error": "Ofii keetiif call erguu hin dandeessu."}), 400

        receiver = db.session.get(User, receiver_id)

        if not receiver:
            return jsonify({"error": "Worker kun hin jiru."}), 404

    signal = Signal(
        room=room,
        sender_id=current_user().id,
        receiver_id=receiver_id,
        kind=kind,
        payload=json_string(payload),
    )

    db.session.add(signal)
    db.session.commit()

    return jsonify({
        "ok": True,
        "id": signal.id
    })
@app.post("/api/signals/cleanup")
@login_required
def cleanup_signals():
    room = request.get_json(silent=True).get("room", "general")
    cutoff = datetime.now(timezone.utc)
    # Keep cleanup conservative: remove only signals older than 1 hour.
    from datetime import timedelta
    old = cutoff - timedelta(hours=1)
    db.session.execute(
        db.delete(Signal).where(Signal.room == room, Signal.created_at < old)
    )
    db.session.commit()
    return jsonify({"ok": True})

@app.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok", "database": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "database": str(e)}), 500

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
