"""MCP Server for Iran Khodro (IKCO) website - ikco.ir"""

import httpx
import json
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ikco-server")

BASE_URL = "https://www.ikco.ir"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_page(url: str, timeout: int = 15) -> str | None:
    try:
        with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text
    except httpx.RequestError as e:
        return None
    except httpx.HTTPStatusError as e:
        return None


def fetch_json(url: str, timeout: int = 15) -> dict | list | None:
    try:
        with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


@mcp.tool()
def get_homepage_info() -> str:
    """صفحه اصلی سایت ایران خودرو را بارگذاری و اطلاعات کلی را برمی‌گرداند."""
    html = fetch_page(BASE_URL)
    if not html:
        return "خطا در اتصال به سایت ایران خودرو"

    soup = BeautifulSoup(html, "lxml")

    # Remove scripts and styles
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else "بدون عنوان"

    # Get main menu items
    menu_items = []
    for a in soup.select("nav a, .menu a, .navbar a")[:20]:
        text = a.get_text(strip=True)
        href = a.get("href", "")
        if text and len(text) > 1:
            menu_items.append(f"{text}: {href}")

    # Get headings
    headings = []
    for h in soup.find_all(["h1", "h2", "h3"])[:15]:
        text = h.get_text(strip=True)
        if text:
            headings.append(text)

    result = f"عنوان صفحه: {title}\n\n"
    if menu_items:
        result += "منوها:\n" + "\n".join(menu_items[:10]) + "\n\n"
    if headings:
        result += "سرتیترها:\n" + "\n".join(headings) + "\n"

    return result


@mcp.tool()
def get_car_list() -> str:
    """لیست خودروهای ایران خودرو را برمی‌گرداند."""
    urls_to_try = [
        f"{BASE_URL}/fa/products",
        f"{BASE_URL}/fa/cars",
        f"{BASE_URL}/products",
        f"{BASE_URL}/fa",
    ]

    for url in urls_to_try:
        html = fetch_page(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        cars = []

        # Look for car product cards
        for card in soup.select(".product-card, .car-card, .product-item, .car-item, article")[:20]:
            name = card.find(["h2", "h3", "h4", ".title", ".name"])
            if name:
                text = name.get_text(strip=True)
                if text:
                    cars.append(text)

        if cars:
            return "خودروهای ایران خودرو:\n" + "\n".join(f"- {c}" for c in cars)

    # Try API endpoint
    api_url = f"{BASE_URL}/api/products"
    data = fetch_json(api_url)
    if data:
        return f"داده‌های API:\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}"

    return f"لیست خودروها از {urls_to_try[0]} در دسترس نیست. لطفاً مستقیماً به {BASE_URL} مراجعه کنید."


@mcp.tool()
def get_car_details(car_name: str) -> str:
    """جزئیات یک خودرو خاص از ایران خودرو را جستجو و برمی‌گرداند.

    Args:
        car_name: نام خودرو مورد نظر مثل 'دنا' یا 'پژو 207'
    """
    search_url = f"{BASE_URL}/fa/search?q={car_name}"
    html = fetch_page(search_url)

    if not html:
        search_url = f"{BASE_URL}/search?q={car_name}"
        html = fetch_page(search_url)

    if not html:
        return f"خطا در جستجوی {car_name}"

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()

    results = []
    for item in soup.select(".search-result, .product, article, .car-item")[:5]:
        text = item.get_text(separator="\n", strip=True)
        if text and len(text) > 20:
            results.append(text[:500])

    if results:
        return f"نتایج جستجو برای '{car_name}':\n\n" + "\n\n---\n\n".join(results)

    # Try direct product page
    car_slug = car_name.replace(" ", "-").lower()
    product_url = f"{BASE_URL}/fa/products/{car_slug}"
    html = fetch_page(product_url)
    if html:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l for l in text.splitlines() if l.strip()]
        return "\n".join(lines[:50])

    return f"اطلاعاتی برای '{car_name}' یافت نشد."


@mcp.tool()
def get_news() -> str:
    """آخرین اخبار و اطلاعیه‌های ایران خودرو را برمی‌گرداند."""
    news_urls = [
        f"{BASE_URL}/fa/news",
        f"{BASE_URL}/news",
        f"{BASE_URL}/fa/media/news",
    ]

    for url in news_urls:
        html = fetch_page(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        news_items = []

        for item in soup.select("article, .news-item, .news-card, .post")[:10]:
            title = item.find(["h2", "h3", "h4", ".title"])
            date = item.find([".date", ".time", "time", ".post-date"])
            summary = item.find(["p", ".summary", ".excerpt", ".description"])

            entry = {}
            if title:
                entry["عنوان"] = title.get_text(strip=True)
            if date:
                entry["تاریخ"] = date.get_text(strip=True)
            if summary:
                entry["خلاصه"] = summary.get_text(strip=True)[:200]

            if entry.get("عنوان"):
                news_items.append(entry)

        if news_items:
            result = f"آخرین اخبار ایران خودرو ({url}):\n\n"
            for i, item in enumerate(news_items, 1):
                result += f"{i}. {item.get('عنوان', '')}\n"
                if item.get("تاریخ"):
                    result += f"   تاریخ: {item['تاریخ']}\n"
                if item.get("خلاصه"):
                    result += f"   {item['خلاصه']}\n"
                result += "\n"
            return result

    return "اخبار در دسترس نیست"


@mcp.tool()
def get_price_list() -> str:
    """لیست قیمت خودروهای ایران خودرو را برمی‌گرداند."""
    price_urls = [
        f"{BASE_URL}/fa/price-list",
        f"{BASE_URL}/fa/prices",
        f"{BASE_URL}/price-list",
        f"{BASE_URL}/fa/products/price",
    ]

    for url in price_urls:
        html = fetch_page(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")

        # Look for price tables
        tables = soup.find_all("table")
        if tables:
            result = f"لیست قیمت از {url}:\n\n"
            for table in tables[:2]:
                rows = table.find_all("tr")
                for row in rows[:20]:
                    cols = row.find_all(["td", "th"])
                    row_text = " | ".join(c.get_text(strip=True) for c in cols)
                    if row_text.strip():
                        result += row_text + "\n"
            return result

        # Look for price list items
        price_items = []
        for item in soup.select(".price-item, .product-price, .car-price")[:15]:
            text = item.get_text(separator=" | ", strip=True)
            if text:
                price_items.append(text)

        if price_items:
            return f"لیست قیمت از {url}:\n\n" + "\n".join(price_items)

    return f"لیست قیمت در حال حاضر در دسترس نیست. برای اطلاعات دقیق به {BASE_URL} مراجعه کنید."


@mcp.tool()
def fetch_ikco_url(url: str) -> str:
    """محتوای هر صفحه‌ای از سایت ایران خودرو را بارگذاری می‌کند.

    Args:
        url: آدرس کامل صفحه مورد نظر در سایت ikco.ir
    """
    if not ("ikco.ir" in url or url.startswith("/")):
        return "فقط URLهای سایت ikco.ir مجاز هستند"

    if url.startswith("/"):
        url = BASE_URL + url

    html = fetch_page(url)
    if not html:
        return f"خطا در بارگذاری {url}"

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines[:100])


if __name__ == "__main__":
    mcp.run()
