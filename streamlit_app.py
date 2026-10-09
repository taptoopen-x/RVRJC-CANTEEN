import sqlite3
import uuid
import datetime
from pathlib import Path
from io import BytesIO

import pandas as pd
import qrcode
import streamlit as st

# ============================================================
# CAMPUSBITES — DEMO QR + PAYMENT METHODS
# No Razorpay account or payment credentials required.
# All payments in this version are simulations only.
# ============================================================

st.set_page_config(
    page_title="CampusBites Zero-Touch Canteen",
    page_icon="🍱",
    layout="wide",
)

DB = str(Path(__file__).parent / "campusbites.db")

# Demo staff PIN. For a college presentation only.
# You can set app.staff_pin in Streamlit Secrets to change it.
try:
    STAFF_PIN = str(st.secrets["app"]["staff_pin"])
except Exception:
    STAFF_PIN = "1234"


# ========================== DATABASE ==========================

def db():
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                price REAL NOT NULL,
                category TEXT NOT NULL,
                stock INTEGER NOT NULL DEFAULT 100,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE,
                token INTEGER UNIQUE,
                student_name TEXT DEFAULT '',
                student_id TEXT DEFAULT '',
                items TEXT NOT NULL,
                total REAL NOT NULL,
                gateway_fee REAL NOT NULL DEFAULT 0,
                net_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                razorpay_link_id TEXT DEFAULT '',
                payment_id TEXT DEFAULT '',
                payment_method TEXT DEFAULT 'Scan QR (Demo)'
            )
        """)

        # Add missing columns to existing databases without
        # deleting existing orders.
        existing = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(orders)"
            ).fetchall()
        }

        migrations = {
            "student_name": "TEXT DEFAULT ''",
            "student_id": "TEXT DEFAULT ''",
            "razorpay_link_id": "TEXT DEFAULT ''",
            "payment_id": "TEXT DEFAULT ''",
            "payment_method": "TEXT DEFAULT 'Scan QR (Demo)'",
        }

        for column, definition in migrations.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE orders ADD COLUMN {column} {definition}"
                )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        menu_items = [
            ("Hot Crispy Dosa", 35, "Breakfast", 100),
            ("Steaming Soft Idli (Plate)", 30, "Breakfast", 100),
            ("Special Filter Coffee", 15, "Beverage", 100),
            ("Chai / Tea", 12, "Beverage", 100),
            ("Crispy Samosa (Plate)", 30, "Snack", 100),
        ]

        for item in menu_items:
            conn.execute("""
                INSERT OR IGNORE INTO menu(name, price, category, stock)
                VALUES (?, ?, ?, ?)
            """, item)

        conn.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            VALUES('token_counter', '100')
        """)


def get_menu():
    with db() as conn:
        return conn.execute("""
            SELECT * FROM menu
            WHERE active=1
            ORDER BY category, name
        """).fetchall()


def get_orders():
    with db() as conn:
        return conn.execute(
            "SELECT * FROM orders ORDER BY id DESC"
        ).fetchall()


def get_order(order_id):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE order_id=?",
            (order_id,),
        ).fetchone()


