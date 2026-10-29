import os
import json
import hashlib
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin

PAGE_URL = "https://dscc.gov.bd/pages/office-orders"
STATE_FILE = Path("state.json")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DSCCOfficeOrderMonitor/1.0)"
}


def get_orders():
    from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()

retry_strategy = Retry(
    total=3,
    connect=3,
    read=2,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)

session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

response = session.get(
    PAGE_URL,
    headers=HEADERS,
    timeout=(20, 45),
)

response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")

    if table is None:
        raise RuntimeError("Office order table not found")

    orders = []

    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)

        if len(cells) < 5:
            continue

        title = cells[1].get_text(" ", strip=True)
        date = cells[4].get_text(" ", strip=True)

        if not title:
            continue

        links = row.find_all("a", href=True)
        detail_url = PAGE_URL

        for link in links:
            href = link["href"]
            if "/pages/office-orders/" in href:
                detail_url = urljoin(PAGE_URL, href)
                break

        identity = f"{title}|{date}|{detail_url}"
        order_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()

        orders.append({
            "id": order_id,
            "title": title,
            "date": date,
            "url": detail_url,
        })

    if not orders:
        raise RuntimeError(
            "No office orders found. Website structure may have changed."
        )

    return orders


def send_telegram(order):
    message = (
        "🔔 DSCC — নতুন অফিস আদেশ\n\n"
        f"📌 শিরোনাম: {order['title']}\n"
        f"📅 প্রকাশের তারিখ: {order['date']}\n\n"
        f"🔗 আদেশ দেখুন: {order['url']}"
    )

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        api_url,
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()

    if not response.json().get("ok"):
        raise RuntimeError("Telegram could not send the message")


def main():
    orders = get_orders()

    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as file:
            previous_ids = set(json.load(file))
        first_run = False
    else:
        previous_ids = set()
        first_run = True

    current_ids = {order["id"] for order in orders}

    if first_run:
        print(f"Initial setup: saving {len(orders)} existing orders.")
    else:
        new_orders = [
            order for order in orders
            if order["id"] not in previous_ids
        ]

        # Send oldest first when multiple new orders appear.
        for order in reversed(new_orders):
            send_telegram(order)
            print(f"Notification sent: {order['title']}")

    # Keep a rolling history of the IDs seen on the monitored page.
    updated_ids = previous_ids | current_ids

    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(sorted(updated_ids), file, ensure_ascii=False, indent=2)

    print(f"Check complete: {len(orders)} orders found.")


if __name__ == "__main__":
    main()
