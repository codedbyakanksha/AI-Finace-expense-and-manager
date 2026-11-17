
from flask import Flask, render_template, request, redirect, session, url_for, send_file, flash
import sqlite3
import io
import calendar
from datetime import date, datetime
from werkzeug.security import generate_password_hash, check_password_hash

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import pandas as pd
from sklearn.linear_model import LinearRegression
from reportlab.pdfgen import canvas


app = Flask(__name__, template_folder="template")
app.secret_key = "finance_manager_123"

INCOME_CATEGORIES = ["Salary"]

EXPENSE_CATEGORIES = [
    "Food", "Shopping", "Travel", "Education",
    "Bills", "Healthcare", "Entertainment", "Other"
]


# DATABASE CONNECTION
def connect():
    con = sqlite3.connect("finance.db")
    con.row_factory = sqlite3.Row
    return con


# CREATE DATABASE TABLES
def create_tables():
    con = connect()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            type TEXT NOT NULL,
            transaction_date TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            amount REAL NOT NULL,
            UNIQUE(user_id, month)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS savings_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            target REAL NOT NULL,
            saved REAL DEFAULT 0
        )
    """)

    con.commit()
    con.close()


create_tables()


# LOGIN CHECK
def login_required():
    return "user_id" in session

@app.route("/")
def home():
    if login_required():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# REGISTER
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]

        if not name or not email or len(password) < 6:
            flash("Please enter valid details. Password must have 6 characters.")
            return redirect(url_for("register"))

        con = connect()

        try:
            con.execute(
                "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password))
            )
            con.commit()
            flash("Registration successful! Please login.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("This email is already registered.")

        finally:
            con.close()

    return render_template("register.html")


# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]

        con = connect()
        user = con.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        con.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html")


# LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# DASHBOARD
@app.route("/dashboard")
def dashboard():
    if not login_required():
        return redirect(url_for("login"))

    con = connect()
    user_id = session["user_id"]

    income = con.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id=? AND type='Income'",
        (user_id,)
    ).fetchone()[0]

    expense = con.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id=? AND type='Expense'",
        (user_id,)
    ).fetchone()[0]

    total = con.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    recent = con.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY transaction_date DESC, id DESC LIMIT 5",
        (user_id,)
    ).fetchall()

    con.close()

    balance = income - expense

    return render_template(
        "dashboard.html",
        income=income,
        expense=expense,
        balance=balance,
        total=total,
        recent=recent
    )


# TRANSACTIONS
@app.route("/transactions", methods=["GET", "POST"])
def transactions():
    if not login_required():
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        title = request.form["title"].strip()
        category = request.form["category"]
        transaction_type = request.form["type"]
        transaction_date = request.form["transaction_date"]

        try:
            amount = float(request.form["amount"])

            if amount <= 0:
                raise ValueError

            if transaction_type == "Income":
                if category not in INCOME_CATEGORIES:
                    raise ValueError
            elif transaction_type == "Expense":
                if category not in EXPENSE_CATEGORIES:
                    raise ValueError
            else:
                raise ValueError

            datetime.strptime(transaction_date, "%Y-%m-%d")

        except (ValueError, TypeError):
            flash("Please enter valid transaction details.")
            return redirect(url_for("transactions"))

        con = connect()
        con.execute("""
            INSERT INTO transactions
            (user_id, title, amount, category, type, transaction_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id, title, amount, category,
            transaction_type, transaction_date
        ))
        con.commit()
        con.close()

        flash("Transaction added successfully!")
        return redirect(url_for("transactions"))

    search = request.args.get("search", "").strip()
    transaction_type = request.args.get("type", "")
    category = request.args.get("category", "")

    query = "SELECT * FROM transactions WHERE user_id=?"
    values = [user_id]

    if search:
        query += " AND title LIKE ?"
        values.append("%" + search + "%")

    if transaction_type in ["Income", "Expense"]:
        query += " AND type=?"
        values.append(transaction_type)

    if category in INCOME_CATEGORIES + EXPENSE_CATEGORIES:
        query += " AND category=?"
        values.append(category)

    query += " ORDER BY transaction_date DESC, id DESC"

    con = connect()
    records = con.execute(query, values).fetchall()
    con.close()

    return render_template(
        "transaction.html",
        records=records,
        today=date.today().isoformat(),
        income_categories=INCOME_CATEGORIES,
        expense_categories=EXPENSE_CATEGORIES,
        search=search,
        selected_type=transaction_type,
        selected_category=category
    )


