import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime
from bson.objectid import ObjectId

app = Flask(__name__, static_folder="static")
CORS(app)

# Mongo connection
client   = MongoClient("mongodb://localhost:27017/")
db       = client["project_data"]
prod_col = db["product_data"]
user_col = db["user_data"]

sale_col = db["sale_data"]
order_col = db["order_data"]
buy_col = db["buy_data"]
log_col   = db["log_data"]

# ------------ FRONTEND ROUTES ------------

# Serve signup page
@app.route("/signup", methods=["GET"])
def serve_signup():
    return send_from_directory(app.static_folder, "signup.html")

# Serve login page
@app.route("/login", methods=["GET"])
def serve_login():
    return send_from_directory(app.static_folder, "login.html")

# Fallback: serve other static pages (inventory, dashboard, etc.)
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    # Default to inventory page
    return send_from_directory(app.static_folder, "inventory.html")

# ------------ PRODUCT CRUD API (unchanged) ------------

@app.route("/api/products", methods=["GET"])
def get_products():
    prods = list(prod_col.find({}, {"_id":0}))
    return jsonify(prods), 200

@app.route("/api/products/<barcode>", methods=["GET"])
def get_product(barcode):
    p = prod_col.find_one({"barcode": barcode}, {"_id":0})
    return (jsonify(p), 200) if p else (jsonify({"error":"Not found"}), 404)

@app.route("/api/products", methods=["POST"])
def add_product():
    data = request.json
    if prod_col.find_one({"barcode": data["barcode"]}):
        return jsonify({"error":"Barcode exists"}), 400
    prod_col.insert_one(data)
    return jsonify({"message":"Added"}), 201

@app.route("/api/products/<barcode>", methods=["PUT"])
def update_product(barcode):
    data = request.json
    existing = prod_col.find_one({"barcode": barcode})
    if not existing:
        return jsonify({"error":"Not found"}), 404
    new_bc = data.get("barcode", barcode)
    if new_bc != barcode and prod_col.find_one({"barcode": new_bc}):
        return jsonify({"error":"New barcode exists"}), 400
    prod_col.update_one({"barcode": barcode}, {"$set": data})
    return jsonify({"message":"Updated"}), 200

@app.route("/api/products/<barcode>", methods=["DELETE"])
def delete_product(barcode):
    res = prod_col.delete_one({"barcode": barcode})
    if res.deleted_count:
        return jsonify({"message":"Deleted"}), 200
    return jsonify({"error":"Not found"}), 404

# ------------ AUTHENTICATION API ------------

# helper to serialize ObjectId
def serialize_user(doc):
    doc["id"] = str(doc.pop("_id"))
    return doc

# allowed roles
ALLOWED_ROLES = {"employee", "admin", "owner", "supplier"}

# 1) SIGN UP
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json or {}
    # check required
    for fld in ("name", "role", "age", "username", "email", "password"):
        if fld not in data:
            return jsonify({"error": f"Missing {fld}"}), 400

    # validate role
    if data["role"] not in ALLOWED_ROLES:
        return jsonify({"error": "Invalid role"}), 400

    # unique username/email
    if user_col.find_one({"username": data["username"]}):
        return jsonify({"error": "Username taken"}), 400
    if user_col.find_one({"email": data["email"]}):
        return jsonify({"error": "Email registered"}), 400

    # build new document
    new_user = {
        "name":     data["name"],
        "role":     data["role"],
        "age":      int(data["age"]),
        "username": data["username"],
        "email":    data["email"],
        "password": data["password"],  # TODO: hash in production
        "verified": False
    }
    user_col.insert_one(new_user)
    return jsonify({"message": "User registered"}), 201

# 2) LOGIN
@app.route("/api/login", methods=["POST"])
def login():
    data   = request.json or {}
    usernm = data.get("username")
    pwd    = data.get("password")
    if not usernm or not pwd:
        return jsonify({"error": "Username and password required"}), 400

    user = user_col.find_one({"username": usernm}, {"_id": 0})
    if not user or user.get("password") != pwd:
        return jsonify({"error": "Invalid credentials"}), 401

    if not user.get("verified", False):
        return jsonify({"error": "Account not verified"}), 403

    user.pop("password", None)
    return jsonify({"message": "Login successful", "user": user}), 200

# 3) GET all users
@app.route("/api/users", methods=["GET"])
def get_users():
    docs = list(user_col.find())
    users = [serialize_user(d) for d in docs]
    return jsonify(users), 200

