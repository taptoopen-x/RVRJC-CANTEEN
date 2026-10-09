import io
import os
import sqlite3
import uuid
from datetime import datetime
from urllib.parse import quote

import pandas as pd
import qrcode
import streamlit as st

# ============================================================
# CampusBites - College Canteen Ordering Demo
# Replace your entire streamlit_app.py with this file.
# ============================================================

APP_TITLE = "CampusBites"
DB_PATH = os.environ.get("CAMPUSBITES_DB", "campusbites_v2.db")
DEMO_UPI_ID = "demo-canteen@upi"  # Placeholder only; replace with a real merchant UPI ID.
MERCHANT_NAME = "RVRJC Canteen (DEMO)"
CATEGORIES = ["Snacks", "Meals", "Drinks", "Desserts", "Other"]

st.set_page_config(
    page_title="CampusBites | RVRJC Canteen",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------- Database -------------------------
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0),
                category TEXT NOT NULL DEFAULT 'Other',
                available INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_token TEXT NOT NULL UNIQUE,
                student_name TEXT NOT NULL,
                college_id TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total REAL NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'Pay at counter (Cash)',
                status TEXT NOT NULL DEFAULT 'Placed',
                created_at TEXT NOT NULL DEFAULT '',
                collected_at TEXT
            )
            """
        )

        # Safely add columns that may be missing from an older SQLite table.
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()
        }
        migrations = {
            "order_token": "TEXT",
            "student_name": "TEXT NOT NULL DEFAULT ''",
            "college_id": "TEXT NOT NULL DEFAULT ''",
            "items_json": "TEXT NOT NULL DEFAULT '[]'",
            "total": "REAL NOT NULL DEFAULT 0",
            "payment_method": "TEXT NOT NULL DEFAULT 'Pay at counter (Cash)'",
            "status": "TEXT NOT NULL DEFAULT 'Placed'",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "collected_at": "TEXT",
        }
        for column_name, column_definition in migrations.items():
            if column_name not in existing_columns:
                conn.execute(
                    f"ALTER TABLE orders ADD COLUMN {column_name} {column_definition}"
                )

        # Populate missing tokens on older rows before new orders are created.
        rows_without_token = conn.execute(
            "SELECT id FROM orders WHERE order_token IS NULL OR order_token = ''"
        ).fetchall()
        for row in rows_without_token:
            conn.execute(
                "UPDATE orders SET order_token=? WHERE id=?",
                (uuid.uuid4().hex[:6].upper(), row["id"]),
            )
        conn.commit()

    # Small, editable starter menu. Seed only when the menu is empty.
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM menu").fetchone()[0]
        if count == 0:
            starter_menu = [
                ("Samosa", 15, "Snacks", 1),
                ("Veg Sandwich", 40, "Snacks", 1),
                ("Veg Burger", 60, "Snacks", 1),
                ("French Fries", 50, "Snacks", 1),
                ("Veg Fried Rice", 70, "Meals", 1),
                ("Veg Noodles", 70, "Meals", 1),
                ("Veg Meals", 90, "Meals", 1),
                ("Veg Biryani", 100, "Meals", 1),
                ("Tea", 10, "Drinks", 1),
                ("Coffee", 20, "Drinks", 1),
                ("Lime Juice", 25, "Drinks", 1),
                ("Cold Drink", 30, "Drinks", 1),
                ("Ice Cream", 35, "Desserts", 1),
                ("Gulab Jamun", 25, "Desserts", 1),
                ("Pastry", 40, "Desserts", 1),
            ]
            now = datetime.now().isoformat(timespec="seconds")
            conn.executemany(
                "INSERT INTO menu (name, price, category, available, created_at) VALUES (?, ?, ?, ?, ?)",
                [(n, p, c, a, now) for n, p, c, a in starter_menu],
            )
            conn.commit()


def get_menu(include_unavailable=False):
    with get_connection() as conn:
        if include_unavailable:
            rows = conn.execute("SELECT * FROM menu ORDER BY category, name").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM menu WHERE available = 1 ORDER BY category, name"
            ).fetchall()
    return [dict(row) for row in rows]


def add_menu_item(name, price, category):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO menu (name, price, category, available, created_at) VALUES (?, ?, ?, 1, ?)",
            (name.strip(), float(price), category, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()


def edit_menu_item(item_id, name, price, category, available):
    with get_connection() as conn:
        conn.execute(
            "UPDATE menu SET name=?, price=?, category=?, available=? WHERE id=?",
            (name.strip(), float(price), category, int(available), int(item_id)),
        )
        conn.commit()


def delete_menu_item(item_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM menu WHERE id=?", (int(item_id),))
        conn.commit()


def create_order(student_name, college_id, items, total, payment_method):
    token = uuid.uuid4().hex[:6].upper()
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO orders
            (order_token, student_name, college_id, items_json, total, payment_method, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Placed', ?)
            """,
            (
                token,
                student_name.strip(),
                college_id.strip(),
                pd.Series(items).to_json(orient="records"),
                float(total),
                payment_method,
                now,
            ),
        )
        order_id = cur.lastrowid
        conn.commit()
    return order_id, token


