import os
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session,
)
import mysql.connector
import pandas as pd
from functools import wraps

app = Flask(__name__)

# -----------------------------------------
# SECRET KEY (REQUIRED FOR LOGIN SESSIONS)
# -----------------------------------------
# -----------------------------------------
# SECRET KEY (REQUIRED FOR LOGIN SESSIONS)
# -----------------------------------------
app.secret_key = os.environ.get("SECRET_KEY", "change_this_local_secret")

# -----------------------------------------
# SIMPLE ADMIN CREDENTIALS (OVERRIDDEN BY ENV VARS IN PRODUCTION)
# -----------------------------------------
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# -----------------------------------------
# DATABASE CONFIG
# -----------------------------------------
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "2507"),
    "database": os.environ.get("DB_NAME", "tracking_service_db")
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def norm(name: str) -> str:
    """Normalize Excel column names."""
    return str(name).strip().lower().replace(" ", "").replace(".", "")


# -----------------------------------------
# LOGIN REQUIRED DECORATOR
# -----------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            next_url = request.path
            return redirect(url_for("admin_login", next=next_url))
        return f(*args, **kwargs)
    return wrapper


# -----------------------------------------
# HOME ROUTE
# -----------------------------------------
@app.route("/")
def home():
    return "Tracking Service is Running!"


# -----------------------------------------
# TEST DB
# -----------------------------------------
@app.route("/test-db")
def test_db():
    try:
        conn = get_db_connection()
        conn.close()
        return "MySQL Connection Successful!"
    except Exception as e:
        return f"MySQL Connection Failed: {e}"


# -----------------------------------------
# ADMIN LOGIN / LOGOUT
# -----------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    next_url = request.args.get("next") or url_for("admin_dashboard")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        next_url = request.form.get("next") or url_for("admin_dashboard")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(next_url)
        else:
            error = "Invalid username or password."

    return render_template("login.html", error=error, next=next_url)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# -----------------------------------------
