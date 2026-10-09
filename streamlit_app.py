
import sqlite3
import uuid
import datetime
from pathlib import Path
from io import BytesIO

import pandas as pd
import qrcode
import requests
import streamlit as st

st.set_page_config(
    page_title="CampusBites Zero-Touch Canteen",
    page_icon="🍱",
    layout="wide",
)

DB = str(Path(__file__).parent / "campusbites.db")

# Razorpay credentials must be stored in Streamlit Secrets.
try:
    RZP_KEY = st.secrets["razorpay"]["key_id"]
    RZP_SECRET = st.secrets["razorpay"]["key_secret"]
except Exception:
    RZP_KEY = ""
    RZP_SECRET = ""

try:
    APP_URL = st.secrets["app"]["public_url"].rstrip("/")
    STAFF_PIN = str(st.secrets["app"]["staff_pin"])
except Exception:
    APP_URL = ""
    STAFF_PIN = ""

# ---------------- DATABASE ----------------

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
                payment_id TEXT DEFAULT ''
            )
        """)

        # Upgrade an existing database without deleting its records.
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
    # Allocate a unique token and order ID in one transaction.
    items_text = ", ".join(
        f"{x['name']} x{x['qty']}" for x in cart
    )
    food_total = sum(x["price"] * x["qty"] for x in cart)
    fee = round(total * 0.0236, 2)
    net = round(total - fee, 2)
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
                status, payment_status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, token, student_name, student_id,
            items_text, total, fee, net,
            "Awaiting Payment", "Pending", now,
        ))

    return order_id, token


# ---------------- RAZORPAY ----------------

def razorpay_ready():
    return bool(RZP_KEY and RZP_SECRET and APP_URL.startswith("https://"))


def create_payment_link(order_id):
    """Create a real Razorpay hosted checkout link."""

    if not razorpay_ready():
        raise RuntimeError(
            "Payment is not configured. Add Razorpay keys and the public "
            "HTTPS app URL in Streamlit Secrets."
        )

    order = get_order(order_id)
    if not order:
        raise RuntimeError("Order not found.")

    if order["payment_status"] == "Paid":
        raise RuntimeError("This order has already been paid.")

    if order["razorpay_link_id"]:
        response = requests.get(
            "https://api.razorpay.com/v1/payment_links/"
            + order["razorpay_link_id"],
            auth=(RZP_KEY, RZP_SECRET),
            timeout=20,
        )
        response.raise_for_status()
        link = response.json()

        if link.get("status") == "paid":
            verify_payment_link(link["id"])
            raise RuntimeError(
                "Razorpay reports this payment as paid. Refresh the app."
            )

        if link.get("status") in ("created", "issued"):
            return link["short_url"]

        raise RuntimeError(
            "The existing payment link is no longer payable. "
            "Please contact the canteen staff."
        )

    payload = {
        "amount": int(round(float(order["total"]) * 100)),
        "currency": "INR",
        "accept_partial": False,
        "reference_id": order["order_id"],
        "description": f"CampusBites order {order['order_id']}",
        "customer": {"name": order["student_name"]},
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "callback_url": APP_URL,
        "callback_method": "get",
        "notes": {
            "student_id": str(order["student_id"])[:200],
            "pickup_token": str(order["token"]),
        },
    }

    response = requests.post(
        "https://api.razorpay.com/v1/payment_links",
        json=payload,
        auth=(RZP_KEY, RZP_SECRET),
        timeout=20,
    )
    response.raise_for_status()
    link = response.json()

    with db() as conn:
        conn.execute("""
            UPDATE orders SET razorpay_link_id=?
            WHERE order_id=?
        """, (link["id"], order_id))

    return link["short_url"]


def verify_payment_link(link_id):
    """Check payment with Razorpay's authenticated server API."""

    if not razorpay_ready():
        return False, "Razorpay credentials are not configured."

    response = requests.get(
        "https://api.razorpay.com/v1/payment_links/" + link_id,
        auth=(RZP_KEY, RZP_SECRET),
        timeout=20,
    )
    response.raise_for_status()
    link = response.json()

    with db() as conn:
        order = conn.execute("""
            SELECT * FROM orders WHERE razorpay_link_id=?
        """, (link_id,)).fetchone()

        if not order:
            return False, "No matching order found."

        expected_amount = int(round(float(order["total"]) * 100))

        if link.get("reference_id") != order["order_id"]:
            return False, "Payment reference does not match the order."

        if int(link.get("amount", -1)) != expected_amount:
            return False, "Payment amount does not match the order."

        if link.get("status") != "paid":
            return False, "Payment is not confirmed yet."

        if int(link.get("amount_paid", 0)) != expected_amount:
            return False, "The confirmed payment amount does not match."

        payment_id = ""
        for payment in link.get("payments", []):
            if payment.get("status") == "captured":
                payment_id = payment.get("payment_id", "")
                break

        # Only update the order after the server-side checks pass.
        conn.execute("""
            UPDATE orders
            SET payment_status='Paid',
                payment_id=?,
                status=CASE
                    WHEN status='Awaiting Payment' THEN 'Preparing'
                    ELSE status
                END
            WHERE order_id=?
              AND razorpay_link_id=?
              AND payment_status!='Paid'
        """, (payment_id, order["order_id"], link_id))

    return True, "Payment verified with Razorpay."