def get_orders():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def find_order(search_value):
    value = search_value.strip()
    if not value:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM orders
            WHERE CAST(id AS TEXT)=? OR UPPER(order_token)=UPPER(?) OR UPPER(college_id)=UPPER(?)
            ORDER BY id DESC LIMIT 1
            """,
            (value, value, value),
        ).fetchone()
    return dict(row) if row else None


def update_order_status(order_id, status):
    collected_at = datetime.now().isoformat(timespec="seconds") if status == "Collected" else None
    with get_connection() as conn:
        conn.execute(
            "UPDATE orders SET status=?, collected_at=COALESCE(?, collected_at) WHERE id=?",
            (status, collected_at, int(order_id)),
        )
        conn.commit()


# ------------------------- Helpers -------------------------
def money(amount):
    return f"₹{float(amount):,.2f}"


def make_qr_bytes(data):
    qr = qrcode.QRCode(box_size=7, border=3)
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def safe_items_from_json(items_json):
    try:
        items = pd.read_json(io.StringIO(items_json), orient="records")
        return items.to_dict(orient="records")
    except Exception:
        return []


def show_order_details(order):
    items = safe_items_from_json(order["items_json"])
    st.write(f"**Order:** #{order['id']} · **Pickup token:** `{order['order_token']}`")
    st.write(f"**Student:** {order['student_name']} · **College ID:** {order['college_id']}")
    st.write(f"**Placed:** {order['created_at']} · **Status:** {order['status']}")
    if items:
        st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)
    st.markdown(f"### Total: {money(order['total'])}")
    st.caption(f"Payment selection: {order['payment_method']}")


# ------------------------- App -------------------------
init_db()

st.title("🍽️ CampusBites")
st.caption("RVRJC College Canteen · Student ordering, kitchen pickup, and menu administration")

student_tab, kitchen_tab, admin_tab = st.tabs(
    ["🛒 Student Menu", "👨‍🍳 Kitchen & Pickup", "⚙️ Admin & Menu"]
)

# ========================= STUDENT =========================
with student_tab:
    st.subheader("Choose from the menu")
    st.info("Browse separate food sections below. Your cart total includes items from every section.")

    menu_items = get_menu()
    if not menu_items:
        st.warning("The menu is currently empty. Ask the canteen admin to add items.")
    else:
        if "cart_version" not in st.session_state:
            st.session_state.cart_version = 0
        if "order_notice" not in st.session_state:
            st.session_state.order_notice = False

        if st.session_state.order_notice:
            st.success("Order placed successfully! Your order details are available to the kitchen using your college ID or pickup token.")
            st.session_state.order_notice = False

        quantities = {}
        for category in CATEGORIES:
            category_items = [item for item in menu_items if item["category"] == category]
            if not category_items:
                continue
            st.markdown(f"### {'🥪' if category == 'Snacks' else '🍛' if category == 'Meals' else '☕' if category == 'Drinks' else '🍨' if category == 'Desserts' else '🍽️'} {category}")
            columns = st.columns(2)
            for index, item in enumerate(category_items):
                with columns[index % 2]:
                    with st.container(border=True):
                        st.markdown(f"**{item['name']}**")
                        st.write(money(item["price"]))
                        key = f"qty_{item['id']}_{st.session_state.cart_version}"
                        quantities[item["id"]] = st.number_input(
                            "Quantity",
                            min_value=0,
                            max_value=20,
                            value=0,
                            step=1,
                            key=key,
                        )

        selected_items = []
        total = 0.0
        menu_by_id = {item["id"]: item for item in menu_items}
        for item_id, quantity in quantities.items():
            if quantity > 0:
                item = menu_by_id[item_id]
                line_total = float(item["price"]) * int(quantity)
                selected_items.append(
                    {
                        "Item": item["name"],
                        "Category": item["category"],
                        "Quantity": int(quantity),
                        "Unit price": money(item["price"]),
                        "Subtotal": money(line_total),
                    }
                )
                total += line_total

        st.divider()
        left, right = st.columns([1.3, 1])
        with left:
            st.subheader("Your cart")
            if selected_items:
                st.dataframe(pd.DataFrame(selected_items), use_container_width=True, hide_index=True)
            else:
                st.caption("Your cart is empty. Add quantities from any menu section.")
        with right:
            st.metric("Cart total", money(total))

        with st.form("checkout_form", clear_on_submit=True):
            st.subheader("Checkout")
            student_name = st.text_input("Student name")
            college_id = st.text_input("College ID")
            payment_method = st.radio(
                "Payment method",
                ["Pay at counter (Cash)", "UPI QR (demo only)", "UPI ID (demo only)", "Card/Razorpay (not connected)"],
                help="Online payment options are demonstrations only. This app does not collect or process payments.",
            )
            submit_order = st.form_submit_button(
                "Place order",
                type="primary",
                use_container_width=True,
                disabled=(not selected_items or total <= 0),
            )

        if submit_order:
            if not student_name.strip() or not college_id.strip():
                st.error("Enter both your name and college ID.")
            else:
                order_id, token = create_order(
                    student_name, college_id, selected_items, total, payment_method
                )
                st.session_state.cart_version += 1
                st.session_state.order_notice = True
                st.session_state.last_order_token = token
                st.session_state.last_order_id = order_id
                st.rerun()

        # Payment guidance is explicitly marked as a demo, not a payment request.
        with st.expander("Demo payment information"):
            st.warning("This is a college-project demo. No money is transferred and no online payment is processed.")
            st.write(f"Sample UPI ID: `{DEMO_UPI_ID}` (placeholder, not verified)")
            st.write(f"Merchant label: **{MERCHANT_NAME}**")
            demo_payload = (
                "CampusBites DEMO ONLY - no payment will be processed. "
                f"Sample UPI ID: {DEMO_UPI_ID}"
            )
            st.image(make_qr_bytes(demo_payload), caption="Demo instruction QR — NOT a real UPI payment QR", width=190)
            st.caption("For real payments, integrate a payment provider securely and use its official checkout flow. Never store card details in this app.")

# ====================== KITCHEN & PICKUP ====================
with kitchen_tab:
    st.subheader("Find and manage an order")
    st.caption("Search using the college ID, numeric order ID, or pickup token.")
    search_value = st.text_input("College ID / Order ID / Pickup token", key="kitchen_search")
    search_clicked = st.button("Find order", type="primary")
    if search_clicked:
        order = find_order(search_value)
        if order:
            st.session_state.kitchen_order_id = order["id"]
        else:
            st.session_state.kitchen_order_id = None
            st.error("No matching order found.")

    current_order_id = st.session_state.get("kitchen_order_id")
    if current_order_id:
        all_orders = get_orders()
        order = next((o for o in all_orders if o["id"] == current_order_id), None)
        if order:
            show_order_details(order)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Mark as Ready", use_container_width=True, disabled=(order["status"] in ["Ready", "Collected"])):
                    update_order_status(order["id"], "Ready")
                    st.success("Order marked Ready.")
                    st.rerun()
            with c2:
                if st.button("Confirm Collected", use_container_width=True, disabled=(order["status"] == "Collected")):
                    update_order_status(order["id"], "Collected")
                    st.success("Order marked Collected.")
                    st.rerun()
            st.warning("Before handing over food, staff should verify the student's physical college ID and pickup token.")
    st.divider()
    st.subheader("Recent orders")
    recent_orders = get_orders()[:15]
    if recent_orders:
        recent_df = pd.DataFrame(
            [
                {
                    "Order ID": o["id"],
                    "Token": o["order_token"],
                    "Student": o["student_name"],
                    "College ID": o["college_id"],
                    "Total": money(o["total"]),
                    "Status": o["status"],
                    "Placed": o["created_at"],
                }
                for o in recent_orders
            ]
        )
        st.dataframe(recent_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No orders have been placed yet.")

# ========================= ADMIN & MENU ======================
with admin_tab:
    st.subheader("Menu management")
    st.warning("Demo app: this admin page has no login or role protection. Do not expose it publicly for a real canteen.")

    add_tab, edit_tab, delete_tab = st.tabs(["➕ Add item", "✏️ Edit / availability", "🗑️ Delete item"])

    with add_tab:
        with st.form("add_menu_item_form", clear_on_submit=True):
            new_name = st.text_input("Item name", key="new_item_name")
            new_price = st.number_input("Price (₹)", min_value=0.0, max_value=100000.0, value=20.0, step=5.0, key="new_item_price")
            new_category = st.selectbox("Menu section", CATEGORIES, key="new_item_category")
            add_clicked = st.form_submit_button("Add to menu", type="primary")
        if add_clicked:
            if not new_name.strip():
                st.error("Enter an item name.")
            elif any(x["name"].casefold() == new_name.strip().casefold() for x in get_menu(include_unavailable=True)):
                st.error("An item with that name already exists.")
            else:
                add_menu_item(new_name, new_price, new_category)
                st.success(f"Added {new_name.strip()} to {new_category}.")
                st.rerun()

    all_menu_items = get_menu(include_unavailable=True)
    if all_menu_items:
        item_labels = {f"{item['name']} · {item['category']} · #{item['id']}": item for item in all_menu_items}
        selected_label = st.selectbox("Choose an existing item", list(item_labels.keys()), key="admin_selected_item")
        selected_item = item_labels[selected_label]

        with edit_tab:
            with st.form("edit_menu_item_form"):
                edit_name = st.text_input("Item name", value=selected_item["name"])
                edit_price = st.number_input(
                    "Price (₹)", min_value=0.0, max_value=100000.0,
                    value=float(selected_item["price"]), step=5.0,
                )
                edit_category = st.selectbox(
                    "Menu section", CATEGORIES,
                    index=CATEGORIES.index(selected_item["category"]) if selected_item["category"] in CATEGORIES else CATEGORIES.index("Other"),
                )
                edit_available = st.checkbox("Available to students", value=bool(selected_item["available"]))
                save_edit = st.form_submit_button("Save changes", type="primary")
            if save_edit:
                if not edit_name.strip():
                    st.error("Item name cannot be empty.")
                else:
                    duplicate = any(
                        x["id"] != selected_item["id"] and x["name"].casefold() == edit_name.strip().casefold()
                        for x in get_menu(include_unavailable=True)
                    )
                    if duplicate:
                        st.error("Another item already uses that name.")
                    else:
                        edit_menu_item(selected_item["id"], edit_name, edit_price, edit_category, edit_available)
                        st.success("Menu item updated.")
                        st.rerun()

        with delete_tab:
            st.write(f"Selected item: **{selected_item['name']}**")
            st.warning("Deleting an item removes it from the menu. If it is only sold out temporarily, use Edit / availability instead.")
            confirm_delete = st.checkbox("I understand this permanently deletes the menu item.", key=f"confirm_delete_{selected_item['id']}")
            if st.button("Delete selected item", type="secondary", disabled=not confirm_delete):
                delete_menu_item(selected_item["id"])
                st.success("Menu item deleted.")
                st.rerun()

    st.divider()
    st.subheader("Current menu by section")
    all_menu_items = get_menu(include_unavailable=True)
    if all_menu_items:
        for category in CATEGORIES:
            category_items = [x for x in all_menu_items if x["category"] == category]
            if category_items:
                with st.expander(f"{category} ({len(category_items)} items)", expanded=True):
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "ID": x["id"],
                                    "Item": x["name"],
                                    "Price": money(x["price"]),
                                    "Available": "Yes" if x["available"] else "No",
                                }
                                for x in category_items
                            ]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
    else:
        st.caption("No menu items yet.")

    st.divider()
    st.subheader("Order overview")
    orders = get_orders()
    if orders:
        totals = [float(o["total"]) for o in orders]
        placed_count = sum(o["status"] == "Placed" for o in orders)
        ready_count = sum(o["status"] == "Ready" for o in orders)
        collected_count = sum(o["status"] == "Collected" for o in orders)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total orders", len(orders))
        m2.metric("Placed", placed_count)
        m3.metric("Ready", ready_count)
        m4.metric("Collected", collected_count)
        st.metric("Total order value", money(sum(totals)))

        export_rows = []
        for order in orders:
            item_text = ", ".join(
                f"{x.get('Item', 'Item')} x{x.get('Quantity', 1)}"
                for x in safe_items_from_json(order["items_json"])
            )
            export_rows.append(
                {
                    "Order ID": order["id"],
                    "Pickup Token": order["order_token"],
                    "Student Name": order["student_name"],
                    "College ID": order["college_id"],
                    "Items": item_text,
                    "Total": order["total"],
                    "Payment Method": order["payment_method"],
                    "Status": order["status"],
                    "Created At": order["created_at"],
                    "Collected At": order["collected_at"] or "",
                }
            )
        export_df = pd.DataFrame(export_rows)
        st.dataframe(export_df, use_container_width=True, hide_index=True)
        csv_data = export_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download orders as CSV",
            data=csv_data,
            file_name="campusbites_orders.csv",
            mime="text/csv",
        )
    else:
        st.caption("Order analytics will appear after the first order.")

st.sidebar.title("🍽️ CampusBites")
st.sidebar.caption("RVRJC Canteen demo")
st.sidebar.markdown("---")
st.sidebar.markdown("**Menu sections**")
for section in CATEGORIES:
    st.sidebar.write(f"• {section}")
st.sidebar.markdown("---")
st.sidebar.caption("Project demo only. Add authentication, persistent database hosting, and a real payment-provider integration before production use.")
