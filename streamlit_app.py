
import streamlit as st
import sqlite3
import qrcode
import pandas as pd
import json
import uuid
from io import BytesIO
from pathlib import Path
from datetime import datetime

# ==========================================================
# CAMPUSBITES - RVR & JC COLLEGE OF ENGINEERING
# Demo ordering, pickup QR, kitchen queue and admin
# ==========================================================

st.set_page_config(
    page_title="CampusBites | RVRJC",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_PATH = Path(__file__).parent / "campusbites.db"

DEFAULT_MENU = [
    ("Hot Crispy Dosa", 35, "Breakfast"),
    ("Steaming Soft Idli (Plate)", 30, "Breakfast"),
    ("Special Filter Coffee", 15, "Drinks"),
    ("Chai / Tea", 12, "Drinks"),
    ("Crispy Samosa (Plate)", 30, "Snacks"),
]

PAYMENT_METHODS = [
    "UPI at counter",
    "Card at counter",
    "Cash at counter",
]

# ---------------- DATABASE ----------------

def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                category TEXT DEFAULT 'Food',
                active INTEGER DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                token INTEGER,
                student_name TEXT NOT NULL,
                student_id TEXT NOT NULL,
                items TEXT NOT NULL,
                total REAL NOT NULL,
                gateway_fee REAL DEFAULT 0,
                net_amount REAL DEFAULT 0,
                status TEXT DEFAULT 'Preparing',
                payment_status TEXT DEFAULT 'Pay at counter',
                created_at TEXT,
                razorpay_link_id TEXT,
                payment_id TEXT,
                payment_method TEXT DEFAULT 'UPI at counter'
            )
        """)

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(orders)"
            ).fetchall()
        }

        migrations = {
            "token": "INTEGER",
            "gateway_fee": "REAL DEFAULT 0",
            "net_amount": "REAL DEFAULT 0",
            "razorpay_link_id": "TEXT",
            "payment_id": "TEXT",
            "payment_method": "TEXT DEFAULT 'UPI at counter'",
        }

        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(
                    f"ALTER TABLE orders ADD COLUMN {column} {definition}"
                )

        menu_count = conn.execute(
            "SELECT COUNT(*) FROM menu"
        ).fetchone()[0]

        if menu_count == 0:
            conn.executemany(
                """INSERT INTO menu (name, price, category, active)
                   VALUES (?, ?, ?, 1)""",
                DEFAULT_MENU
            )


initialize_db()

# ---------------- HELPERS ----------------

def money(amount):
    return f"₹{float(amount):.2f}"


def get_menu():
    with connect_db() as conn:
        return conn.execute("""
            SELECT * FROM menu
            WHERE active = 1
            ORDER BY category, name
        """).fetchall()


def get_orders():
    with connect_db() as conn:
        return conn.execute("""
            SELECT * FROM orders
            ORDER BY created_at DESC
        """).fetchall()


def get_order(order_id):
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE order_id = ?",
            (order_id,)
        ).fetchone()


def normalize_id(value):
    return str(value or "").strip().upper()


def get_items_text(order):
    try:
        items = json.loads(order["items"])
        return ", ".join(
            f'{item["name"]} x {item["quantity"]}'
            for item in items
        )
    except (ValueError, TypeError, KeyError):
        return str(order["items"])


def create_order(name, college_id, basket, payment_method):
    subtotal = sum(
        float(item["price"]) * int(item["quantity"])
        for item in basket
    )

    # Demo service fee, not a payment gateway fee.
    fee = 1.00
    total = subtotal + fee
    order_id = "CB-" + uuid.uuid4().hex[:8].upper()

    with connect_db() as conn:
        last_token = conn.execute(
            "SELECT COALESCE(MAX(token), 100) FROM orders"
        ).fetchone()[0]

        token = int(last_token or 100) + 1

        conn.execute("""
            INSERT INTO orders (
                order_id, token, student_name, student_id, items,
                total, gateway_fee, net_amount, status,
                payment_status, created_at, payment_method
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            token,
            name.strip(),
            normalize_id(college_id),
            json.dumps(basket),
            total,
            fee,
            subtotal,
            "Preparing",
            "Pay at counter",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            payment_method
        ))

    return order_id


