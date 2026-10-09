
import json
import sqlite3
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path

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

# Use a fresh database to avoid old schema conflicts.
DB_PATH = Path(__file__).parent / "campusbites_v2.db"

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


def save_order(order):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO orders (
                order_id, token, student_name, college_id,
                items, total, payment_method, payment_status,
                status, created_at
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


def get_orders():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, order_id, token, student_name,
                   college_id, items, total, payment_method,
                   payment_status, status, created_at
            FROM orders
            ORDER BY id DESC
        """).fetchall()


def change_status(order_id, status):
    with get_connection() as conn:
        conn.execute("""
            UPDATE orders SET status = ?
            WHERE order_id = ?
        """, (status, order_id))


initialize_database()

# ==================================================
# SESSION STATE
# ==================================================

if "cart_version" not in st.session_state:
    st.session_state.cart_version = 0

if "last_order" not in st.session_state:
    st.session_state.last_order = None

if "notice" not in st.session_state:
    st.session_state.notice = None

# ==================================================
# ORDER AND QR HELPERS
# ==================================================

def make_order(student_name, college_id, payment_method, cart):
    total = sum(
        item["price"] * item["quantity"]
        for item in cart
    )

    return {
        "order_id": "CB-" + uuid.uuid4().hex[:8].upper(),
        "token": uuid.uuid4().hex[:6].upper(),
        "student_name": student_name.strip(),
        "college_id": college_id.strip(),
        "items": cart,
        "total": round(total, 2),
        "payment_method": payment_method,
        "payment_status": "Pay at counter",
        "status": "Preparing",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def make_qr(order):
    qr_data = {
        "order_id": order["order_id"],
        "pickup_token": order["token"],
        "student_name": order["student_name"],
        "college_id": order["college_id"],
        "items": order["items"],
        "total_inr": order["total"],
        "payment_method": order["payment_method"],
        "payment_status": order["payment_status"],
        "note": (
            "Order receipt only. Not a payment QR. "
            "Pay at the canteen counter. Verify physical college ID."
        ),
    }

    qr = qrcode.QRCode(
        version=1,
        box_size=8,
        border=3,
    )
    qr.add_data(json.dumps(qr_data, ensure_ascii=False))
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ==================================================
# STYLING
# ==================================================

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}
.food-title {
    font-size: 1.05rem;
    font-weight: 650;
}
.muted {
    color: #777;
    font-size: 0.9rem;
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
    st.subheader("Place your order")
    st.write("Select your food and enter your college details.")

    menu = get_menu()

    if not menu:
        st.warning("No menu items are available.")
    else:
        version = st.session_state.cart_version

        # All widgets are inside one form.
        # The cart is submitted together with the form.
        with st.form(key=f"order_form_{version}"):
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
                            key=f"qty_{version}_{item['id']}",
                        )

                        if quantity > 0:
                            cart.append({
                                "id": item["id"],
                                "name": item["name"],
                                "price": item["price"],
                                "quantity": int(quantity),
                            })

            st.markdown("---")
            st.markdown("### 🎓 Student details")

            student_name = st.text_input(
                "Student name",
                key=f"name_{version}",
            )

            college_id = st.text_input(
                "College ID",
                key=f"college_{version}",
            )

            payment_method = st.selectbox(
                "Payment option",
                [
                    "UPI at counter",
                    "Card at counter",
                    "Cash at counter",
                ],
                key=f"payment_{version}",
            )

            total = sum(
                item["price"] * item["quantity"]
                for item in cart
            )

            st.markdown(f"### Total: ₹{total:.2f}")

            submitted = st.form_submit_button(
                "Place Order",
                type="primary",
                use_container_width=True,
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
                    order = make_order(
                        student_name,
                        college_id,
                        payment_method,
                        cart,
                    )
                    save_order(order)

                    st.session_state.last_order = order
                    st.session_state.cart_version += 1
                    st.session_state.notice = (
                        "Order placed! Your pickup token is "
                        + order["token"]
                    )

                    # Fresh widget keys will be used on the next run.
                    st.rerun()

                except sqlite3.Error:
                    st.error(
                        "The order could not be saved to the database. "
                        "Please try again."
                    )

    # Display latest receipt
    order = st.session_state.last_order

    if order:
        st.markdown("---")
        st.subheader("✅ Order receipt")

        st.write(f"**Order ID:** {order['order_id']}")
        st.write(f"**Pickup token:** `{order['token']}`")
        st.write(f"**Student:** {order['student_name']}")
        st.write(f"**College ID:** {order['college_id']}")
        st.write(f"**Status:** {order['status']}")

        st.markdown("#### Items")
        for item in order["items"]:
            line_total = item["price"] * item["quantity"]
            st.write(
                f"- {item['name']} × {item['quantity']} "
                f"— ₹{line_total:.2f}"
            )

        st.markdown(f"### Total: ₹{order['total']:.2f}")
        st.write(f"**Payment option:** {order['payment_method']}")

        st.info(
            "This is an order QR, not a payment QR. "
            "Pay at the canteen counter. Staff must verify "
            "your physical college ID and pickup token."
        )

        qr_bytes = make_qr(order)
        st.image(qr_bytes, width=250)

        st.download_button(
            "Download Order QR",
            data=qr_bytes,
            file_name=f"{order['order_id']}_qr.png",
            mime="image/png",
        )

        receipt = (
            f"CampusBites - RVRJC\n"
            f"Order ID: {order['order_id']}\n"
            f"Pickup token: {order['token']}\n"
            f"Student: {order['student_name']}\n"
            f"College ID: {order['college_id']}\n"
            + "".join(
                f"{item['name']} x {item['quantity']} = "
                f"₹{item['price'] * item['quantity']:.2f}\n"
                for item in order["items"]
            )
            + f"Total: ₹{order['total']:.2f}\n"
            + f"Payment option: {order['payment_method']}\n"
            + "Pay at the canteen counter.\n"
        )

        st.download_button(
            "Download Text Receipt",
            data=receipt,
            file_name=f"{order['order_id']}_receipt.txt",
            mime="text/plain",
        )

# ==================================================
# TAB 2: KITCHEN AND PICKUP
# ==================================================

with kitchen_tab:
    st.subheader("Kitchen queue & pickup")
    st.caption(
        "Verify the student's physical college ID and pickup token "
        "before handing over food."
    )

    if st.button("Refresh Orders"):
        st.rerun()

    try:
        orders = get_orders()
    except sqlite3.Error:
        orders = []
        st.error("Could not load orders from the database.")

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
                    for item in json.loads(items_json):
                        st.write(
                            f"- {item['name']} × {item['quantity']}"
                        )
                except (ValueError, TypeError, KeyError):
                    st.write("Could not display the saved item details.")

                if status == "Preparing":
                    if st.button(
                        "Mark Ready",
                        key=f"ready_{order_id}",
                    ):
                        change_status(order_id, "Ready")
                        st.rerun()

                if st.button(
                    "Confirm ID & Token — Collected",
                    key=f"collect_{order_id}",
                ):
                    st.session_state[f"verify_{order_id}"] = True

                if st.session_state.get(f"verify_{order_id}", False):
                    st.warning(
                        "Check the physical college ID and pickup token "
                        "before confirming collection."
                    )

                    if st.button(
                        "Confirm collection",
                        key=f"confirm_{order_id}",
                        type="primary",
                    ):
                        change_status(order_id, "Collected")
                        st.session_state.pop(
                            f"verify_{order_id}", None
                        )
                        st.rerun()

    st.markdown("---")
    st.markdown("### Find an order")

    search_value = st.text_input(
        "Enter pickup token, order ID, or college ID",
        key="search_order",
    )

    if search_value.strip():
        try:
            all_orders = get_orders()
            query = search_value.strip().lower()

            matches = [
                order for order in all_orders
                if query in str(order[1]).lower()
                or query in str(order[2]).lower()
                or query in str(order[4]).lower()
            ]

            if matches:
                for order in matches:
                    st.write(
                        f"**{order[1]}** · {order[3]} · "
                        f"College ID: {order[4]} · "
                        f"Token: {order[2]} · Status: {order[9]}"
                    )
            else:
                st.info("No matching order found.")

        except sqlite3.Error:
            st.error("Could not search the order database.")

# ==================================================
# TAB 3: ADMIN DASHBOARD
# ==================================================

with admin_tab:
    st.subheader("Admin dashboard")

    try:
        orders = get_orders()

        total_count = len(orders)
        preparing_count = sum(o[9] == "Preparing" for o in orders)
        ready_count = sum(o[9] == "Ready" for o in orders)
        collected_count = sum(o[9] == "Collected" for o in orders)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Orders", total_count)
        col2.metric("Preparing", preparing_count)
        col3.metric("Ready", ready_count)
        col4.metric("Collected", collected_count)

        st.markdown("### Order history")

        if orders:
            import pandas as pd

            data = []
            for order in orders:
                data.append({
                    "Order ID": order[1],
                    "Pickup Token": order[2],
                    "Student": order[3],
                    "College ID": order[4],
                    "Items": order[5],
                    "Total (₹)": order[6],
                    "Payment Option": order[7],
                    "Payment Status": order[8],
                    "Status": order[9],
                    "Created At": order[10],
                })

            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)

            st.download_button(
                "Download Order History CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="campusbites_orders.csv",
                mime="text/csv",
            )
        else:
            st.info("No orders have been placed yet.")

        st.markdown("### Available menu")
        for item in get_menu():
            st.write(
                f"**{item['name']}** — ₹{item['price']:.2f} "
                f"({item['category']})"
            )

    except sqlite3.Error:
        st.error("Could not load the admin dashboard.")

    st.warning(
        "Demo only: Kitchen and Admin are not password-protected. "
        "Do not use this version for confidential data or real payments."
    )
