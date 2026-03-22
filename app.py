import os
from flask import Flask, render_template, request, redirect, url_for, session
from functools import wraps
import requests
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
import sqlite3


# -------------------- LOGIN REQUIRED DECORATOR --------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


# -------------------- ENVIRONMENT SETUP --------------------
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")


# -------------------- ADMIN CREDENTIALS --------------------
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")


# -------------------- PAYSTACK CONFIG --------------------
PAYSTACK_SECRET_KEY = os.getenv(
    "PAYSTACK_SECRET_KEY",
    "sk_test_b3fa11dd625cdce9bbebe18d817c80b36bf78827"
)

PAYSTACK_PUBLIC_KEY = os.getenv(
    "PAYSTACK_PUBLIC_KEY",
    "pk_test_0ee7abce66cdf09d45269e1070881148c90063d7"
)

PAYSTACK_INIT_URL = "https://api.paystack.co/transaction/initialize"
PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify/{}"

print("Paystack keys loaded successfully")


# -------------------- DATABASE SETUP --------------------
DB_PATH = Path(__file__).resolve().parent / "donations.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_name TEXT NOT NULL,
            amount REAL NOT NULL,
            datetime TEXT NOT NULL,
            reference TEXT UNIQUE NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()


# -------------------- ROUTES --------------------

@app.route("/", methods=["GET"])
def donate_form():
    return render_template("donate.html", public_key=PAYSTACK_PUBLIC_KEY, datetime=datetime)


@app.route("/pay", methods=["POST"])
def pay():
    name = request.form.get("name", "").strip()
    amount = request.form.get("amount", "").strip()

    if not name or not amount:
        return "Please provide both name and amount.", 400

    try:
        amount_float = float(amount)
        if amount_float <= 0:
            return "Amount must be greater than zero.", 400
    except ValueError:
        return "Invalid amount.", 400

    amount_kobo = int(round(amount_float * 100))

    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    data = {
        "email": f"{name.replace(' ', '').lower()}@echohope.org",
        "amount": amount_kobo,
        "metadata": {"donor_name": name},
        "currency": "GHS",
        "callback_url": request.url_root.rstrip("/") + url_for("callback")
    }

    response = requests.post(PAYSTACK_INIT_URL, headers=headers, json=data)
    res = response.json()

    if not res.get("status"):
        return f"Error initializing payment: {res.get('message')}", 500

    return redirect(res["data"]["authorization_url"])


@app.route("/api/public-donations")
def public_donations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT donor_name, amount, datetime
        FROM donations
        ORDER BY id DESC
        LIMIT 10
    """)

    rows = cursor.fetchall()
    conn.close()

    donations = []

    for row in rows:
        donations.append({
            "name": row[0],
            "amount": row[1],
            "datetime": row[2]
        })

    return {"donations": donations}


@app.route("/callback")
def callback():
    reference = request.args.get("reference")

    if not reference:
        return "Missing transaction reference.", 400

    verify_url = PAYSTACK_VERIFY_URL.format(reference)
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    response = requests.get(verify_url, headers=headers)

    if response.status_code != 200:
        return "Verification request failed.", 500

    res = response.json()

    if not res.get("status"):
        return "Could not verify payment.", 500

    data = res.get("data")

    # --- SECURITY CHECKS ---
    if data.get("status") != "success":
        return "Payment not successful.", 400

    if data.get("currency") != "GHS":
        return "Invalid currency detected.", 400

    reference = data.get("reference")
    donor_name = data.get("metadata", {}).get("donor_name", "Anonymous")
    amount = data.get("amount", 0) / 100.0

    # --- SAFE DATABASE INSERT ---
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO donations (donor_name, amount, datetime, reference)
            VALUES (?, ?, ?, ?)
        """, (donor_name, amount, now, reference))

        conn.commit()
        conn.close()

        print(f"✅ Secure donation logged to DB: {donor_name} — GHS {amount:.2f}")

    except sqlite3.IntegrityError:
        print("⚠️ Duplicate transaction ignored.")

    return render_template(
        "thankyou.html",
        name=donor_name,
        amount=f"{amount:.2f}",
        datetime=datetime
    )

@app.route("/api/donations")
@login_required
def get_donations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT donor_name, amount, datetime, reference
        FROM donations
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    donations = []
    total_amount = 0.0

    for row in rows:
        donations.append({
            "name": row[0],
            "amount": row[1],
            "datetime": row[2],
            "reference": row[3]
        })
        total_amount += row[1]

    return {
        "donations": donations,
        "total_amount": round(total_amount, 2),
        "count": len(donations)
    }


# -------------------- ADMIN LOGIN --------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))

        return render_template("admin_login.html", error="Invalid credentials")

    return render_template("admin_login.html")


@app.route("/admin")
@login_required
def admin_dashboard():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT donor_name, amount, datetime, reference
        FROM donations
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    donations = []
    total_amount = 0.0

    for row in rows:
        donations.append({
            "Donor Name": row[0],
            "Amount (GHS)": f"{row[1]:.2f}",
            "Date & Time": row[2],
            "Transaction Ref": row[3]
        })
        total_amount += row[1]

    return render_template(
        "admin_dashboard.html",
        donations=donations,
        total_amount=f"{total_amount:.2f}"
    )


@app.route("/admin/logout")
@login_required
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/api/donations")
@login_required
def get_donations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT donor_name, amount, datetime, reference
        FROM donations
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cursor.fetchall()
    conn.close()

    donations = []
    total_amount = 0.0

    for row in rows:
        donations.append({
            "name": row[0],
            "amount": row[1],
            "datetime": row[2],
            "reference": row[3]
        })
        total_amount += row[1]

    return {
        "donations": donations,
        "total_amount": f"{total_amount:.2f}",
        "count": len(donations)
    }


# -------------------- MAIN --------------------
if __name__ == "__main__":
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print(f"\n🚀 Server running!")
    print(f"👉 Laptop: http://127.0.0.1:5000")
    print(f"👉 Phone (same Wi-Fi): http://{local_ip}:5000\n")

    app.run()