def allocate_order(student_name, student_id, cart, total):
    """Create an order with a unique ID and pickup token."""

    if not cart:
        raise ValueError("Your basket is empty.")

    items_text = ", ".join(
        f"{item['name']} x{item['qty']}" for item in cart
    )

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT value FROM settings WHERE key='token_counter'"
        ).fetchone()

        token = int(row["value"]) + 1

        conn.execute(
            "UPDATE settings SET value=? WHERE key='token_counter'",
            (str(token),),
        )

        order_id = (
            f"CB{datetime.datetime.now().strftime('%Y%m%d')}-"
            f"{uuid.uuid4().hex[:8].upper()}"
        )

        conn.execute("""
            INSERT INTO orders(
                order_id, token, student_name, student_id,
                items, total, gateway_fee, net_amount,
                status, payment_status, created_at, payment_method
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            token,
            student_name,
            student_id,
            items_text,
            total,
            0.00,
            total,
            "Awaiting Payment",
            "Pending",
            now,
            "Scan QR (Demo)",
        ))

    return order_id, token


# ======================= DEMO PAYMENT ========================

def make_qr(text):
    """Generate a QR image from the supplied text."""

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=7,
        border=3,
    )
    qr.add_data(text)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer


def demo_qr_text(order):
    """
    QR contains order information only.
    It is NOT a UPI QR and cannot transfer money.
    """

    return (
        "CAMPUSBITES - DEMO ONLY\n"
        "NOT A REAL PAYMENT QR\n"
        f"Order ID: {order['order_id']}\n"
        f"Pickup Token: {order['token']}\n"
        f"Student: {order['student_name']}\n"
        f"Amount: INR {float(order['total']):.2f}\n"
        "No money transferred."
    )


def mark_demo_payment(order_id):
    """
    Record a simulated payment.
    This does not collect or verify real money.
    """

    demo_payment_id = "DEMO-" + uuid.uuid4().hex[:10].upper()

    with db() as conn:
        result = conn.execute("""
            UPDATE orders
            SET payment_status='Demo Paid',
                payment_id=?,
                status='Preparing'
            WHERE order_id=?
              AND payment_status='Pending'
              AND status='Awaiting Payment'
        """, (demo_payment_id, order_id))

    return result.rowcount == 1


# ========================== UTILITIES ========================

def staff_allowed(pin):
    if pin != STAFF_PIN:
        st.error("Enter the correct staff PIN to continue.")
        return False

    return True


def reset_demo():
    with db() as conn:
        conn.execute("DELETE FROM orders")
        conn.execute("""
            UPDATE settings SET value='100'
            WHERE key='token_counter'
        """)


def order_is_demo_paid(order):
    return order["payment_status"] == "Demo Paid"


# Initialize database and session state.
init_db()

if "cart" not in st.session_state:
    st.session_state.cart = []

if "last_order_id" not in st.session_state:
    st.session_state.last_order_id = None


# =========================== DESIGN ==========================

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
}
.hero {
    background: linear-gradient(120deg, #173d31, #2c8061);
    padding: 1.5rem;
    border-radius: 18px;
    color: white;
    margin-bottom: 1rem;
}
.hero h1 {
    color: white;
    margin: 0;
}
.hero p {
    color: #e5f5ec;
    margin-top: .4rem;
}
.demo-banner {
    background: #fff3cd;
    border: 1px solid #e7c766;
    color: #664d03;
    border-radius: 10px;
    padding: 12px 16px;
    margin-bottom: 16px;
}
</style>

<div class="hero">
    <h1>🍱 CampusBites — Zero-Touch Canteen</h1>
    <p>Student ordering · Demo QR · Payment choices · Unique pickup tokens</p>
</div>

<div class="demo-banner">
    <b>DEMO MODE ONLY</b> — Payments are simulated.
    No money is collected or transferred.
</div>
""", unsafe_allow_html=True)


orders_now = get_orders()

st.sidebar.header("🟢 System Status")
st.sidebar.success("App online")
st.sidebar.metric("Total orders", len(orders_now))
st.sidebar.warning(
    "Demo version: QR and payment options are simulations. "
    "Do not enter real payment details."
)
st.sidebar.caption(
    "Demo staff PIN: 1234, unless changed in Streamlit Secrets."
)


# ============================ TABS ===========================

student_tab, kitchen_tab, pickup_tab, admin_tab = st.tabs([
    "📱 Student App",
    "🖨️ Kitchen",
    "🎟️ Pickup Verification",
    "⚙️ Admin & Stress Test",
])


# ======================== STUDENT APP ========================

