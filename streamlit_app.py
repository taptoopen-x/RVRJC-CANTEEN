
import json
import sqlite3
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import qrcode
import streamlit as st

# ==================================================
# PAGE CONFIG
# ==================================================

st.set_page_config(
    page_title="CampusBites | RVRJC",
    page_icon="🍔",
    layout="wide",
)

DB_PATH = Path(__file__).parent / "campusbites_v2.db"

# Enter the canteen's REAL UPI ID here to enable payment QR.
# Example format: canteenname@bank
MERCHANT_UPI_ID = ""
MERCHANT_NAME = "RVRJC Canteen"

DEFAULT_MENU = [
    ("Veg Sandwich", 40, "Snacks"),
    ("Veg Burger", 60, "Snacks"),
    ("French Fries", 50, "Snacks"),
    ("Samosa", 15, "Snacks"),
    ("Veg Fried Rice", 70, "Meals"),
    ("Veg Noodles", 70, "Meals"),
    ("Chicken Fried Rice", 100, "Meals"),
    ("Tea", 10, "Drinks"),
    ("Coffee", 15, "Drinks"),
    ("Lime Juice", 25, "Drinks"),
]


# ==================================================
# DATABASE
# ==================================================

def get_connection():
    return sqlite3.connect(str(DB_PATH), timeout=20)


def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                price REAL NOT NULL,
                category TEXT NOT NULL,
                available INTEGER NOT NULL DEFAULT 1
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
            conn.executemany("""
                INSERT INTO menu (name, price, category, available)
                VALUES (?, ?, ?, 1)
            """, DEFAULT_MENU)


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
            "category": row[3],
        }
        for row in rows
    ]


def get_orders():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, order_id, token, student_name, college_id,
                   items, total, payment_method, payment_status,
                   status, created_at
            FROM orders
            ORDER BY id DESC
        """).fetchall()


def save_order(order):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO orders (
                order_id, token, student_name, college_id, items,
                total, payment_method, payment_status, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order["order_id"],
            order["token"],
            order["student_name"],
            order["college_id"],
            json.dumps(order["items"]),
            order["total"],
            order["payment_method"],
            order["payment_status"],
            order["status"],
            order["created_at"],
        ))


def change_status(order_id, status):
    with get_connection() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?",
            (status, order_id),
        )


# ==================================================
# QR HELPERS
# ==================================================

def qr_image_bytes(text):
    qr = qrcode.QRCode(box_size=8, border=3)
    qr.add_data(text)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_payment_qr(order):
    if not MERCHANT_UPI_ID.strip():
        return None

    params = {
        "pa": MERCHANT_UPI_ID.strip(),
        "pn": MERCHANT_NAME,
        "am": f"{order['total']:.2f}",
        "cu": "INR",
        "tn": f"CampusBites {order['order_id']}",
    }

    return qr_image_bytes("upi://pay?" + urlencode(params))


def make_receipt_qr(order):
    details = {
        "type": "CampusBites order receipt",
        "order_id": order["order_id"],
        "pickup_token": order["token"],
        "student_name": order["student_name"],
        "college_id": order["college_id"],
        "items": order["items"],
        "total_inr": order["total"],
        "payment_method": order["payment_method"],
        "payment_status": order["payment_status"],
        "note": "Order receipt only, not proof of payment.",
    }

    return qr_image_bytes(
        json.dumps(details, ensure_ascii=False)
    )


# ==================================================
# APP INITIALIZATION
# ==================================================

initialize_database()

if "cart_version" not in st.session_state:
    st.session_state.cart_version = 0

if "notice" not in st.session_state:
    st.session_state.notice = None

if "order_just_placed" not in st.session_state:
    st.session_state.order_just_placed = False


# ==================================================
# STYLING
# ==================================================

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}
</style>
""", unsafe_allow_html=True)


# ==================================================
# HEADER
# ==================================================

st.title("🍔 CampusBites")
st.caption("RVRJC College Canteen Ordering System")

if st.session_state.notice:
    st.success(st.session_state.notice)
    st.session_state.notice = None

