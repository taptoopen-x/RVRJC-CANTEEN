
import streamlit as st
import qrcode
from io import BytesIO
import sqlite3
import datetime
import random
import string
import pandas as pd

st.set_page_config(
    page_title="CampusBites Zero-Touch Canteen",
    page_icon="⚡",
    layout="wide",
)

DB = "campusbites.db"

# ---------------- DATABASE ----------------
def db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
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
            items TEXT NOT NULL,
            total REAL NOT NULL,
            gateway_fee REAL NOT NULL,
            net_amount REAL NOT NULL,
            status TEXT NOT NULL,
            payment_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    defaults = [
        ("Hot Crispy Dosa", 35, "Breakfast", 100),
        ("Steaming Soft Idli (Plate)", 30, "Breakfast", 100),
        ("Special Filter Coffee", 15, "Beverage", 100),
        ("Chai / Tea", 12, "Beverage", 100),
        ("Crispy Samosa (Plate)", 30, "Snack", 100),
    ]
    for item in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO menu(name,price,category,stock) VALUES(?,?,?,?)",
            item
        )
    if conn.execute("SELECT 1 FROM settings WHERE key='token_counter'").fetchone() is None:
        conn.execute("INSERT INTO settings(key,value) VALUES('token_counter','100')")
    conn.commit()
    conn.close()

def next_token():
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key='token_counter'").fetchone()
    token = int(row["value"]) + 1
    conn.execute("UPDATE settings SET value=? WHERE key='token_counter'", (str(token),))
    conn.commit()
    conn.close()
    return token

def make_order_id(token):
    return f"CB{datetime.datetime.now().strftime('%Y%m%d')}-{token}"

def gateway_fee(total):
    # Prototype estimate only. Replace with the actual merchant fee from the
    # selected payment provider in production.
    return round(total * 0.0236, 2)

