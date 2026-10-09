
import streamlit as st
import sqlite3
import qrcode
import pandas as pd
import json
import uuid
from io import BytesIO
from pathlib import Path
from datetime import datetime

# -------------------- CONFIGURATION --------------------

st.set_page_config(
    page_title="CampusBites | RVRJC",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_PATH = Path(__file__).parent / "campusbites.db"

STAFF_PIN = st.secrets.get("app", {}).get("staff_pin", "1234")

DEFAULT_MENU = [
    ("Hot Crispy Dosa", 35, "Breakfast"),
    ("Steaming Soft Idli (Plate)", 30, "Breakfast"),
    ("Special Filter Coffee", 15, "Drinks"),
    ("Chai / Tea", 12, "Drinks"),
    ("Crispy Samosa (Plate)", 30, "Snacks"),
]

# -------------------- DATABASE --------------------

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
                status TEXT DEFAULT 'Awaiting Payment',
                payment_status TEXT DEFAULT 'Pending',
                created_at TEXT,
                razorpay_link_id TEXT,
                payment_id TEXT,
                payment_method TEXT DEFAULT 'Demo QR'
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
            "payment_method": "TEXT DEFAULT 'Demo QR'",
        }

        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(
                    f"ALTER TABLE orders ADD COLUMN {column} {definition}"
                )

        count = conn.execute(
            "SELECT COUNT(*) FROM menu"
        ).fetchone()[0]

        if count == 0:
            conn.executemany(
                "INSERT INTO menu (name, price, category, active) "
                "VALUES (?, ?, ?, 1)",
                DEFAULT_MENU
            )


initialize_db()

# -------------------- HELPERS --------------------

def money(amount):
    return f"₹{float(amount):.2f}"


def get_menu():
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM menu WHERE active = 1 ORDER BY category, name"
        ).fetchall()


def get_orders():
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC"
        ).fetchall()


def normalize_id(value):
    return str(value or "").strip().upper()


def create_order(name, college_id, basket, payment_method):
    subtotal = sum(
        float(item["price"]) * int(item["quantity"])
        for item in basket
    )
    fee = 1.00
    total = subtotal + fee

    order_id = "CB-" + uuid.uuid4().hex[:8].upper()

    with connect_db() as conn:
        previous = conn.execute(
            "SELECT COALESCE(MAX(token), 100) FROM orders"
        ).fetchone()[0]
        token = int(previous or 100) + 1

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
            "Awaiting Payment",
            "Pending",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            payment_method
        ))

    return order_id


def get_order(order_id):
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE order_id = ?",
            (order_id,)
        ).fetchone()


def create_order_qr(order):
    """Create a QR containing readable demo order details."""
    items = json.loads(order["items"])

    item_lines = [
        f'{item["name"]} x {item["quantity"]}'
        for item in items
    ]

    subtotal = sum(
        float(item["price"]) * int(item["quantity"])
        for item in items
    )
    fee = float(order["total"]) - subtotal

    qr_text = "\n".join([
        "CAMPUSBITES - DEMO ORDER",
        "NOT A REAL PAYMENT QR",
        f'Order ID: {order["order_id"]}',
        f'Name: {order["student_name"]}',
        f'College ID: {order["student_id"]}',
        f'Pickup Token: {order["token"]}',
        "Items:",
        *item_lines,
        f"Food subtotal: INR {subtotal:.2f}",
        f"Demo service fee: INR {fee:.2f}",
        f'AMOUNT TO PAY: INR {float(order["total"]):.2f}',
        f'Order status: {order["status"]}',
        "Payment is simulated. No money transferred."
    ])

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=7,
        border=3
    )
    qr.add_data(qr_text)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def simulate_payment(order_id):
    with connect_db() as conn:
        conn.execute("""
            UPDATE orders
            SET payment_status = 'Demo Paid',
                status = 'Preparing'
            WHERE order_id = ?
              AND payment_status = 'Pending'
              AND status = 'Awaiting Payment'
        """, (order_id,))


def update_order_status(order_id, new_status):
    with connect_db() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?",
            (new_status, order_id)
        )


def get_items_text(order):
    try:
        items = json.loads(order["items"])
        return ", ".join(
            f'{item["name"]} x {item["quantity"]}'
            for item in items
        )
    except (ValueError, TypeError, KeyError):
        return str(order["items"])


# -------------------- DESIGN --------------------