# 4) GET single user by username
@app.route("/api/users/<username>", methods=["GET"])
def get_user(username):
    doc = user_col.find_one({"username": username})
    if not doc:
        return jsonify({"error": "User not found"}), 404
    return jsonify(serialize_user(doc)), 200

# 5) UPDATE user
@app.route("/api/users/<username>", methods=["PUT"])
def update_user(username):
    data = request.json or {}
    existing = user_col.find_one({"username": username})
    if not existing:
        return jsonify({"error": "User not found"}), 404

    # if updating username/email, check uniqueness
    new_un = data.get("username")
    if new_un and new_un != username:
        if user_col.find_one({"username": new_un}):
            return jsonify({"error": "Username taken"}), 400

    new_email = data.get("email")
    if new_email and new_email != existing.get("email"):
        if user_col.find_one({"email": new_email}):
            return jsonify({"error": "Email registered"}), 400

    # validate role if provided
    if "role" in data and data["role"] not in ALLOWED_ROLES:
        return jsonify({"error": "Invalid role"}), 400

    # cast age to int if provided
    if "age" in data:
        data["age"] = int(data["age"])

    user_col.update_one({"username": username}, {"$set": data})
    return jsonify({"message": "User updated"}), 200

# 6) DELETE user
@app.route("/api/users/<username>", methods=["DELETE"])
def delete_user(username):
    res = user_col.delete_one({"username": username})
    if res.deleted_count == 0:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"message": "User deleted"}), 200


# ------------ SALES API ------------
# 1) Create a new sale
@app.route("/api/sales", methods=["POST"])
def create_sale():
    data = request.json or {}
    # 1.1 Validate input
    for fld in ("barcode", "quantity"):
        if fld not in data:
            return jsonify({"error": f"Missing {fld}"}), 400

    barcode = data["barcode"]
    try:
        qty = int(data["quantity"])
    except:
        return jsonify({"error": "Quantity must be a number"}), 400

    # 1.2 Lookup product
    prod = prod_col.find_one({"barcode": barcode})
    if not prod:
        return jsonify({"error": "Product not found"}), 404

    # 1.3 Stock check
    if prod["quantity"] < qty:
        return jsonify({"error": "Insufficient stock"}), 400

    price = prod["price"]
    total = round(price * qty, 2)

    # 1.4 Determine sale_date
    if "sale_date" in data:
        try:
            sale_date = datetime.fromisoformat(data["sale_date"])
        except:
            return jsonify({"error": "Invalid sale_date format"}), 400
    else:
        sale_date = datetime.utcnow()

    # 1.5 Insert into sale_data
    sale_doc = {
        "barcode":   barcode,
        "quantity":  qty,
        "price":     price,
        "total":     total,
        "sale_date": sale_date
    }
    result = sale_col.insert_one(sale_doc)

    # 1.6 Deduct from product_data
    prod_col.update_one(
        {"barcode": barcode},
        {"$inc": {"quantity": -qty}}
    )

    # 1.7 Respond
    sale_doc["id"] = str(result.inserted_id)
    sale_doc["sale_date"] = sale_date.isoformat()
    return jsonify(sale_doc), 201


# 2) List all sales (optional filtering by date or barcode)
@app.route("/api/sales", methods=["GET"])
def list_sales():
    query = {}
    # ?barcode=1234
    bc = request.args.get("barcode")
    if bc:
        query["barcode"] = bc

    # ?start=2025-07-01&end=2025-07-31
    start = request.args.get("start")
    end   = request.args.get("end")
    if start or end:
        tsq = {}
        if start:
            tsq["$gte"] = datetime.fromisoformat(start)
        if end:
            tsq["$lte"] = datetime.fromisoformat(end)
        query["sale_date"] = tsq

    docs = list(sale_col.find(query).sort("sale_date", -1))
    for d in docs:
        d["id"] = str(d.pop("_id"))
        d["sale_date"] = d["sale_date"]
    return jsonify(docs), 200

# ------------ ORDER API ------------
# Create a new order
@app.route("/api/orders", methods=["POST"])
def create_order():
    data = request.json or {}
    required = ("order_id", "barcode", "product_name", "quantity", "price")
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing {field}"}), 400

    data["order_date"] = datetime.utcnow()
    data["pending"]    = data.get("pending", False)
    order_col.insert_one(data)
    return jsonify({"message": "Order created"}), 201


# Read (list) orders, optionally filtered by pending status
@app.route("/api/orders", methods=["GET"])
def read_orders():
    query   = {}
    pending = request.args.get("pending")  # /api/orders?pending=true
    if pending is not None:
        query["pending"] = pending.lower() == "true"

    orders = list(order_col.find(query).sort("order_date", -1))
    for o in orders:
        o["id"]         = str(o.pop("_id"))
        o["order_date"] = o["order_date"]
    return jsonify(orders), 200