def create_order(cart, handling_fee=1.0):
    food_total = sum(x["price"] * x["qty"] for x in cart)
    total = round(food_total + handling_fee, 2)
    fee = gateway_fee(total)
    net = round(total - fee, 2)
    token = next_token()
    oid = make_order_id(token)
    item_text = ", ".join(f"{x['name']} x{x['qty']}" for x in cart)
    conn = db()
    conn.execute("""
        INSERT INTO orders(order_id,token,items,total,gateway_fee,net_amount,
                           status,payment_status,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
    """, (oid, token, item_text, total, fee, net, "Preparing",
          "Verified", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return oid, token, total

def get_menu():
    conn = db()
    rows = conn.execute("SELECT * FROM menu WHERE active=1 ORDER BY category,name").fetchall()
    conn.close()
    return rows

def get_orders():
    conn = db()
    rows = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    conn.close()
    return rows

def update_status(order_id, status):
    conn = db()
    conn.execute("UPDATE orders SET status=? WHERE order_id=?", (status, order_id))
    conn.commit()
    conn.close()

def clear_completed():
    conn = db()
    conn.execute("DELETE FROM orders WHERE status='Completed'")
    conn.commit()
    conn.close()

def reset_demo():
    conn = db()
    conn.execute("DELETE FROM orders")
    conn.execute("UPDATE settings SET value='100' WHERE key='token_counter'")
    conn.commit()
    conn.close()

init_db()

if "cart" not in st.session_state:
    st.session_state.cart = []

# ---------------- HEADER ----------------
st.title("⚡ CampusBites — Zero-Touch Campus Canteen")
st.caption("Prototype: Student ordering → payment verification → token → kitchen workflow → ready for collection")

with st.sidebar:
    st.header("🟢 System Status")
    st.success("Online")
    st.metric("Orders in Queue", len(get_orders()))
    st.markdown("---")
    st.info(
        "Demo mode: payment verification is simulated. "
        "Production mode can connect the same workflow to a real payment provider webhook."
    )

tab_student, tab_kitchen, tab_admin = st.tabs([
    "📱 Student App", "🖨️ Kitchen / Counter", "⚙️ Admin & Stress Test"
])

# ---------------- STUDENT ----------------
with tab_student:
    st.subheader("📍 Today's Menu")
    menu = get_menu()

    for row in menu:
        c1, c2, c3 = st.columns([4, 1, 1])
        with c1:
            st.markdown(f"**{row['name']}**")
            st.caption(f"{row['category']} • Stock: {row['stock']}")
        with c2:
            st.markdown(f"### ₹{row['price']:.0f}")
        with c3:
            if st.button("Add", key=f"add_{row['id']}", use_container_width=True):
                found = False
                for x in st.session_state.cart:
                    if x["name"] == row["name"]:
                        x["qty"] += 1
                        found = True
                        break
                if not found:
                    st.session_state.cart.append({
                        "name": row["name"], "price": float(row["price"]), "qty": 1
                    })
                st.rerun()

    st.divider()
    st.subheader("🛒 Your Basket")

    if not st.session_state.cart:
        st.info("Your basket is empty.")
    else:
        new_cart = []
        for i, item in enumerate(st.session_state.cart):
            c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
            with c1:
                st.write(f"**{item['name']}**")
            with c2:
                st.write(f"₹{item['price']:.0f}")
            with c3:
                st.write(f"× {item['qty']}")
            with c4:
                if st.button("−", key=f"minus_{i}"):
                    item["qty"] -= 1
                if item["qty"] > 0:
                    new_cart.append(item)
        st.session_state.cart = new_cart

        food_total = sum(x["price"] * x["qty"] for x in st.session_state.cart)
        handling_fee = 1.00
        total = round(food_total + handling_fee, 2)

        st.markdown(f"**Food Total:** ₹{food_total:.2f}")
        st.markdown(f"**Platform Handling Fee:** ₹{handling_fee:.2f}")
        st.markdown(f"## Final Amount: ₹{total:.2f}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🗑️ Empty Basket", use_container_width=True):
                st.session_state.cart = []
                st.rerun()

        # Demo QR
        upi_url = (
            f"upi://pay?pa=canteen@razorpay&pn=CampusBites"
            f"&am={total:.2f}&cu=INR&tn=CampusBites-Demo"
        )
        qr = qrcode.QRCode(version=1, box_size=5, border=2)
        qr.add_data(upi_url)
        qr.make(fit=True)
        img = qr.make_image()
        buf = BytesIO()
        img.save(buf, format="PNG")

        with c2:
            st.image(buf.getvalue(), width=180, caption="Demo UPI QR")

        st.warning("🔒 DEMO PAYMENT: The button below simulates a verified payment webhook.")

        if st.button("📲 Simulate Verified Payment", type="primary", use_container_width=True):
            oid, token, final_total = create_order(st.session_state.cart)
            st.session_state.cart = []
            st.success(f"✅ Payment verified! Order **{oid}** | Token **#{token}**")
            st.balloons()
            st.info("🖨️ Kitchen ticket generated automatically.")
            st.rerun()

# ---------------- KITCHEN ----------------
with tab_kitchen:
    st.subheader("🖨️ Automated Kitchen & Counter Queue")
    orders = get_orders()

    if not orders:
        st.info("No active orders. Create an order from the Student App.")
    else:
        active = [o for o in orders if o["status"] != "Completed"]
        st.metric("Active Orders", len(active))

        for o in active:
            with st.container(border=True):
                a, b, c = st.columns([3, 2, 2])
                with a:
                    st.markdown(f"### 🎫 Token #{o['token']}")
                    st.write(f"**Order:** {o['order_id']}")
                    st.write(o["items"])
                    st.caption(o["created_at"])
                with b:
                    st.metric("Amount", f"₹{o['total']:.2f}")
                    st.success(f"Payment: {o['payment_status']}")
                with c:
                    st.write(f"**Status:** {o['status']}")
                    if o["status"] == "Preparing":
                        if st.button("🟢 Mark Ready", key=f"ready_{o['order_id']}"):
                            update_status(o["order_id"], "Ready")
                            st.rerun()
                    elif o["status"] == "Ready":
                        if st.button("🎉 Complete / Collected", key=f"complete_{o['order_id']}"):
                            update_status(o["order_id"], "Completed")
                            st.rerun()

        if st.button("🧹 Clear Completed Orders"):
            clear_completed()
            st.rerun()

# ---------------- ADMIN ----------------
with tab_admin:
    st.subheader("⚙️ Admin Dashboard")

    orders = get_orders()
    total_orders = len(orders)
    revenue = sum(float(o["total"]) for o in orders)
    ready = sum(o["status"] == "Ready" for o in orders)
    completed = sum(o["status"] == "Completed" for o in orders)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Orders", total_orders)
    m2.metric("Revenue", f"₹{revenue:.2f}")
    m3.metric("Ready", ready)
    m4.metric("Completed", completed)

    st.divider()

    st.markdown("### 📦 Menu & Inventory")
    conn = db()
    menu_df = pd.read_sql_query("SELECT id,name,category,price,stock FROM menu ORDER BY category,name", conn)
    conn.close()
    st.dataframe(menu_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 🚨 High-Traffic Stress Test")
    st.write("Generate 100 verified demo orders to demonstrate queue handling.")

    if st.button("🔥 Simulate 100 Instant Orders", type="primary"):
        progress = st.progress(0)
        for i in range(100):
            # Use a low-cost demo item and bypass the UI cart.
            demo_cart = [{"name": "Crispy Samosa (Plate)", "price": 30.0, "qty": 1}]
            create_order(demo_cart)
            progress.progress((i + 1) / 100)
        st.success("💥 100 demo orders verified and added to the kitchen queue.")
        st.rerun()

    if st.button("♻️ Reset Demo Data"):
        reset_demo()
        st.session_state.cart = []
        st.success("Demo data reset.")
        st.rerun()

    st.divider()
    st.markdown("### 📊 Order Export")
    if orders:
        export_df = pd.DataFrame([dict(o) for o in orders])
        st.download_button(
            "⬇️ Download Order Report (CSV)",
            export_df.to_csv(index=False).encode("utf-8"),
            "campusbites_orders.csv",
            "text/csv"
        )

    st.divider()
    st.info(
        "Production roadmap: replace the simulated payment action with a real payment "
        "provider checkout + server-side webhook signature verification; move SQLite to "
        "a persistent cloud database; connect a thermal printer on the canteen LAN; "
        "add authentication and role-based access."
    )