st.markdown("""
<style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }
    h1, h2, h3 {
        letter-spacing: -0.4px;
    }
    div.stButton > button {
        width: 100%;
        min-height: 42px;
        border-radius: 9px;
        font-weight: 600;
    }
    div[data-testid="stMetric"] {
        border: 1px solid rgba(128,128,128,0.25);
        padding: 14px;
        border-radius: 12px;
    }
    div[data-testid="stTabs"] button {
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

st.title("🍽️ CampusBites")
st.caption("RVR & JC College of Engineering · Smart Canteen Demo")

st.info(
    "Demo version: payments are simulated. The QR displays order details "
    "and the amount, but does not transfer money."
)

# -------------------- TABS --------------------

tab_order, tab_kitchen, tab_give, tab_admin = st.tabs([
    "🛒 Order Food",
    "👨‍🍳 Kitchen",
    "🤝 Give Food",
    "📊 Admin"
])

# ============================================================
# 1. STUDENT ORDER PAGE
# ============================================================

with tab_order:
    st.subheader("Order your food")

    menu_rows = get_menu()

    left, right = st.columns([1.15, 0.85], gap="large")

    with left:
        st.markdown("#### Today's menu")

        if not menu_rows:
            st.warning("No menu items are available.")
        else:
            # Display menu items in two columns.
            for start in range(0, len(menu_rows), 2):
                menu_cols = st.columns(2, gap="small")

                for col, item in zip(
                    menu_cols, menu_rows[start:start + 2]
                ):
                    with col:
                        with st.container(border=True):
                            st.markdown(f'**{item["name"]}**')
                            st.caption(item["category"])
                            st.write(money(item["price"]))

                            key = f'qty_{item["id"]}'
                            if key not in st.session_state:
                                st.session_state[key] = 0

                            st.number_input(
                                f'Quantity — {item["name"]}',
                                min_value=0,
                                max_value=20,
                                step=1,
                                key=key,
                                label_visibility="collapsed"
                            )

    with right:
        st.markdown("#### Your basket")

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
                    f'{item["name"]} × {item["quantity"]} '
                    f'— {money(item["price"] * item["quantity"])}'
                )
        else:
            st.caption("Choose an item from the menu to begin.")

        st.divider()
        st.write(f"Food subtotal: **{money(subtotal)}**")
        st.write(f"Demo service fee: **{money(fee)}**")
        st.markdown(f"### Total: {money(total)}")

        st.markdown("#### Student details")

        student_name = st.text_input(
            "Full name",
            key="student_name",
            placeholder="Enter your name"
        )

        student_id = st.text_input(
            "College ID",
            key="student_id",
            placeholder="Enter your college ID"
        )

        payment_method = st.selectbox(
            "Demo payment method",
            ["Demo QR", "Demo Cash"],
            help="Both choices are simulated. No real payment is made."
        )

        if st.button("Place Order", type="primary"):
            if not basket:
                st.error("Please select at least one food item.")
            elif not student_name.strip():
                st.error("Please enter your name.")
            elif not student_id.strip():
                st.error("Please enter your college ID.")
            else:
                new_order_id = create_order(
                    student_name,
                    student_id,
                    basket,
                    payment_method
                )
                st.session_state["last_order_id"] = new_order_id
                st.rerun()

        # Show the latest order and its QR.
        last_order_id = st.session_state.get("last_order_id")

        if last_order_id:
            order = get_order(last_order_id)

            if order:
                st.divider()
                st.markdown("#### Your order")

                st.success(f'Order ID: {order["order_id"]}')
                st.write(f'**Status:** {order["status"]}')
                st.write(f'**Payment:** {order["payment_status"]}')
                st.write(f'**Pickup token:** {order["token"]}')
                st.write(f'**Amount:** {money(order["total"])}')
                st.write(f'**College ID:** {order["student_id"]}')

                if (
                    payment_method == "Demo QR"
                    or order["payment_method"] == "Demo QR"
                ):
                    st.image(
                        create_order_qr(order),
                        caption="Scan to view order details and amount",
                        width=230
                    )

                    st.download_button(
                        "Download order QR",
                        data=create_order_qr(order),
                        file_name=f'{order["order_id"]}_QR.png',
                        mime="image/png"
                    )

                if (
                    order["payment_status"] == "Pending"
                    and order["status"] == "Awaiting Payment"
                ):
                    if st.button(
                        "✅ Simulate Payment Complete",
                        type="primary",
                        key="pay_demo"
                    ):
                        simulate_payment(order["order_id"])
                        st.success("Demo payment recorded!")
                        st.rerun()

                st.caption(
                    "This is a demonstration only. Do not use this QR "
                    "to make a real payment."
                )

# ============================================================
# 2. KITCHEN PAGE
# ============================================================

with tab_kitchen:
    st.subheader("Kitchen order queue")
    st.caption("Mark an order Ready after its food is prepared.")

    kitchen_pin = st.text_input(
        "Staff PIN",
        type="password",
        key="kitchen_pin"
    )

    if kitchen_pin == STAFF_PIN:
        orders = get_orders()
        active_orders = [
            order for order in orders
            if order["status"] in ("Preparing", "Ready")
            and order["payment_status"] in ("Demo Paid", "Paid")
        ]

        if not active_orders:
            st.info("No orders are waiting in the kitchen.")
        else:
            for order in active_orders:
                with st.container(border=True):
                    st.markdown(
                        f'**{order["student_name"]}** · '
                        f'`{order["student_id"]}`'
                    )
                    st.caption(
                        f'{order["order_id"]} · '
                        f'Token {order["token"]}'
                    )
                    st.write(get_items_text(order))
                    st.write(f'Total: **{money(order["total"])}**')

                    if order["status"] == "Preparing":
                        if st.button(
                            "Mark Ready",
                            key=f'ready_{order["order_id"]}',
                            type="primary"
                        ):
                            update_order_status(
                                order["order_id"],
                                "Ready"
                            )
                            st.rerun()
                    else:
                        st.success("Ready for collection")
    elif kitchen_pin:
        st.error("Incorrect staff PIN.")

# ============================================================
# 3. GIVE FOOD PAGE
# ============================================================

with tab_give:
    st.subheader("Give food to student")
    st.write(
        "Ask the student to show their physical college ID card. "
        "Search their college ID below and confirm the matching order."
    )

    give_pin = st.text_input(
        "Staff PIN",
        type="password",
        key="give_pin"
    )

    if give_pin == STAFF_PIN:
        search_id = st.text_input(
            "Search by college ID",
            placeholder="Example: Y25EC006",
            key="search_college_id"
        )

        if search_id.strip():
            orders = get_orders()
            matched_orders = [
                order for order in orders
                if normalize_id(order["student_id"])
                == normalize_id(search_id)
                and order["status"] in ("Ready", "Collected")
            ]

            if not matched_orders:
                st.warning(
                    "No Ready or Collected orders found for this college ID."
                )

            for order in matched_orders:
                with st.container(border=True):
                    st.markdown(f'**{order["student_name"]}**')
                    st.write(f'College ID: `{order["student_id"]}`')
                    st.write(f'Order: `{order["order_id"]}`')
                    st.write(f'Food: {get_items_text(order)}')
                    st.write(f'Amount: **{money(order["total"])}**')

                    if order["status"] == "Ready":
                        st.success("Food is ready")

                        if st.button(
                            "🍱 Give Food",
                            key=f'give_{order["order_id"]}',
                            type="primary"
                        ):
                            with connect_db() as conn:
                                result = conn.execute("""
                                    UPDATE orders
                                    SET status = 'Collected'
                                    WHERE order_id = ?
                                      AND status = 'Ready'
                                      AND payment_status IN ('Demo Paid', 'Paid')
                                """, (order["order_id"],))

                            if result.rowcount:
                                st.success(
                                    "Food marked as given successfully."
                                )
                            else:
                                st.warning(
                                    "This order has changed. Refresh and check again."
                                )
                            st.rerun()
                    else:
                        st.info("This order has already been collected.")

    elif give_pin:
        st.error("Incorrect staff PIN.")

# ============================================================
# 4. ADMIN PAGE
# ============================================================

with tab_admin:
    st.subheader("Admin dashboard")

    admin_pin = st.text_input(
        "Admin PIN",
        type="password",
        key="admin_pin"
    )

    if admin_pin == STAFF_PIN:
        orders = get_orders()

        total_orders = len(orders)
        demo_paid = sum(
            1 for order in orders
            if order["payment_status"] == "Demo Paid"
        )
        ready_count = sum(
            1 for order in orders if order["status"] == "Ready"
        )
        collected_count = sum(
            1 for order in orders if order["status"] == "Collected"
        )
        demo_revenue = sum(
            float(order["total"])
            for order in orders
            if order["payment_status"] == "Demo Paid"
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total orders", total_orders)
        c2.metric("Demo paid", demo_paid)
        c3.metric("Ready", ready_count)
        c4.metric("Collected", collected_count)

        st.metric("Demo payment total", money(demo_revenue))
        st.caption(
            "Demo totals are not actual money received by the canteen."
        )

        st.markdown("#### Order history")

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
                    "Payment": order["payment_status"],
                    "Status": order["status"],
                    "Created": order["created_at"],
                })

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.download_button(
                "📥 Download order history CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="campusbites_orders.csv",
                mime="text/csv"
            )
        else:
            st.info("No orders have been placed yet.")

        st.divider()
        st.markdown("#### Menu management")

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
            "Menu items can be edited in the SQLite database. "
            "This simple demo does not include an in-app menu editor."
        )

        st.divider()
        st.markdown("#### Reset demo data")

        st.warning(
            "This permanently deletes all orders from the local demo database."
        )

        confirm_reset = st.checkbox(
            "I understand that all order history will be deleted."
        )

        if st.button("Reset All Orders", type="secondary"):
            if confirm_reset:
                with connect_db() as conn:
                    conn.execute("DELETE FROM orders")
                st.session_state.pop("last_order_id", None)
                st.success("Order history cleared.")
                st.rerun()
            else:
                st.error("Tick the confirmation box first.")

    elif admin_pin:
        st.error("Incorrect admin PIN.")

# -------------------- FOOTER --------------------

st.divider()
st.caption(
    "CampusBites · RVR & JC College of Engineering · "
    "Student prototype · Demo payments only"
)