def handle_payment_return():
    link_id = st.query_params.get("razorpay_payment_link_id")
    reference = st.query_params.get(
        "razorpay_payment_link_reference_id"
    )

    if not link_id:
        return

    try:
        ok, message = verify_payment_link(link_id)

        order = None
        with db() as conn:
            order = conn.execute("""
                SELECT order_id FROM orders WHERE razorpay_link_id=?
            """, (link_id,)).fetchone()

        if not order or reference != order["order_id"]:
            ok = False
            message = "The payment return did not match the saved order."

        st.session_state["payment_notice"] = (ok, message)

    except Exception:
        st.session_state["payment_notice"] = (
            False,
            "Payment could not be checked right now. Use Check Payment "
            "Status below or contact the canteen staff.",
        )
    finally:
        st.query_params.clear()
        st.rerun()


def make_qr(url):
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------- UTILITIES ----------------

def staff_allowed(pin):
    if not STAFF_PIN:
        st.error("Set app.staff_pin in Streamlit Secrets first.")
        return False
    return pin == STAFF_PIN


def update_status(order_id, status):
    with db() as conn:
        conn.execute(
            "UPDATE orders SET status=? WHERE order_id=?",
            (status, order_id),
        )


def reset_demo():
    with db() as conn:
        conn.execute("DELETE FROM orders")
        conn.execute("""
            UPDATE settings SET value='100'
            WHERE key='token_counter'
        """)


init_db()
handle_payment_return()

if "cart" not in st.session_state:
    st.session_state.cart = []

# ---------------- HEADER ----------------

st.markdown("""
<style>
.block-container {padding-top: 1.5rem;}
.hero {
    background: linear-gradient(120deg,#173d31,#2c8061);
    padding: 1.5rem;
    border-radius: 18px;
    color: white;
    margin-bottom: 1rem;
}
.hero h1 {color: white; margin: 0;}
.hero p {color: #e5f5ec; margin-top: .4rem;}
</style>
<div class="hero">
<h1>🍱 CampusBites — Zero-Touch Canteen</h1>
<p>Student ordering · Razorpay checkout · Unique pickup tokens</p>
</div>
""", unsafe_allow_html=True)

notice = st.session_state.pop("payment_notice", None)
if notice:
    if notice[0]:
        st.success(notice[1])
    else:
        st.warning(notice[1])

orders_now = get_orders()
st.sidebar.header("🟢 System Status")
st.sidebar.success("App online")
st.sidebar.metric("Total orders", len(orders_now))
st.sidebar.info(
    "Real payment checkout requires your Razorpay credentials. "
    "The QR below will open the actual hosted checkout link."
)

student_tab, kitchen_tab, pickup_tab, admin_tab = st.tabs([
    "📱 Student App",
    "🖨️ Kitchen",
    "🎟️ Pickup Verification",
    "⚙️ Admin & Stress Test",
])

# ---------------- STUDENT APP ----------------