order_tab, kitchen_tab, admin_tab = st.tabs([
    "🛒 Order Food",
    "👨‍🍳 Kitchen & Pickup",
    "📊 Admin",
])


# ==================================================
# TAB 1: ORDER FOOD
# ==================================================

with order_tab:
    if st.session_state.order_just_placed:
        st.success("✅ Order placed successfully!")
        st.info(
            "Your order has been sent to the canteen. "
            "You can place a new order below."
        )
        st.session_state.order_just_placed = False

    st.subheader("Place your order")
    st.write("Select food quantities and your payment method.")

    menu = get_menu()
    version = st.session_state.cart_version
    cart = []

    if not menu:
        st.warning("No menu items are available.")
    else:
        categories = list(dict.fromkeys(
            item["category"] for item in menu
        ))

        # Quantities update on every Streamlit rerun.
        for category in categories:
            st.markdown(f"### {category}")

            category_items = [
                item for item in menu
                if item["category"] == category
            ]

            columns = st.columns(2)

            for index, item in enumerate(category_items):
                with columns[index % 2]:
                    st.markdown(f"**{item['name']}**")
                    st.write(f"₹{item['price']:.2f}")

                    quantity = st.number_input(
                        f"Quantity — {item['name']}",
                        min_value=0,
                        max_value=20,
                        value=0,
                        step=1,
                        key=f"qty_{version}_{item['id']}",
                    )

                    if quantity > 0:
                        cart.append({
                            "id": item["id"],
                            "name": item["name"],
                            "price": item["price"],
                            "quantity": int(quantity),
                        })

        # Correct live total
        total = round(sum(
            item["price"] * item["quantity"]
            for item in cart
        ), 2)

        st.divider()
        st.subheader(f"Total amount: ₹{total:.2f}")

        st.markdown("### 🎓 Student details")

        student_name = st.text_input(
            "Student name",
            key=f"name_{version}",
        )

        college_id = st.text_input(
            "College ID",
            key=f"college_{version}",
        )

        payment_method = st.radio(
            "Choose payment method",
            [
                "Cash",
                "UPI QR",
                "UPI ID",
                "Razorpay / Card",
            ],
            key=f"payment_{version}",
        )

        if payment_method == "Cash":
            st.info("Pay cash at the canteen counter.")

        elif payment_method == "UPI QR":
            if MERCHANT_UPI_ID.strip():
                st.info(
                    "A payment QR will be generated after placing "
                    "the order."
                )
            else:
                st.warning(
                    "Demo mode: the canteen's real UPI ID must be "
                    "configured to enable payment QR."
                )

        elif payment_method == "UPI ID":
            if MERCHANT_UPI_ID.strip():
                st.write(f"Pay to UPI ID: `{MERCHANT_UPI_ID}`")
            else:
                st.warning(
                    "The official canteen UPI ID has not been configured."
                )

        elif payment_method == "Razorpay / Card":
            st.info(
                "Demo option only. Real card payments require "
                "a connected payment gateway."
            )

        place_clicked = st.button(
            "Place Order",
            type="primary",
            use_container_width=True,
            disabled=(not cart),
            key=f"place_{version}",
        )

        if place_clicked:
            if not student_name.strip():
                st.error("Please enter your student name.")
            elif not college_id.strip():
                st.error("Please enter your college ID.")
            else:
                if payment_method == "Cash":
                    payment_status = "Pay cash at counter"
                elif payment_method in ("UPI QR", "UPI ID"):
                    payment_status = (
                        "Awaiting payment"
                        if MERCHANT_UPI_ID.strip()
                        else "Demo - payment not configured"
                    )
                else:
                    payment_status = "Demo - gateway not connected"

                order = {
                    "order_id": "CB-" + uuid.uuid4().hex[:8].upper(),
                    "token": uuid.uuid4().hex[:6].upper(),
                    "student_name": student_name.strip(),
                    "college_id": college_id.strip(),
                    "items": cart,
                    "total": total,
                    "payment_method": payment_method,
                    "payment_status": payment_status,
                    "status": "Preparing",
                    "created_at": datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                }

                try:
                    save_order(order)

                    # Don't keep or show the old order receipt.
                    st.session_state.cart_version += 1
                    st.session_state.order_just_placed = True

                    # New widget keys reset the cart safely.
                    st.rerun()

                except sqlite3.Error:
                    st.error(
                        "Could not save the order. Please try again."
                    )


