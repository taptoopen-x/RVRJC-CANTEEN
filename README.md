# CampusBites Zero-Touch Canteen

A Streamlit prototype for an automated college canteen.

## Demo workflow

Student:
1. Select food and quantities.
2. View basket and total.
3. Scan/display a UPI-style QR.
4. Click **Simulate Verified Payment**.
5. Receive an order ID and token.

Kitchen:
1. New paid order appears automatically.
2. Kitchen marks it **Ready**.
3. Counter marks it **Completed / Collected**.

Admin:
- Revenue and order metrics
- Menu/inventory view
- CSV export
- 100-order stress test
- Reset demo data

## Important

This is a **working prototype**, not a live banking integration.

The payment button deliberately simulates a successful webhook so the project can be demonstrated without real money. For production, integrate an actual payment provider and verify webhooks server-side.

SQLite is used for the demo database. For a real multi-user deployment, use a persistent cloud database (for example PostgreSQL or Firebase) and add authentication.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Streamlit Community Cloud can deploy a GitHub repository and provides a shareable `streamlit.app` URL.
