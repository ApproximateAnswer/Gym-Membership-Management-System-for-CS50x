import os

from flask import Flask, flash, redirect, render_template, request, session, url_for
from cs50 import SQL
from datetime import datetime, date, timedelta  
from flask_session import Session
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import apology, login_required, usd

app = Flask(__name__)

app.jinja_env.filters["usd"] = usd

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

db = SQL("sqlite:///gym.db")

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/register", methods=["GET","POST"])
def register():
    #staff
    if request.method=="POST":
        username=request.form.get("username")
        password=request.form.get("password")
        confirmation=request.form.get("confirmation")

        if not username or not password or not confirmation:
            flash("All fields are required, please try again.","danger")
            return render_template("register.html")
        if confirmation != password:
            flash("Passwords do not match!", "danger")
            return render_template("register.html")

        # Check if username exists
        existing_user = db.execute("SELECT * FROM users WHERE username = ?", username)
        if existing_user:
            flash("Username already taken.", "danger")
            return render_template("register.html")

        # Hash and save
        hashed_password = generate_password_hash(password)
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, hashed_password)

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            flash("Must provide username and password", "danger")
            return render_template("login.html")

        rows = db.execute("SELECT * FROM users WHERE username = ?", username)

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
            flash("Invalid username and/or password", "danger")
            return render_template("login.html")

        session["user_id"] = rows[0]["id"]
        return redirect(url_for("index"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    """Log staff out"""
    session.clear()
    return redirect(url_for("login"))



@app.route("/")
@login_required
def index():
    """Dashboard displaying high-level metrics"""
    # Fixed: Adjusted today's date calculation by subtracting 1 hour
    today_str = (datetime.now() - timedelta(hours=1)).date().isoformat()

    # Calculate active members (end_date >= today)
    active_members = db.execute(
        "SELECT COUNT(DISTINCT member_id) AS count FROM subscriptions WHERE end_date >= ?",
        today_str
       )[0]["count"]

    # Calculate total revenue collected
    revenue_data = db.execute("SELECT SUM(price) AS total FROM subscriptions")[0]["total"]
    total_revenue = revenue_data if revenue_data else 0.0

    # Calculate today's total attendance count
    today_attendance = db.execute(
        "SELECT COUNT(*) AS count FROM attendance WHERE DATE(check_in_time) = ?",
        today_str
    )[0]["count"]

    return render_template(
        "index.html",
        active_members=active_members,
        total_revenue=total_revenue,
        today_attendance=today_attendance
    )

@app.route("/members", methods=["GET", "POST"])
@login_required
def members():

    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email")
        phone = request.form.get("phone")

        if not first_name or not last_name or not email or not phone:
            flash("All member fields are required.", "danger")
            return redirect(url_for("members"))

        try:
            db.execute(
                "INSERT INTO members (first_name, last_name, email, phone) VALUES (?, ?, ?, ?)",
                first_name, last_name, email, phone
            )
            flash("Member registered successfully!", "success")
        except:
            flash("Error: Email already exists in system.", "danger")

        return redirect(url_for("members"))

    # GET request: fetch members alongside their latest subscription status
    members_list = db.execute("""
        SELECT m.*, s.plan_name, s.end_date,
        CASE WHEN s.end_date >= DATE('now', 'localtime') THEN 'Active' ELSE 'Expired' END as status
        FROM members m
        LEFT JOIN subscriptions s ON m.id = s.member_id
        GROUP BY m.id HAVING s.id = MAX(s.id) OR s.id IS NULL
    """)
    return render_template("members.html", members=members_list)

@app.route("/subscribe", methods=["POST"])
@login_required
def subscribe():
    """Assign or renew a subscription package"""
    member_id = request.form.get("member_id")
    plan_name = request.form.get("plan_name")
    start_date_str = request.form.get("start_date")
    end_date_str = request.form.get("end_date")

    # Simple explicit pricing based on plan selection
    price = 50.0 if plan_name == "Monthly" else 500.0

    if not member_id or not plan_name or not start_date_str or not end_date_str:
        flash("Missing data for renewal.", "danger")
        return redirect(url_for("members"))

    db.execute(
        "INSERT INTO subscriptions (member_id, plan_name, price, start_date, end_date) VALUES (?, ?, ?, ?, ?)",
        member_id, plan_name, price, start_date_str, end_date_str
    )
    flash("Subscription updated successfully!", "success")
    return redirect(url_for("members"))

@app.route("/checkin", methods=["GET", "POST"])
@login_required
def checkin():
    """Search member and evaluate expiration logic before logging access"""
    search_results = []
    query = request.args.get("q")

    if query:
        search_results = db.execute(
            "SELECT * FROM members WHERE first_name LIKE ? OR last_name LIKE ? OR email LIKE ?",
            f"%{query}%", f"%{query}%", f"%{query}%"
        )

    if request.method == "POST":
        member_id = request.form.get("member_id")

        # Pull the absolute latest subscription end date for this member
        sub = db.execute(
            "SELECT end_date FROM subscriptions WHERE member_id = ? ORDER BY end_date DESC LIMIT 1",
            member_id
        )

        if not sub:
            flash("Access Denied: No active subscription file found for this member!", "danger")
            return redirect(url_for("checkin", q=query))

        # Date validation evaluation logic
        # Fixed: Made the comparison date match the 1-hour subtracted time
        today = (datetime.now() - timedelta(hours=1)).date()
        subscription_end = datetime.strptime(sub[0]["end_date"], "%Y-%m-%d").date()

        if today > subscription_end:
            flash(f"Access Denied: Subscription expired on {sub[0]['end_date']}!", "danger")
        else:
            # Fixed: Gets the server time, subtracts 1 hour, and records it
            pc_time = datetime.now() - timedelta(hours=1)
            pc_time_str = pc_time.strftime("%Y-%m-%d %H:%M:%S")
            db.execute("INSERT INTO attendance (member_id, check_in_time) VALUES (?, ?)", member_id, pc_time_str)
            flash("Access Granted: Check-in logged successfully.", "success")

        return redirect(url_for("checkin", q=query))

    return render_template("checkin.html", results=search_results, query=query)

@app.route("/attendance")
@login_required
def attendance():
    """Render historical ledger of verified gym access logs"""
    logs = db.execute("""
        SELECT a.check_in_time, m.first_name, m.last_name, m.email
        FROM attendance a
        JOIN members m ON a.member_id = m.id
        ORDER BY a.check_in_time DESC
    """)
    return render_template("attendance.html", logs=logs)

if __name__ == "__main__":
    app.run(debug=True)