with student_tab:
    st.subheader("📍 Today's Menu")

    menu = get_menu()

    if not menu:
        st.info("No menu items are currently available.")

    for item in menu:
        left, price_col, add_col = st.columns([4, 1, 1])

        left.markdown(f"**{item['name']}**")
        left.caption(
            f"{item['category']} · Available stock: {item['stock']}"
        )
        price_col.markdown(f"### ₹{item['price']:.0f}")

        if add_col.button("Add", key=f"add_{item['id']}"):
            existing = next(
                (
                    x for x in st.session_state.cart
                    if x["name"] == item["name"]
                ),
                None,
            )

            if existing:
                existing["qty"] += 1
            else:
                st.session_state.cart.append({
                    "name": item["name"],
                    "price": float(item["price"]),
                    "qty": 1,
                })

            st.rerun()

    st.divider()
    st.subheader("🛒 Your Basket")

    if not st.session_state.cart:
        st.info("Your basket is empty.")

    else:
        new_cart = []

        for i, item in enumerate(st.session_state.cart):
            a, b, c, d = st.columns([5, 1, 1, 1])

            a.write(f"**{item['name']}**")
            b.write(f"₹{item['price']:.0f}")
            c.write(f"× {item['qty']}")

            if d.button("−", key=f"minus_{i}"):
                item["qty"] -= 1

            if item["qty"] > 0:
                new_cart.append(item)

        st.session_state.cart = new_cart

        if st.session_state.cart:
            food_total = sum(
                item["price"] * item["qty"]
                for item in st.session_state.cart
            )

            handling_fee = 1.00
            total = round(food_total + handling_fee, 2)

            st.write(f"Food total: ₹{food_total:.2f}")
            st.write(f"Handling fee: ₹{handling_fee:.2f}")
            st.markdown(f"## Final amount: ₹{total:.2f}")

            st.divider()
            st.subheader("🧾 Student Details")

            with st.form("checkout_form"):
                student_name = st.text_input(
                    "Student full name",
                    max_chars=80,
                )

                student_id = st.text_input(
                    "College ID",
                    placeholder="Enter your college ID",
                    max_chars=40,
                )

                st.divider()
                st.subheader("💳 Choose a Payment Method")

                selected_payment_method = st.radio(
                    "Payment options (demonstration only)",
                    [
                        "Scan QR (Demo)",
                        "UPI ID / UPI App (Demo)",
                        "Debit Card (Demo)",
                        "Credit Card (Demo)",
                    ],
                )

                st.caption(
                    "Demo only. Do not enter real UPI IDs, PINs, "
                    "or card details. No money will be transferred."
                )

                checkout = st.form_submit_button(
                    "Create Demo Order",
                    type="primary",
                    use_container_width=True,
                )

            if checkout:
                if not student_name.strip() or not student_id.strip():
                    st.error("Enter both your name and college ID.")

                else:
                    try:
                        order_id, token = allocate_order(
                            student_name.strip(),
                            student_id.strip(),
                            st.session_state.cart,
                            total,
                        )

                        with db() as conn:
                            conn.execute("""
                                UPDATE orders
                                SET payment_method=?
                                WHERE order_id=?
                            """, (selected_payment_method, order_id))

                        st.session_state.last_order_id = order_id
                        st.session_state.cart = []

                        st.rerun()

                    except Exception as exc:
                        st.error("Could not create the demo order.")
                        st.exception(exc)

            if st.button("🗑️ Empty Basket"):
                st.session_state.cart = []
                st.rerun()

    # Display the latest order.
    last_id = st.session_state.get("last_order_id")

    if last_id:
        order = get_order(last_id)

        if order:
            st.divider()
            st.subheader("📦 Your Order")

            col1, col2 = st.columns(2)

            col1.metric("Pickup Token", f"#{order['token']}")
            col2.metric("Total Amount", f"₹{order['total']:.2f}")

            st.write("**Order ID:**", order["order_id"])
            st.write("**Student:**", order["student_name"])
            st.write("**College ID:**", order["student_id"])
            st.write("**Items:**", order["items"])
            st.write("**Payment method:**", order["payment_method"])
            st.write("**Payment status:**", order["payment_status"])
            st.write("**Kitchen status:**", order["status"])

            if order["payment_status"] == "Pending":
                st.warning(
                    "DEMO ONLY — this is not a real payment. "
                    "No money will be transferred."
                )

                if order["payment_method"] == "Scan QR (Demo)":
                    st.markdown("#### 📱 Scan this Demo QR")

                    st.image(
                        make_qr(demo_qr_text(order)),
                        width=240,
                        caption="DEMO QR — order details only, not a payment QR",
                    )

                    st.caption(
                        "Scanning this QR displays order information. "
                        "It does not open a UPI app or collect money."
                    )

                elif order["payment_method"] == "UPI ID / UPI App (Demo)":
                    st.info(
                        "UPI option selected. In a real integration, "
                        "this step would connect to a payment provider."
                    )

                elif order["payment_method"] == "Debit Card (Demo)":
                    st.info(
                        "Debit card option selected. Real card details "
                        "are not requested in this demo."
                    )

                elif order["payment_method"] == "Credit Card (Demo)":
                    st.info(
                        "Credit card option selected. Real card details "
                        "are not requested in this demo."
                    )

                if st.button(
                    "✓ Simulate Successful Payment (Demo)",
                    key=f"demo_pay_{order['order_id']}",
                    type="primary",
                    use_container_width=True,
                ):
                    if mark_demo_payment(order["order_id"]):
                        st.success(
                            "Demo payment recorded. No money was transferred."
                        )
                        st.rerun()
                    else:
                        st.warning(
                            "This order has already been processed or its "
                            "status has changed. Refresh and check the order."
                        )

            elif order["payment_status"] == "Demo Paid":
                st.warning(
                    "DEMO PAYMENT COMPLETE — no real money was transferred."
                )
                st.success(
                    "Your order has entered the demo kitchen workflow. "
                    "Keep your order ID and pickup token."
                )

            elif order["payment_status"] == "Paid":
                st.success(
                    "This order is marked Paid in the saved database. "
                    "Check the payment record before handing over food."
                )

            else:
                st.info(
                    f"Current payment status: {order['payment_status']}"
                )