# ADMIN: UPLOAD EXCEL (PROTECTED)
# -----------------------------------------
@app.route("/admin/upload", methods=["GET", "POST"])
@login_required
def upload_page():
    if request.method == "GET":
        return render_template("upload.html")

    file = request.files.get("file")
    if not file:
        return "No file selected"

    try:
        df = pd.read_excel(file)
        df.columns = [norm(c) for c in df.columns]

        required_cols = [
            "slno",          # Sl.no
            "name",
            "orderid",
            "pincode",
            "phonenumber",
            "tracknumber",
            "weight",
            "couriername",
        ]
        for col in required_cols:
            if col not in df.columns:
                return f"Missing column in Excel (after normalize): {col}"

        conn = get_db_connection()
        cursor = conn.cursor()
        inserted = 0

        for _, row in df.iterrows():
            customer_name = str(row["name"]).strip()
            order_id = str(row["orderid"]).strip()
            phone = str(row["phonenumber"]).strip()
            pincode = str(row["pincode"]).strip()
            tracking_number = str(row["tracknumber"]).strip()
            weight = str(row["weight"]).strip()
            courier_name = str(row["couriername"]).strip()

            courier_name_lower = courier_name.lower()
            if courier_name_lower == "dtdc":
                courier_site = (
                    "https://www.dtdc.in/tracking.asp?"
                    f"Ttype=awb&strCNNo={tracking_number}"
                )
            elif courier_name_lower in ["india post", "indian post"]:
                courier_site = (
                    "https://www.indiapost.gov.in/_layouts/15/"
                    f"dop.portal.tracking/trackconsignment.aspx?consignmentno={tracking_number}"
                )
            else:
                courier_site = ""

            sql = """
                INSERT INTO shipments
                (customer_name, order_id, phone, pincode,
                 tracking_number, weight, courier_name, courier_site)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                customer_name,
                order_id,
                phone,
                pincode,
                tracking_number,
                weight,
                courier_name,
                courier_site,
            )
            cursor.execute(sql, values)
            inserted += 1

        conn.commit()
        cursor.close()
        conn.close()

        return f"Excel uploaded! Total rows inserted: {inserted}"

    except Exception as e:
        return f"Error processing file: {e}"


# -----------------------------------------
# PUBLIC API: TRACK BY PHONE OR ORDER ID
# -----------------------------------------
@app.route("/api/track", methods=["GET"])
def track_by_phone_or_order():
    phone = request.args.get("phone", "").strip()
    order_id = request.args.get("order_id", "").strip()

    if not phone and not order_id:
        return jsonify({"error": "Provide phone or order_id parameter"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        where_clauses = []
        params = []

        if phone:
            where_clauses.append("phone = %s")
            params.append(phone)

        if order_id:
            where_clauses.append("order_id = %s")
            params.append(order_id)

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT customer_name, order_id, phone, pincode,
                   tracking_number, weight, courier_name, courier_site, updated_at
            FROM shipments
            WHERE {where_sql}
            ORDER BY updated_at DESC
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return jsonify({"results": [], "message": "No orders found for given details."})

        return jsonify({"results": rows})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------------------
# ADMIN DASHBOARD (PROTECTED)
# -----------------------------------------
@app.route("/admin")
@login_required
def admin_dashboard():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM shipments")
        overall_total = cursor.fetchone()[0]

        where_clauses = []
        params = []

        if start_date:
            where_clauses.append("DATE(updated_at) >= %s")
            params.append(start_date)

        if end_date:
            where_clauses.append("DATE(updated_at) <= %s")
            params.append(end_date)

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        cursor.execute("SELECT COUNT(*) FROM shipments" + where_sql, params)
        total_orders = cursor.fetchone()[0]

        courier_query = """
            SELECT courier_name, COUNT(*)
            FROM shipments
        """ + where_sql + " GROUP BY courier_name"

        cursor.execute(courier_query, params)
        courier_stats = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            "admin.html",
            overall_total=overall_total,
            total_orders=total_orders,
            courier_stats=courier_stats,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        return f"Error loading admin dashboard: {e}"


# -----------------------------------------
# ADMIN ORDER HISTORY (PROTECTED)
# -----------------------------------------
@app.route("/admin/orders")
@login_required
def admin_orders():
    query = request.args.get("q", "").strip()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    courier_filter = request.args.get("courier", "").strip()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        where_clauses = []
        params = []

        if query:
            where_clauses.append("""
                (
                    customer_name LIKE %s OR 
                    phone LIKE %s OR 
                    order_id LIKE %s OR 
                    courier_name LIKE %s
                )
            """)
            wildcard = f"%{query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        if start_date:
            where_clauses.append("DATE(updated_at) >= %s")
            params.append(start_date)

        if end_date:
            where_clauses.append("DATE(updated_at) <= %s")
            params.append(end_date)

        if courier_filter:
            where_clauses.append("courier_name = %s")
            params.append(courier_filter)

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        query_sql = f"""
            SELECT *
            FROM shipments
            {where_sql}
            ORDER BY updated_at DESC
        """

        cursor.execute(query_sql, params)
        orders = cursor.fetchall()

        cursor.execute("SELECT DISTINCT courier_name FROM shipments")
        courier_rows = cursor.fetchall()
        couriers = [row["courier_name"] for row in courier_rows if row["courier_name"]]

        cursor.close()
        conn.close()

        return render_template(
            "admin_orders.html",
            orders=orders,
            query=query,
            start_date=start_date,
            end_date=end_date,
            couriers=couriers,
            courier_filter=courier_filter
        )

    except Exception as e:
        return f"Error loading order history: {e}"


# -----------------------------------------
# PUBLIC TRACK PAGE (HTML)
# -----------------------------------------
@app.route("/track")
def track_page():
    return render_template("track.html")


# -----------------------------------------
# START SERVER
# -----------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