def make_pickup_qr(order):
    """QR shows order information. It does not transfer money."""
    items = json.loads(order["items"])

    item_lines = [
        f'{item["name"]} x {item["quantity"]}'
        for item in items
    ]

    qr_text = "\n".join([
        "CAMPUSBITES - PICKUP RECEIPT",
        f'Order ID: {order["order_id"]}',
        f'Pickup Token: {order["token"]}',
        f'Name: {order["student_name"]}',
        f'College ID: {order["student_id"]}',
        "Items:",
        *item_lines,
        f'AMOUNT: INR {float(order["total"]):.2f}',
        f'Payment choice: {order["payment_method"]}',
        f'Status: {order["status"]}',
        "Pay at canteen counter.",
        "Staff must check the physical college ID."
    ])

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=7,
        border=3
    )
    qr.add_data(qr_text)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white"
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def set_status(order_id, status):
    with connect_db() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?",
            (status, order_id)
        )


# ---------------- DESIGN ----------------

st.markdown("""
<style>
    .block-container {
        padding-top: 0.6rem;
        padding-bottom: 1rem;
        max-width: 1300px;
    }
    h1, h2, h3 {
        letter-spacing: -0.4px;
        margin-bottom: 0.4rem;
    }
    div.stButton > button {
        width: 100%;
        min-height: 38px;
        border-radius: 9px;
        font-weight: 600;
    }
    div[data-testid="stMetric"] {
        border: 1px solid rgba(128,128,128,0.25);
        padding: 10px;
        border-radius: 10px;
    }
    div[data-testid="stTabs"] button {
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

st.title("🍽️ CampusBites")
st.caption("RVR & JC College of Engineering · Smart Canteen")

st.info(
    "Order food → collect your QR/token → show your physical college ID "
    "to staff. Payment is handled separately at the counter."
)

tab_order, tab_kitchen, tab_admin = st.tabs([
    "🛒 Order Food",
    "👨‍🍳 Kitchen & Pickup",
    "📊 Admin"
])

# ==========================================================
# 1. STUDENT ORDER
# ==========================================================

with tab_order:
    st.subheader("Today's menu")

    menu_rows = get_menu()

    left, right = st.columns([1.15, 0.85], gap="small")

    with left:
        if not menu_rows:
            st.warning("No food items available.")
        else:
            # Two menu cards per row to reduce scrolling.
            for start in range(0, len(menu_rows), 2):
                cols = st.columns(2, gap="small")

                for col, item in zip(
                    cols, menu_rows[start:start + 2]
                ):
                    with col:
                        with st.container(border=True):
                            st.markdown(f'**{item["name"]}**')
                            st.caption(item["category"])
                            st.write(money(item["price"]))

                            quantity_key = f'qty_{item["id"]}'

                            if quantity_key not in st.session_state:
                                st.session_state[quantity_key] = 0

                            st.number_input(
                                "Quantity",
                                min_value=0,
                                max_value=20,
                                step=1,
                                key=quantity_key
                            )

    with right:
        st.subheader("Your basket")

        basket = []

        for item in menu_rows:
            quantity = int(
                st.session_state.get(f'qty_{item["id"]}', 0)
            )

            if quantity > 0:
                basket.append({
                    "name": item["name"],
                    "price": float(item["price"]),
                    "quantity": quantity
                })

        subtotal = sum(
            item["price"] * item["quantity"]
            for item in basket
        )
        fee = 1.00 if basket else 0.00
        total = subtotal + fee

        if basket:
            for item in basket:
                st.write(
                    f'{item["name"]} × {item["quantity"]} — '
                    f'{money(item["price"] * item["quantity"])}'
                )
        else:
            st.caption("Choose food from the menu.")

        st.divider()
        st.write(f"Food subtotal: **{money(subtotal)}**")
        st.write(f"Service fee: **{money(fee)}**")
        st.markdown(f"### Total: {money(total)}")

        st.subheader("Student details")

        student_name = st.text_input(
            "Student name",
            key="student_name",
            placeholder="Enter your name"
        )

        student_id = st.text_input(
            "College ID",
            key="student_id",
            placeholder="Enter your college ID"
        )

        payment_method = st.selectbox(
            "Payment method",
            PAYMENT_METHODS
        )

        st.caption(
            "These are payment preferences only. UPI and card payments "
            "are not processed by this demo."
        )

        if st.button("Place Order", type="primary"):
            if not basket:
                st.error("Please select at least one food item.")
            elif not student_name.strip():
                st.error("Enter your name.")
            elif not student_id.strip():
                st.error("Enter your college ID.")
            else:
                new_id = create_order(
                    student_name,
                    student_id,
                    basket,
                    payment_method
                )

                st.session_state["last_order_id"] = new_id

                # Clear the basket quantities after successful order creation.
                for item in menu_rows:
                    st.session_state[f'qty_{item["id"]}'] = 0

                st.rerun()

        # Show the last receipt.
        last_id = st.session_state.get("last_order_id")

        if last_id:
            order = get_order(last_id)

            if order:
                st.divider()
                st.subheader("Your pickup receipt")

                st.success(f'Pickup token: {order["token"]}')
                st.write(f'**Student:** {order["student_name"]}')
                st.write(f'**College ID:** {order["student_id"]}')
                st.write(f'**Order:** {order["order_id"]}')
                st.write(f'**Food:** {get_items_text(order)}')
                st.write(f'**Amount:** {money(order["total"])}')
                st.write(f'**Status:** {order["status"]}')
                st.write(f'**Payment choice:** {order["payment_method"]}')

                qr_image = make_pickup_qr(order)

                st.image(
                    qr_image,
                    width=210,
                    caption="Scan for order details and amount"
                )

                st.download_button(
                    "Download pickup QR",
                    data=qr_image,
                    file_name=f'{order["order_id"]}_QR.png',
                    mime="image/png"
                )

                receipt = "\n".join([
                    "CAMPUSBITES - PICKUP RECEIPT",
                    f'Order: {order["order_id"]}',
                    f'Token: {order["token"]}',
                    f'Name: {order["student_name"]}',
                    f'College ID: {order["student_id"]}',
                    f'Food: {get_items_text(order)}',
                    f'Amount: {money(order["total"])}',
                    f'Payment choice: {order["payment_method"]}',
                    f'Status: {order["status"]}',
                    "Pay at counter. Show physical college ID."
                ])

                st.download_button(
                    "Download receipt to print",
                    data=receipt,
                    file_name=f'{order["order_id"]}_receipt.txt',
                    mime="text/plain"
                )

                if order["status"] == "Collected":
                    st.success("Previous order collected. You can order again.")

                if st.button("New Order", key="new_order"):
                    st.session_state.pop("last_order_id", None)
                    st.session_state["student_name"] = ""
                    st.session_state["student_id"] = ""
                    for item in menu_rows:
                        st.session_state[f'qty_{item["id"]}'] = 0
                    st.rerun()

# ==========================================================
# 2. KITCHEN AND PICKUP - NO PIN
# ==========================================================

with tab_kitchen:
    st.subheader("Kitchen & pickup")
    st.caption(
        "Staff: prepare the order, mark it Ready, then check the student's "
        "physical college ID and pickup token before handing over food."
    )

    orders = get_orders()

    active_orders = [
        order for order in orders
        if order["status"] in ("Preparing", "Ready")
    ]

    if not active_orders:
        st.info("No active orders.")
    else:
        for order in active_orders:
            with st.container(border=True):
                st.markdown(
                    f'### Token {order["token"]} · {order["student_name"]}'
                )
                st.write(f'**College ID:** {order["student_id"]}')
                st.write(f'**Order ID:** {order["order_id"]}')
                st.write(f'**Food:** {get_items_text(order)}')
                st.write(f'**Amount:** {money(order["total"])}')
                st.write(f'**Payment choice:** {order["payment_method"]}')
                st.write(f'**Status:** {order["status"]}')

                if order["status"] == "Preparing":
                    if st.button(
                        "Mark Ready",
                        key=f'ready_{order["order_id"]}',
                        type="primary"
                    ):
                        set_status(order["order_id"], "Ready")
                        st.rerun()

                elif order["status"] == "Ready":
                    st.success("Ready for pickup")

                    st.caption(
                        "Check the physical college ID and printed token. "
                        "Collect payment at the counter before handing over food."
                    )

                    if st.button(
                        "Confirm ID & Token — Collected",
                        key=f'collected_{order["order_id"]}'
                    ):
                        set_status(order["order_id"], "Collected")
                        st.rerun()

    st.divider()
    st.subheader("Find order by token or college ID")

    search_value = st.text_input(
        "Enter pickup token or college ID",
        placeholder="Example: 101 or Y25EC006",
        key="staff_search"
    )

    if search_value.strip():
        search = search_value.strip()
        matches = [
            order for order in orders
            if str(order["token"]) == search
            or normalize_id(order["student_id"]) == normalize_id(search)
        ]

        if matches:
            for order in matches:
                st.write(
                    f'**Token {order["token"]}** — '
                    f'{order["student_name"]} — '
                    f'{order["student_id"]} — '
                    f'{order["status"]}'
                )
        else:
            st.warning("No matching order found.")

# ==========================================================
# 3. ADMIN AND ORDER HISTORY
# ==========================================================

with tab_admin:
    st.subheader("Admin dashboard")

    orders = get_orders()

    total_orders = len(orders)
    preparing_count = sum(
        1 for order in orders if order["status"] == "Preparing"
    )
    ready_count = sum(
        1 for order in orders if order["status"] == "Ready"
    )
    collected_count = sum(
        1 for order in orders if order["status"] == "Collected"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total orders", total_orders)
    c2.metric("Preparing", preparing_count)
    c3.metric("Ready", ready_count)
    c4.metric("Collected", collected_count)

    st.caption(
        "No PIN is required in this demonstration. Do not expose this "
        "version publicly with real student or business data."
    )

    st.subheader("Order history")

    if orders:
        rows = []

        for order in orders:
            rows.append({
                "Order ID": order["order_id"],
                "Token": order["token"],
                "Student": order["student_name"],
                "College ID": order["student_id"],
                "Items": get_items_text(order),
                "Amount": float(order["total"]),
                "Payment method": order["payment_method"],
                "Payment status": order["payment_status"],
                "Status": order["status"],
                "Created": order["created_at"],
            })

        df = pd.DataFrame(rows)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "Download order history CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="campusbites_orders.csv",
            mime="text/csv"
        )
    else:
        st.info("No orders have been placed yet.")

    st.subheader("Menu")

    with connect_db() as conn:
        menu_df = pd.read_sql_query(
            "SELECT id, name, price, category, active FROM menu",
            conn
        )

    st.dataframe(
        menu_df,
        use_container_width=True,
        hide_index=True
    )

    st.caption(
        "The menu can be edited in the SQLite database. "
        "This app does not include an in-app menu editor."
    )

    st.divider()
    st.subheader("Reset demo order history")

    confirm_reset = st.checkbox(
        "I understand this deletes all orders from the local database."
    )

    if st.button("Reset All Orders"):
        if confirm_reset:
            with connect_db() as conn:
                conn.execute("DELETE FROM orders")

            st.session_state.pop("last_order_id", None)
            st.success("Order history cleared.")
            st.rerun()
        else:
            st.error("Confirm before resetting.")

# ---------------- FOOTER ----------------

st.divider()
st.caption(
    "CampusBites · RVR & JC College of Engineering · "
    "Prototype only · Payment collected separately at counter"
)