# Read a single order by order_id
@app.route("/api/orders/<order_id>", methods=["GET"])
def read_order(order_id):
    o = order_col.find_one({"order_id": order_id})
    if not o:
        return jsonify({"error": "Order not found"}), 404
    o["id"]         = str(o.pop("_id"))
    o["order_date"] = o["order_date"]
    return jsonify(o), 200


# Update an order (partial fields)
@app.route("/api/orders/<order_id>", methods=["PATCH"])
def update_order(order_id):
    data = request.json or {}
    result = order_col.update_one(
        {"order_id": order_id},
        {"$set": data}
    )
    if result.matched_count == 0:
        return jsonify({"error": "Order not found"}), 404
    return jsonify({"message": "Order updated"}), 200


# Delete an order
@app.route("/api/orders/<order_id>", methods=["DELETE"])
def delete_order(order_id):
    result = order_col.delete_one({"order_id": order_id})
    if result.deleted_count == 0:
        return jsonify({"error": "Order not found"}), 404
    return jsonify({"message": "Order deleted"}), 200


# ------------ PURCHASE API ------------
@app.route("/api/buys", methods=["POST"])
def create_buy():
    data = request.json or {}
    required = ("barcode", "quantity", "price")
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing {field}"}), 400

    # timestamp the record
    data["buy_date"] = datetime.utcnow()
    buy_col.insert_one(data)
    return jsonify({"message": "Purchase recorded"}), 201

# 2) READ all purchases
@app.route("/api/buys", methods=["GET"])
def list_buys():
    docs = list(buy_col.find().sort("buy_date", -1))
    for d in docs:
        d["id"]       = str(d.pop("_id"))
        d["buy_date"] = d["buy_date"]
    return jsonify(docs), 200

# 3) READ a single purchase by its ObjectId
@app.route("/api/buys/<id>", methods=["GET"])
def get_buy(id):
    try:
        o = buy_col.find_one({"_id": ObjectId(id)})
    except:
        o = None
    if not o:
        return jsonify({"error": "Purchase not found"}), 404

    o["id"]       = str(o.pop("_id"))
    o["buy_date"] = o["buy_date"]
    return jsonify(o), 200

# 4) UPDATE a purchase (partial)
@app.route("/api/buys/<id>", methods=["PATCH"])
def update_buy(id):
    data = request.json or {}
    try:
        result = buy_col.update_one(
            {"_id": ObjectId(id)},
            {"$set": data}
        )
    except:
        return jsonify({"error": "Invalid ID"}), 400

    if result.matched_count == 0:
        return jsonify({"error": "Purchase not found"}), 404
    return jsonify({"message": "Purchase updated"}), 200

# 5) DELETE a purchase
@app.route("/api/buys/<id>", methods=["DELETE"])
def delete_buy(id):
    try:
        result = buy_col.delete_one({"_id": ObjectId(id)})
    except:
        return jsonify({"error": "Invalid ID"}), 400

    if result.deleted_count == 0:
        return jsonify({"error": "Purchase not found"}), 404
    return jsonify({"message": "Purchase deleted"}), 200


# ------------ LOGS API ------------
# helper to serialize ObjectId
def serialize_log(doc):
    doc["id"] = str(doc.pop("_id"))
    return doc

# 1) GET all logs
@app.route("/api/logs", methods=["GET"])
def get_logs():
    docs = list(log_col.find().sort("login", 1))
    logs = [serialize_log(d) for d in docs]
    return jsonify(logs), 200

# 2) GET logs for a specific user
@app.route("/api/logs/<username>", methods=["GET"])
def get_logs_for_user(username):
    docs = list(log_col.find({"username": username}).sort("login", 1))
    logs = [serialize_log(d) for d in docs]
    return jsonify(logs), 200

# 3) CREATE a new log entry
@app.route("/api/logs", methods=["POST"])
def add_log():
    data = request.get_json() or {}
    # require at least username and login timestamp
    for fld in ("username", "login"):
        if fld not in data:
            return jsonify({"error": f"Missing {fld}"}), 400

    new_log = {
        "username": data["username"],
        "login":    data["login"],
        # logout can be added now or left None
        "logout":   data.get("logout")
    }
    log_col.insert_one(new_log)
    return jsonify({"message": "Log entry created"}), 201


if __name__ == "__main__":
    app.run(debug=True)