with student_tab:
    st.subheader("📍 Today's Menu")
    menu = get_menu()

    for item in menu:
        left, price_col, add_col = st.columns([4, 1, 1])
        left.markdown(f"**{item['name']}**")
        left.caption(
            f"{item['category']} · Available stock: {item['stock']}"
        )
        price_col.markdown(f"### ₹{item['price']:.0f}")

        if add_col.button("Add", key=f"add_{item['id']}"):
            existing = next(
                (x for x in st.session_state.cart
                 if x["name"] == item["name"]),
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
                x["price"] * x["qty"]
                for x in st.session_state.cart
            )
            handling_fee = 1.00
            total = round(food_total + handling_fee, 2)

            st.write(f"Food total: ₹{food_total:.2f}")
            st.write(f"Handling fee: ₹{handling_fee:.2f}")
            st.markdown(f"## Final amount: ₹{total:.2f}")

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
                checkout = st.form_submit_button(
                    "Create order and payment QR",
                    type="primary",
                    use_container_width=True,
                )

            if checkout:
                if not student_name.strip() or not student_id.strip():
                    st.error("Enter both your name and college ID.")
                elif not razorpay_ready():
                    st.error(
                        "Razorpay is not configured yet. Follow the Secrets "
                        "setup instructions below the code."
                    )
                else:
                    try:
                        order_id, token = allocate_order(
                            student_name.strip(),
                            student_id.strip(),
                            st.session_state.cart,
                            total,
                        )
                        payment_url = create_payment_link(order_id)
                        st.session_state["last_order_id"] = order_id
                        st.session_state["payment_url"] = payment_url
                        st.session_state.cart = []
                        st.rerun()
                    except Exception as exc:
                        st.error("Could not create the payment checkout.")
                        st.caption(str(exc))

            if st.button("🗑️ Empty Basket"):
                st.session_state.cart = []
                st.rerun()

    last_id = st.session_state.get("last_order_id")
    payment_url = st.session_state.get("payment_url")

    if last_id:
        order = get_order(last_id)
        if order:
            st.divider()
            st.subheader("Your order")
            st.metric("Pickup token", f"#{order['token']}")
            st.write("**Order ID:**", order["order_id"])
            st.write("**Student:**", order["student_name"])
            st.write("**College ID:**", order["student_id"])
            st.write("**Items:**", order["items"])
            st.write(f"**Total:** ₹{order['total']:.2f}")
            st.write("**Payment:**", order["payment_status"])
            st.write("**Kitchen status:**", order["status"])

            if order["payment_status"] != "Paid":
                if payment_url:
                    st.image(
                        make_qr(payment_url),
                        width=220,
                        caption="Scan to open Razorpay checkout",
                    )
                    st.link_button(
                        "Pay with Razorpay",
                        payment_url,
                        use_container_width=True,
                    )

                if order["razorpay_link_id"]:
                    if st.button("Check Payment Status"):
                        try:
                            ok, message = verify_payment_link(
                                order["razorpay_link_id"]
                            )
                            if ok:
                                st.success(message)
                            else:
                                st.warning(message)
                            st.rerun()
                        except Exception:
                            st.error(
                                "Could not check payment right now. Try again."
                            )
            else:
                st.success(
                    "Payment verified. Keep your order ID and pickup token."
                )

# ---------------- KITCHEN ----------------

with kitchen_tab:
    st.subheader("🖨️ Kitchen Queue")
    pin = st.text_input("Staff PIN", type="password", key="kitchen_pin")

    if staff_allowed(pin):
        orders = get_orders()
        active = [
            o for o in orders
            if o["payment_status"] == "Paid"
            and o["status"] not in ("Collected", "Completed")
        ]

        if not active:
            st.info("No paid orders waiting in the kitchen.")
        for order in active:
            with st.container(border=True):
                a, b, c = st.columns([3, 2, 2])
                a.markdown(f"### 🎫 Token #{order['token']}")
                a.write(order["order_id"])
                a.write(order["student_name"])
                a.caption(f"College ID: {order['student_id']}")
                b.write(order["items"])
                b.write(f"₹{order['total']:.2f}")
                b.success("Payment: Paid")
                c.write(f"**Status: {order['status']}**")

                if order["status"] == "Preparing":
                    if c.button(
                        "🟢 Mark Ready",
                        key=f"ready_{order['order_id']}",
                    ):
                        with db() as conn:
                            conn.execute("""
                                UPDATE orders SET status='Ready'
                                WHERE order_id=?
                                  AND payment_status='Paid'
                                  AND status='Preparing'
                            """, (order["order_id"],))
                        st.rerun()

                elif order["status"] == "Ready":
                    c.info("Waiting for verified pickup at the counter.")

        if st.button("Refresh kitchen"):
            st.rerun()

# ---------------- PICKUP VERIFICATION ----------------