# DELETE TRANSACTION
@app.route("/delete/<int:id>")
def delete_transaction(id):
    if not login_required():
        return redirect(url_for("login"))

    con = connect()
    con.execute(
        "DELETE FROM transactions WHERE id=? AND user_id=?",
        (id, session["user_id"])
    )
    con.commit()
    con.close()

    flash("Transaction deleted.")
    return redirect(url_for("transactions"))


# EXPENSE ANALYSIS
@app.route("/analysis")
def analysis():
    if not login_required():
        return redirect(url_for("login"))

    con = connect()

    rows = con.execute("""
        SELECT category, SUM(amount) AS total
        FROM transactions
        WHERE user_id=? AND type='Expense'
        GROUP BY category
    """, (session["user_id"],)).fetchall()

    con.close()

    categories = [row["category"] for row in rows]
    amounts = [row["total"] for row in rows]
    total_expense = sum(amounts)

    return render_template(
        "analysis.html",
        categories=categories,
        amounts=amounts,
        total_expense=total_expense
    )


# EXPENSE CHART
@app.route("/expense-chart")
def expense_chart():
    if not login_required():
        return redirect(url_for("login"))

    con = connect()
    rows = con.execute("""
        SELECT category, SUM(amount) AS total
        FROM transactions
        WHERE user_id=? AND type='Expense'
        GROUP BY category
    """, (session["user_id"],)).fetchall()
    con.close()

    if not rows:
        return "", 204

    names = [row["category"] for row in rows]
    amounts = [row["total"] for row in rows]

    plt.figure(figsize=(7, 5))
    plt.pie(amounts, labels=names, autopct="%1.1f%%")
    plt.title("Expense Distribution")
    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png")
    plt.close()
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png")


# EXPENSE FORECASTING
@app.route("/prediction")
def prediction():
    if not login_required():
        return redirect(url_for("login"))

    con = connect()

    rows = con.execute("""
        SELECT substr(transaction_date, 1, 7) AS month,
               SUM(amount) AS total
        FROM transactions
        WHERE user_id=? AND type='Expense'
        GROUP BY month
        ORDER BY month
    """, (session["user_id"],)).fetchall()

    con.close()

    predicted_expense = None
    message = "Add expense transactions to see a prediction."

    if len(rows) >= 2:
        data = pd.DataFrame([
            {"month": row["month"], "total": row["total"]}
            for row in rows
        ])

        data["number"] = range(len(data))

        model = LinearRegression()
        model.fit(data[["number"]], data["total"])

        next_number = [[len(data)]]
        predicted_expense = max(0, model.predict(next_number)[0])

        message = "Estimated using your previous monthly expenses."

    elif len(rows) == 1:
        predicted_expense = rows[0]["total"]
        message = "Only one month of data is available. This is a simple estimate."

    return render_template(
        "prediction.html",
        predicted_expense=predicted_expense,
        message=message
    )


# PDF RECEIPT
@app.route("/receipt/<int:id>")
def receipt(id):
    if not login_required():
        return redirect(url_for("login"))

    con = connect()
    item = con.execute(
        "SELECT * FROM transactions WHERE id=? AND user_id=?",
        (id, session["user_id"])
    ).fetchone()
    con.close()

    if not item:
        flash("Transaction not found.")
        return redirect(url_for("transactions"))

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)

    pdf.setTitle("Finance Transaction Receipt")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(150, 780, "FINANCE MANAGER RECEIPT")

    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, 730, "Receipt ID: " + str(item["id"]))
    pdf.drawString(50, 700, "Name: " + session["user_name"])
    pdf.drawString(50, 670, "Title: " + item["title"])
    pdf.drawString(50, 640, "Category: " + item["category"])
    pdf.drawString(50, 610, "Type: " + item["type"])
    pdf.drawString(50, 580, "Amount: Rs. " + str(item["amount"]))
    pdf.drawString(50, 550, "Date: " + item["transaction_date"])

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="receipt_" + str(item["id"]) + ".pdf",
        mimetype="application/pdf"
    )