# =========================== KITCHEN =========================

with kitchen_tab:
    st.subheader("🖨️ Kitchen Queue")

    pin = st.text_input(
        "Staff PIN",
        type="password",
        key="kitchen_pin",
    )

    if staff_allowed(pin):
        orders = get_orders()

        active = [
            order for order in orders
            if order["payment_status"] in ("Paid", "Demo Paid")
            and order["status"] not in ("Collected", "Completed")
        ]

        if not active:
            st.info("No paid or demo-paid orders waiting in the kitchen.")

        for order in active:
            with st.container(border=True):
                a, b, c = st.columns([3, 2, 2])

                a.markdown(f"### 🎫 Token #{order['token']}")
                a.write(order["order_id"])
                a.write(order["student_name"])
                a.caption(f"College ID: {order['student_id']}")

                b.write(order["items"])
                b.write(f"₹{order['total']:.2f}")

                if order["payment_status"] == "Demo Paid":
                    b.warning("DEMO PAYMENT — no money transferred")
                else:
                    b.success("Payment: Paid")

                c.write(f"**Status: {order['status']}**")

                if order["status"] == "Preparing":
                    if c.button(
                        "🟢 Mark Ready",
                        key=f"ready_{order['order_id']}",
                    ):
                        with db() as conn:
                            result = conn.execute("""
                                UPDATE orders
                                SET status='Ready'
                                WHERE order_id=?
                                  AND payment_status IN ('Paid', 'Demo Paid')
                                  AND status='Preparing'
                            """, (order["order_id"],))

                        if result.rowcount == 1:
                            st.success("Order marked Ready.")
                        else:
                            st.warning(
                                "Order status changed. Refresh the queue."
                            )

                        st.rerun()

                elif order["status"] == "Ready":
                    c.info("Waiting for pickup verification.")

        if st.button("🔄 Refresh Kitchen"):
            st.rerun()


# ===================== PICKUP VERIFICATION ===================

with pickup_tab:
    st.subheader("🎟️ Verify Student Before Handing Over Food")

    st.caption(
        "Search the saved order record. A screenshot alone is not proof "
        "that an order is eligible for pickup."
    )

    pin = st.text_input(
        "Staff PIN",
        type="password",
        key="pickup_pin",
    )

    if staff_allowed(pin):
        search = st.text_input(
            "Search by order ID, college ID, name or pickup token"
        ).strip().lower()

        all_rows = get_orders()
        matching = []

        if search:
            for order in all_rows:
                values = [
                    order["order_id"] or "",
                    order["student_id"] or "",
                    order["student_name"] or "",
                    str(order["token"]),
                ]

                if any(
                    search in str(value).lower()
                    for value in values
                ):
                    matching.append(order)

        if search and not matching:
            st.warning("No matching order found.")

        for order in matching:
            with st.container(border=True):
                st.markdown(f"### 🎫 Token #{order['token']}")

                st.write("**Student:**", order["student_name"])
                st.write("**College ID:**", order["student_id"])
                st.write("**Order ID:**", order["order_id"])
                st.write("**Food:**", order["items"])
                st.write(f"**Amount:** ₹{order['total']:.2f}")
                st.write("**Payment:**", order["payment_status"])
                st.write("**Status:**", order["status"])

                if order["payment_status"] == "Demo Paid":
                    st.warning(
                        "DEMO PAYMENT ONLY — no money was transferred. "
                        "This is for demonstrating the workflow."
                    )

                elif order["payment_status"] != "Paid":
                    st.error(
                        "Payment is not confirmed. Do not hand over food."
                    )

                if order["status"] == "Collected":
                    st.error(
                        "Already collected. Do not hand over this order again."
                    )

                elif order["status"] != "Ready":
                    st.warning(
                        "The kitchen has not marked this order Ready."
                    )

                elif order["payment_status"] in ("Paid", "Demo Paid"):
                    confirmed = st.checkbox(
                        "I checked the student's details and token.",
                        key=f"confirm_{order['order_id']}",
                    )

                    if st.button(
                        "Confirm Collection",
                        key=f"collect_{order['order_id']}",
                        disabled=not confirmed,
                        type="primary",
                    ):
                        with db() as conn:
                            result = conn.execute("""
                                UPDATE orders
                                SET status='Collected'
                                WHERE order_id=?
                                  AND payment_status IN ('Paid', 'Demo Paid')
                                  AND status='Ready'
                            """, (order["order_id"],))

                        if result.rowcount == 1:
                            st.success(
                                "Collection recorded. This order cannot "
                                "be collected a second time through this workflow."
                            )
                            st.rerun()
                        else:
                            st.error(
                                "Order status changed. Refresh and verify again."
                            )