with pickup_tab:
    st.subheader("🎟️ Verify student before handing over food")
    st.caption(
        "Search the live order record. Do not trust a screenshot as proof."
    )

    pin = st.text_input("Staff PIN", type="password", key="pickup_pin")

    if staff_allowed(pin):
        search = st.text_input(
            "Search by order ID, college ID, name or token"
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
                if any(search in str(value).lower() for value in values):
                    matching.append(order)

        if search and not matching:
            st.warning("No matching order found.")

        for order in matching:
            with st.container(border=True):
                st.markdown(f"### Token #{order['token']}")
                st.write("**Student:**", order["student_name"])
                st.write("**College ID:**", order["student_id"])
                st.write("**Order ID:**", order["order_id"])
                st.write("**Food:**", order["items"])
                st.write(f"**Amount:** ₹{order['total']:.2f}")
                st.write("**Payment:**", order["payment_status"])
                st.write("**Status:**", order["status"])

                if order["payment_status"] != "Paid":
                    st.error("Payment not verified. Do not hand over food.")
                elif order["status"] == "Collected":
                    st.error("Already collected. Do not hand over again.")
                elif order["status"] != "Ready":
                    st.warning("The kitchen has not marked this order Ready.")
                else:
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
                                UPDATE orders SET status='Collected'
                                WHERE order_id=?
                                  AND payment_status='Paid'
                                  AND status='Ready'
                            """, (order["order_id"],))

                        if result.rowcount == 1:
                            st.success(
                                "Collection recorded. This order cannot "
                                "be collected a second time."
                            )
                            st.rerun()
                        else:
                            st.error(
                                "Order status changed. Refresh and verify again."
                            )

# ---------------- ADMIN ----------------

with admin_tab:
    st.subheader("⚙️ Admin Dashboard")
    pin = st.text_input("Admin PIN", type="password", key="admin_pin")

    if staff_allowed(pin):
        orders = get_orders()
        total_orders = len(orders)
        paid_orders = [o for o in orders if o["payment_status"] == "Paid"]
        revenue = sum(float(o["total"]) for o in paid_orders)
        ready = sum(o["status"] == "Ready" for o in orders)
        collected = sum(o["status"] == "Collected" for o in orders)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Orders", total_orders)
        m2.metric("Verified Revenue", f"₹{revenue:.2f}")
        m3.metric("Ready", ready)
        m4.metric("Collected", collected)

        st.divider()
        st.subheader("Menu and Inventory")
        with db() as conn:
            menu_df = pd.read_sql_query("""
                SELECT id, name, category, price, stock, active
                FROM menu ORDER BY category, name
            """, conn)
        st.dataframe(menu_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Order History")
        if orders:
            export_df = pd.DataFrame([dict(o) for o in orders])
            st.dataframe(export_df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download Order Report (CSV)",
                export_df.to_csv(index=False).encode("utf-8"),
                "campusbites_orders.csv",
                "text/csv",
            )

        st.divider()
        st.subheader("High-Traffic Demo Test")
        st.caption(
            "Creates clearly labelled unpaid demo records. "
            "They are not real paid orders and will not enter the kitchen queue."
        )

        if st.button("🔥 Generate 100 Demo Orders"):
            with db() as conn:
                for i in range(100):
                    token = conn.execute(
                        "SELECT value FROM settings WHERE key='token_counter'"
                    ).fetchone()
                    number = int(token["value"]) + 1
                    conn.execute(
                        "UPDATE settings SET value=? WHERE key='token_counter'",
                        (str(number),),
                    )
                    demo_id = f"DEMO-{uuid.uuid4().hex[:10].upper()}"
                    conn.execute("""
                        INSERT INTO orders(
                            order_id, token, student_name, student_id,
                            items, total, gateway_fee, net_amount,
                            status, payment_status, created_at
                        )
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        demo_id, number, "Demo Student", "DEMO-ID",
                        "Crispy Samosa x1", 31.00, 0.00, 31.00,
                        "Demo", "Demo - Unpaid",
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ))
            st.success("100 unpaid demo records created.")
            st.rerun()

        with st.expander("Reset all order data"):
            st.warning("This permanently deletes the saved order history.")
            confirm = st.checkbox("I understand this deletes all orders.")
            if st.button("♻️ Reset Orders", disabled=not confirm):
                reset_demo()
                st.session_state.cart = []
                st.session_state.pop("last_order_id", None)
                st.session_state.pop("payment_url", None)
                st.rerun()

st.divider()
st.caption(
    "CampusBites · Razorpay checkout · Server-side payment checks · "
    "Unique tokens · One-time pickup verification"
)
