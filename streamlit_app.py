
import streamlit as st
import sqlite3
import qrcode
import json
import uuid
from io import BytesIO
from datetime import datetime
from pathlib import Path

# ---------------- PAGE CONFIG ----------------

st.set_page_config(
    page_title="CampusBites | RVRJC",
    page_icon="🍔",
    layout="wide"
)

DB_PATH = Path(__file__).parent / "campusbites.db"

# ---------------- MENU ----------------

DEFAULT_MENU = [
    {"name": "Veg Sandwich", "price": 40, "category": "Snacks"},
    {"name": "Veg Burger", "price": 60, "category": "Snacks"},
    {"name": "French Fries", "price": 50, "category": "Snacks"},
    {"name": "Samosa", "price": 15, "category": "Snacks"},
    {"name": "Veg Fried Rice", "price": 70, "category": "Meals"},
    {"name": "Veg Noodles", "price": 70, "category": "Meals"},
    {"name": "Chicken Fried Rice", "price": 100, "category": "Meals"},
    {"name": "Tea", "price": 10, "category": "Drinks"},
    {"name": "Coffee", "price": 15, "category": "Drinks"},
    {"name": "Lime Juice", "price": 25, "category": "Drinks"},
]

# ---------------- DATABASE ----------------

def get_connection():
    return sqlite3.connect(DB_PATH)

def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                price REAL NOT NULL,
                category TEXT NOT NULL,
                available INTEGER DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                token TEXT UNIQUE NOT NULL,
                student_name TEXT NOT NULL,
                college_id TEXT NOT NULL,
                items TEXT NOT NULL,
                total REAL NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        count = conn.execute(
            "SELECT COUNT(*) FROM menu"
        ).fetchone()[0]

        if count == 0:
            conn.executemany(
                """INSERT INTO menu
                   (name, price, category, available)
                   VALUES (?, ?, ?, 1)""",
                [
                    (item["name"], item["price"], item["category"])
                    for item in DEFAULT_MENU
                ]
            )

def get_menu():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, name, price, category
            FROM menu
            WHERE available = 1
            ORDER BY category, name
        """).fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
            "price": float(row[2]),
            "category": row[3]
        }
        for row in rows
    ]

def get_orders():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, order_id, token, student_name,
                   college_id, items, total, payment_method,
                   payment_status, status, created_at
            FROM orders
            ORDER BY id DESC
        """).fetchall()

def update_order_status(order_id, new_status):
    with get_connection() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?",
            (new_status, order_id)
        )

initialize_database()

# ---------------- SESSION STATE ----------------

if "cart_version" not in st.session_state:
    st.session_state.cart_version = 0

if "last_order" not in st.session_state:
    st.session_state.last_order = None

if "notice" not in st.session_state:
    st.session_state.notice = None

# ---------------- QR CODE ----------------

def create_qr(order_data):
    qr_content = {
        "order_id": order_data["order_id"],
        "pickup_token": order_data["token"],
        "student_name": order_data["student_name"],
        "college_id": order_data["college_id"],
        "items": order_data["items"],
        "total_inr": order_data["total"],
        "payment_method": order_data["payment_method"],
        "payment_status": order_data["payment_status"],
        "note": (
            "Order receipt only. Pay at the canteen counter. "
            "Staff must verify the physical college ID."
        )
    }

    qr = qrcode.QRCode(
        version=1,
        box_size=8,
        border=3
    )
    qr.add_data(json.dumps(qr_content, ensure_ascii=False))
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

# ---------------- CREATE ORDER ----------------

def place_order(student_name, college_id, payment_method, cart):
    order_id = "CB-" + uuid.uuid4().hex[:8].upper()
    token = uuid.uuid4().hex[:6].upper()

    total = sum(
        item["price"] * item["quantity"]
        for item in cart
    )

    items_json = json.dumps(cart)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO orders (
                order_id, token, student_name, college_id,
                items, total, payment_method, payment_status,
                status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            token,
            student_name.strip(),
            college_id.strip(),
            items_json,
            total,
            payment_method,
            "Pay at counter",
            "Preparing",
            created_at
        ))

    return {
        "order_id": order_id,
        "token": token,
        "student_name": student_name.strip(),
        "college_id": college_id.strip(),
        "items": cart,
        "total": total,
        "payment_method": payment_method,
        "payment_status": "Pay at counter",
        "status": "Preparing",
        "created_at": created_at
    }

# ---------------- STYLING ----------------

