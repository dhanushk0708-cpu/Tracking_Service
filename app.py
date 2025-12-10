from flask import Flask, render_template, request, jsonify
import mysql.connector
import pandas as pd

app = Flask(__name__)

# -----------------------------------------
# DATABASE CONFIG
# -----------------------------------------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",          # change if needed
    "password": "2507",      # your MySQL password
    "database": "tracking_service_db"
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def norm(name: str) -> str:
    """Normalize Excel column names."""
    return str(name).strip().lower().replace(" ", "").replace(".", "")


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
# ADMIN: UPLOAD EXCEL
# -----------------------------------------
@app.route("/admin/upload", methods=["GET", "POST"])
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
# PUBLIC API: TRACK BY PHONE
# -----------------------------------------
# -----------------------------------------
# PUBLIC API: TRACK BY PHONE OR ORDER ID
# -----------------------------------------
@app.route("/api/track", methods=["GET"])
def track_by_phone_or_order():
    phone = request.args.get("phone", "").strip()
    order_id = request.args.get("order_id", "").strip()

    # At least one filter required
    if not phone and not order_id:
        return jsonify({"error": "Provide phone or order_id parameter"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Build WHERE clause dynamically
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

    
@app.route("/track")
def track_page():
    return render_template("track.html")

@app.route("/admin")
def admin_dashboard():
    # Get date filter values from URL, e.g. /admin?start_date=2025-12-01&end_date=2025-12-10
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Overall total (without any filter)
        cursor.execute("SELECT COUNT(*) FROM shipments")
        overall_total = cursor.fetchone()[0]

        # Build WHERE clause for date filter using updated_at
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

        # Total orders in selected date range
        cursor.execute("SELECT COUNT(*) FROM shipments" + where_sql, params)
        total_orders = cursor.fetchone()[0]

        # Orders by courier in selected date range
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
    
@app.route("/admin/orders")
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

        # Search filter
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

        # Date filters
        if start_date:
            where_clauses.append("DATE(updated_at) >= %s")
            params.append(start_date)

        if end_date:
            where_clauses.append("DATE(updated_at) <= %s")
            params.append(end_date)

        # Courier filter
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

        # Load distinct couriers for dropdown (use dict keys!)
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
# START SERVER
# -----------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