# ==================================================
# TAB 2: KITCHEN & PICKUP
# ==================================================

with kitchen_tab:
    st.subheader("Kitchen queue & pickup")
    st.caption(
        "Staff must verify the student's physical college ID "
        "and pickup token."
    )

    if st.button("Refresh orders"):
        st.rerun()

    try:
        orders = get_orders()
    except sqlite3.Error:
        orders = []
        st.error("Could not load orders.")

    active_orders = [
        order for order in orders
        if order[9] in ("Preparing", "Ready")
    ]

    if not active_orders:
        st.info("No active orders.")

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
            st.write(f"**Payment method:** {payment_method}")
            st.write(f"**Payment status:** {payment_status}")

            try:
                for item in json.loads(items_json):
                    st.write(
                        f"- {item['name']} × {item['quantity']}"
                    )
            except (ValueError, TypeError, KeyError):
                st.write("Could not display order items.")

            if status == "Preparing":
                if st.button(
                    "Mark Ready",
                    key=f"ready_{order_id}",
                ):
                    change_status(order_id, "Ready")
                    st.rerun()

            if st.button(
                "Verify ID & token",
                key=f"verify_{order_id}",
            ):
                st.session_state[f"confirm_{order_id}"] = True

            if st.session_state.get(
                f"confirm_{order_id}", False
            ):
                st.warning(
                    "Physically check the college ID and pickup token "
                    "before handing over the order."
                )

                if st.button(
                    "Confirm collected",
                    key=f"collected_{order_id}",
                    type="primary",
                ):
                    change_status(order_id, "Collected")
                    st.session_state.pop(
                        f"confirm_{order_id}", None
                    )
                    st.rerun()

    st.divider()
    st.markdown("### Find an order")

    search_text = st.text_input(
        "Enter token, order ID, or college ID",
        key="find_order",
    )

    if search_text.strip():
        try:
            query = search_text.strip().lower()

            matches = [
                row for row in get_orders()
                if query in str(row[1]).lower()
                or query in str(row[2]).lower()
                or query in str(row[4]).lower()
            ]

            if matches:
                for row in matches:
                    st.write(
                        f"{row[1]} · {row[3]} · College ID {row[4]} · "
                        f"Token {row[2]} · Status {row[9]}"
                    )
            else:
                st.info("No matching order found.")

        except sqlite3.Error:
            st.error("Could not search orders.")


# ==================================================
# TAB 3: ADMIN
# ==================================================

with admin_tab:
    st.subheader("Admin dashboard")

    try:
        orders = get_orders()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total orders", len(orders))
        col2.metric(
            "Preparing",
            sum(row[9] == "Preparing" for row in orders),
        )
        col3.metric(
            "Ready",
            sum(row[9] == "Ready" for row in orders),
        )
        col4.metric(
            "Collected",
            sum(row[9] == "Collected" for row in orders),
        )

        st.markdown("### Order history")

        if orders:
            data = [{
                "Order ID": row[1],
                "Token": row[2],
                "Student": row[3],
                "College ID": row[4],
                "Items": row[5],
                "Total (₹)": row[6],
                "Payment method": row[7],
                "Payment status": row[8],
                "Status": row[9],
                "Created at": row[10],
            } for row in orders]

            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)

            st.download_button(
                "Download order history CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="campusbites_orders.csv",
                mime="text/csv",
            )
        else:
            st.info("No orders yet.")

        st.markdown("### Available menu")
        for item in get_menu():
            st.write(
                f"{item['name']} — ₹{item['price']:.2f} "
                f"({item['category']})"
            )

    except sqlite3.Error:
        st.error("Could not load the admin dashboard.")

    st.warning(
        "Demo app: Admin and Kitchen tabs have no login. "
        "Do not use this version for confidential data or real payments "
        "until access controls and payment verification are implemented."
    )