st.markdown("""
<style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    .food-card {
        border: 1px solid #dddddd;
        border-radius: 12px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .small-muted {
        color: #777777;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

# ---------------- HEADER ----------------

st.title("🍔 CampusBites")
st.caption("RVRJC College Canteen Ordering System")

if st.session_state.notice:
    st.success(st.session_state.notice)
    st.session_state.notice = None

order_tab, kitchen_tab, admin_tab = st.tabs([
    "🛒 Order Food",
    "👨‍🍳 Kitchen & Pickup",
    "📊 Admin"
])

# ==================================================
# ORDER FOOD
# ==================================================

with order_tab:
    st.subheader("Place your order")
    st.write("Choose your food, enter your student details, and submit.")

    menu = get_menu()

    if not menu:
        st.warning("No food items are currently available.")
    else:
        with st.form(
            key=f"order_form_{st.session_state.cart_version}"
        ):
            st.markdown("### 🍽️ Menu")

            cart = []
            categories = list(dict.fromkeys(
                item["category"] for item in menu
            ))

            for category in categories:
                st.markdown(f"#### {category}")

                category_items = [
                    item for item in menu
                    if item["category"] == category
                ]

                columns = st.columns(2)

                for index, item in enumerate(category_items):
                    with columns[index % 2]:
                        st.markdown(
                            f"**{item['name']}**  \n"
                            f"₹{item['price']:.2f}"
                        )

                        quantity = st.number_input(
                            f"Quantity — {item['name']}",
                            min_value=0,
                            max_value=20,
                            value=0,
                            step=1,
                            key=(
                                f"qty_{st.session_state.cart_version}_"
                                f"{item['id']}"
                            )
                        )

                        if quantity > 0:
                            cart.append({
                                "id": item["id"],
                                "name": item["name"],
                                "price": item["price"],
                                "quantity": int(quantity)
                            })

            st.markdown("---")
            st.markdown("### 🎓 Student details")

            student_name = st.text_input(
                "Student name",
                key=f"name_{st.session_state.cart_version}"
            )

            college_id = st.text_input(
                "College ID",
                key=f"college_{st.session_state.cart_version}"
            )

            payment_method = st.selectbox(
                "Payment option",
                [
                    "UPI at counter",
                    "Card at counter",
                    "Cash at counter"
                ],
                key=f"payment_{st.session_state.cart_version}"
            )

            total = sum(
                item["price"] * item["quantity"]
                for item in cart
            )

            st.markdown(f"### Total: ₹{total:.2f}")

            submitted = st.form_submit_button(
                "Place Order",
                type="primary",
                use_container_width=True
            )

        if submitted:
            if not student_name.strip():
                st.error("Please enter your student name.")
            elif not college_id.strip():
                st.error("Please enter your college ID.")
            elif not cart:
                st.error("Please select at least one food item.")
            else:
                try:
                    order_data = place_order(
                        student_name,
                        college_id,
                        payment_method,
                        cart
                    )

                    st.session_state.last_order = order_data

                    # Create new widget keys on the next run.
                    # Do NOT assign to existing quantity widget keys.
                    st.session_state.cart_version += 1

                    st.session_state.notice = (
                        f"Order placed successfully! "
                        f"Pickup token: {order_data['token']}"
                    )
                    st.rerun()

                except Exception as error:
                    st.error(f"Could not place the order: {error}")

    # Show the most recently placed order
    last_order = st.session_state.last_order

    if last_order:
        st.markdown("---")
        st.subheader("✅ Your order receipt")

        st.write(f"**Order ID:** {last_order['order_id']}")
        st.write(f"**Pickup token:** {last_order['token']}")
        st.write(f"**Student:** {last_order['student_name']}")
        st.write(f"**College ID:** {last_order['college_id']}")
        st.write(f"**Status:** {last_order['status']}")

        st.markdown("#### Items")
        for item in last_order["items"]:
            line_total = item["price"] * item["quantity"]
            st.write(
                f"- {item['name']} × {item['quantity']} "
                f"— ₹{line_total:.2f}"
            )

        st.markdown(f"### Total: ₹{last_order['total']:.2f}")
        st.write(f"**Payment option:** {last_order['payment_method']}")
        st.info(
            "This QR is an order receipt, not a payment QR. "
            "Pay at the counter. Staff must verify your physical "
            "college ID and pickup token."
        )

        qr_buffer = create_qr(last_order)

        st.image(qr_buffer, width=250)

        st.download_button(
            "Download Order QR",
            data=qr_buffer.getvalue(),
            file_name=f"{last_order['order_id']}_qr.png",
            mime="image/png"
        )

        receipt_text = (
            f"CampusBites - RVRJC\n"
            f"Order ID: {last_order['order_id']}\n"
            f"Pickup token: {last_order['token']}\n"
            f"Student: {last_order['student_name']}\n"
            f"College ID: {last_order['college_id']}\n"
            + "".join(
                f"{item['name']} x {item['quantity']} = "
                f"₹{item['price'] * item['quantity']:.2f}\n"
                for item in last_order["items"]
            )
            + f"Total: ₹{last_order['total']:.2f}\n"
            + f"Payment: {last_order['payment_method']}\n"
            + "Pay at the canteen counter.\n"
        )

        st.download_button(
            "Download Text Receipt",
            data=receipt_text,
            file_name=f"{last_order['order_id']}_receipt.txt",
            mime="text/plain"
        )

# ==================================================
# KITCHEN & PICKUP
# ==================================================

with kitchen_tab:
    st.subheader("Kitchen queue & pickup verification")
    st.caption(
        "Demo mode: staff should physically verify the student's "
        "college ID and pickup token."
    )

    if st.button("Refresh Orders"):
        st.rerun()

    orders = get_orders()
    active_orders = [
        order for order in orders
        if order[9] in ("Preparing", "Ready")
    ]

    if not active_orders:
        st.info("There are no active orders.")
    else:
        for order in active_orders:
            (
                db_id, order_id, token, name, college_id,
                items_json, total, payment_method,
                payment_status, status, created_at
            ) = order

            with st.container(border=True):
                st.markdown(f"### {order_id}")
                st.write(f"**Student:** {name}")
                st.write(f"**College ID:** {college_id}")
                st.write(f"**Pickup token:** `{token}`")
                st.write(f"**Status:** {status}")
                st.write(f"**Total:** ₹{total:.2f}")

                try:
                    items = json.loads(items_json)
                    for item in items:
                        st.write(
                            f"- {item['name']} × {item['quantity']}"
                        )
                except (json.JSONDecodeError, TypeError):
                    st.write(items_json)

                left, right = st.columns(2)

                with left:
                    if status == "Preparing":
                        if st.button(
                            "Mark Ready",
                            key=f"ready_{order_id}",
                            use_container_width=True
                        ):
                            update_order_status(order_id, "Ready")
                            st.rerun()

                with right:
                    if st.button(
                        "Confirm ID & Token — Collected",
                        key=f"collected_{order_id}",
                        use_container_width=True
                    ):
                        st.session_state[
                            f"verify_{order_id}"
                        ] = True

                if st.session_state.get(f"verify_{order_id}", False):
                    st.warning(
                        "Before confirming, physically check the "
                        "student's college ID and pickup token."
                    )

                    if st.button(
                        "Confirm collection",
                        key=f"confirm_{order_id}",
                        type="primary"
                    ):
                        update_order_status(order_id, "Collected")
                        st.session_state.pop(
                            f"verify_{order_id}", None
                        )
                        st.rerun()

    st.markdown("---")
    st.markdown("### Find an order")

    search_value = st.text_input(
        "Enter pickup token, order ID, or college ID",
        key="order_search"
    )

    if search_value.strip():
        matching = [
            order for order in orders
            if search_value.strip().lower() in {
                str(order[1]).lower(),
                str(order[2]).lower(),
                str(order[4]).lower()
            }
        ]

        if matching:
            for order in matching:
                st.write(
                    f"**{order[1]}** · {order[3]} · "
                    f"College ID: {order[4]} · "
                    f"Token: {order[2]} · Status: {order[9]}"
                )
        else:
            st.info("No matching order found.")

# ==================================================
# ADMIN
# ==================================================

with admin_tab:
    st.subheader("Admin dashboard")
    orders = get_orders()

    total_orders = len(orders)
    preparing_count = sum(o[9] == "Preparing" for o in orders)
    ready_count = sum(o[9] == "Ready" for o in orders)
    collected_count = sum(o[9] == "Collected" for o in orders)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Orders", total_orders)
    c2.metric("Preparing", preparing_count)
    c3.metric("Ready", ready_count)
    c4.metric("Collected", collected_count)

    st.markdown("### Order history")

    if orders:
        import pandas as pd

        table_rows = []
        for order in orders:
            table_rows.append({
                "Order ID": order[1],
                "Token": order[2],
                "Student": order[3],
                "College ID": order[4],
                "Items": order[5],
                "Total (₹)": order[6],
                "Payment Option": order[7],
                "Payment Status": order[8],
                "Status": order[9],
                "Created At": order[10]
            })

        df = pd.DataFrame(table_rows)
        st.dataframe(df, use_container_width=True)

        st.download_button(
            "Download Order History CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="campusbites_orders.csv",
            mime="text/csv"
        )
    else:
        st.info("No orders have been placed yet.")

    st.markdown("### Available menu")
    menu = get_menu()

    if menu:
        for item in menu:
            st.write(
                f"**{item['name']}** — ₹{item['price']:.2f} "
                f"({item['category']})"
            )

    st.warning(
        "Demo application: Kitchen and Admin tabs have no login. "
        "Do not use this version for real student payments or "
        "sensitive production data."
    )