# MONTHLY BUDGET
@app.route("/budget", methods=["GET", "POST"])
def budget():
    if not login_required():
        return redirect(url_for("login"))

    user_id = session["user_id"]
    selected_month = request.values.get(
        "month", date.today().strftime("%Y-%m")
    )

    try:
        datetime.strptime(selected_month, "%Y-%m")
    except ValueError:
        selected_month = date.today().strftime("%Y-%m")

    con = connect()

    if request.method == "POST":
        try:
            amount = float(request.form["amount"])

            if amount <= 0:
                raise ValueError

            con.execute("""
                INSERT INTO budgets (user_id, month, amount)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, month)
                DO UPDATE SET amount=excluded.amount
            """, (user_id, selected_month, amount))

            con.commit()
            flash("Monthly budget saved successfully!")

        except (ValueError, TypeError):
            flash("Enter a valid budget amount.")

        con.close()
        return redirect(url_for("budget", month=selected_month))

    budget_row = con.execute(
        "SELECT amount FROM budgets WHERE user_id=? AND month=?",
        (user_id, selected_month)
    ).fetchone()

    spent = con.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE user_id=? AND type='Expense'
        AND substr(transaction_date, 1, 7)=?
    """, (user_id, selected_month)).fetchone()[0]

    con.close()

    budget_amount = budget_row["amount"] if budget_row else 0
    remaining = budget_amount - spent
    percentage = (spent / budget_amount * 100) if budget_amount else 0

    return render_template(
        "budget.html",
        selected_month=selected_month,
        budget_amount=budget_amount,
        spent=spent,
        remaining=remaining,
        percentage=percentage
    )


# SAVINGS GOAL
@app.route("/savings", methods=["GET", "POST"])
def savings():
    if not login_required():
        return redirect(url_for("login"))

    user_id = session["user_id"]
    con = connect()

    if request.method == "POST":
        title = request.form["title"].strip()

        try:
            target = float(request.form["target"])
            saved = float(request.form.get("saved", 0))

            if not title or target <= 0 or saved < 0:
                raise ValueError

            con.execute("""
                INSERT INTO savings_goals (user_id, title, target, saved)
                VALUES (?, ?, ?, ?)
            """, (user_id, title, target, saved))

            con.commit()
            flash("Savings goal added!")

        except (ValueError, TypeError):
            flash("Enter valid savings goal details.")

        con.close()
        return redirect(url_for("savings"))

    goals = con.execute(
        "SELECT * FROM savings_goals WHERE user_id=? ORDER BY id DESC",
        (user_id,)
    ).fetchall()

    con.close()

    return render_template("savings.html", goals=goals)


# DELETE SAVINGS GOAL
@app.route("/delete-goal/<int:id>")
def delete_goal(id):
    if not login_required():
        return redirect(url_for("login"))

    con = connect()
    con.execute(
        "DELETE FROM savings_goals WHERE id=? AND user_id=?",
        (id, session["user_id"])
    )
    con.commit()
    con.close()

    flash("Savings goal deleted.")
    return redirect(url_for("savings"))


# MONTHLY REPORTS
@app.route("/reports")
def reports():
    if not login_required():
        return redirect(url_for("login"))

    con = connect()

    rows = con.execute("""
        SELECT substr(transaction_date, 1, 7) AS month,
        SUM(CASE WHEN type='Income' THEN amount ELSE 0 END) AS income,
        SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END) AS expense
        FROM transactions
        WHERE user_id=?
        GROUP BY month
        ORDER BY month DESC
    """, (session["user_id"],)).fetchall()

    con.close()

    return render_template("report.html", records=rows)


# EXPORT TO EXCEL
@app.route("/export-excel")
def export_excel():
    if not login_required():
        return redirect(url_for("login"))

    con = connect()
    rows = con.execute("""
        SELECT title, amount, category, type, transaction_date
        FROM transactions
        WHERE user_id=?
        ORDER BY transaction_date DESC
    """, (session["user_id"],)).fetchall()
    con.close()

    data = [dict(row) for row in rows]
    df = pd.DataFrame(data)

    if df.empty:
        df = pd.DataFrame(columns=[
            "title", "amount", "category", "type", "transaction_date"
        ])

    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Transactions")

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="finance_transactions.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# RUN PROJECT
if __name__ == "__main__":
    app.run(debug=False, port=5000)