# ========================= ADMIN DASHBOARD ===================

with admin_tab:
    st.subheader("⚙️ Admin Dashboard")

    pin = st.text_input(
        "Admin PIN",
        type="password",
        key="admin_pin",
    )

    if staff_allowed(pin):
        orders = get_orders()

        total_orders = len(orders)

        # Only real Paid records count toward real revenue.
        paid_orders = [
            order for order in orders
            if order["payment_status"] == "Paid"
        ]

        demo_paid_orders = [
            order for order in orders
            if order["payment_status"] == "Demo Paid"
        ]

        revenue = sum(
            float(order["total"]) for order in paid_orders
        )

        ready = sum(
            order["status"] == "Ready" for order in orders
        )

        collected = sum(
            order["status"] == "Collected" for order in orders
        )

        m1, m2, m3, m4, m5 = st.columns(5)

        m1.metric("Total Orders", total_orders)
        m2.metric("Real Verified Revenue", f"₹{revenue:.2f}")
        m3.metric("Demo Payments", len(demo_paid_orders))
        m4.metric("Ready", ready)
        m5.metric("Collected", collected)

        st.caption(
            "Demo payments are excluded from real verified revenue."
        )

        st.divider()
        st.subheader("🍽️ Menu and Inventory")

        with db() as conn:
            menu_df = pd.read_sql_query("""
                SELECT id, name, category, price, stock, active
                FROM menu
                ORDER BY category, name
            """, conn)

        st.dataframe(
            menu_df,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.subheader("📋 Order History")

        if orders:
            export_df = pd.DataFrame([
                dict(order) for order in orders
            ])

            st.dataframe(
                export_df,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "⬇️ Download Order Report (CSV)",
                export_df.to_csv(index=False).encode("utf-8"),
                "campusbites_orders.csv",
                "text/csv",
            )
        else:
            st.info("No orders have been created yet.")

        st.divider()
        st.subheader("🔥 High-Traffic Demo Test")

        st.caption(
            "Creates 100 clearly labelled unpaid demo records. "
            "These do not enter the kitchen queue or count as revenue."
        )

        if st.button("Generate 100 Demo Orders"):
            with db() as conn:
                for _ in range(100):
                    token_row = conn.execute(
                        "SELECT value FROM settings WHERE key='token_counter'"
                    ).fetchone()

                    number = int(token_row["value"]) + 1

                    conn.execute(
                        "UPDATE settings SET value=? WHERE key='token_counter'",
                        (str(number),),
                    )

                    demo_id = f"DEMO-{uuid.uuid4().hex[:10].upper()}"

                    conn.execute("""
                        INSERT INTO orders(
                            order_id, token, student_name, student_id,
                            items, total, gateway_fee, net_amount,
                            status, payment_status, created_at,
                            payment_method
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        demo_id,
                        number,
                        "Demo Student",
                        "DEMO-ID",
                        "Crispy Samosa x1",
                        31.00,
                        0.00,
                        31.00,
                        "Demo",
                        "Demo - Unpaid",
                        datetime.datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "Stress Test (Demo)",
                    ))

            st.success("100 unpaid demo records created.")
            st.rerun()

        st.divider()
        st.subheader("♻️ Reset Demo Orders")

        with st.expander("Reset all order data"):
            st.warning(
                "This permanently deletes saved order history, including "
                "student orders and stress-test records."
            )

            confirm = st.checkbox(
                "I understand this deletes all saved orders."
            )

            if st.button(
                "Reset Orders",
                disabled=not confirm,
            ):
                reset_demo()

                st.session_state.cart = []
                st.session_state.last_order_id = None

                st.success("Order data has been reset.")
                st.rerun()


# ============================ FOOTER =========================

st.divider()

st.caption(
    "CampusBites · Demo-only QR and payment simulation · "
    "Unique pickup tokens · One-time pickup workflow · "
    "No real money collected"
)
