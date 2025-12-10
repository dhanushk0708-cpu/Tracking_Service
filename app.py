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
@app.route("/api/track", methods=["GET"])
def track_by_phone():
    phone = request.args.get("phone", "").strip()

    if not phone:
        return jsonify({"error": "phone parameter is required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT customer_name, order_id, phone, pincode,
                   tracking_number, weight, courier_name, courier_site, updated_at
            FROM shipments
            WHERE phone = %s
            ORDER BY updated_at DESC
            """,
            (phone,),
        )

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return jsonify({"results": [], "message": "No orders found for this phone number."})

        return jsonify({"results": rows})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/track")
def track_page():
    return render_template("track.html")



# -----------------------------------------
# START SERVER
# -----------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
