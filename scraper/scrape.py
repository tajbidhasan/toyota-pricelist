"""
New Rochelle Toyota - vAuto Used Car Price List Scraper
Credentials come from environment variables (never hardcoded).
"""

import os
import re
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

VAUTO_USERNAME = os.environ.get("VAUTO_USERNAME", "")
VAUTO_PASSWORD = os.environ.get("VAUTO_PASSWORD", "")
LOGIN_URL      = "https://provision.vauto.app.coxautoinc.com/Va/Login/"
INVENTORY_URL  = "https://provision.vauto.app.coxautoinc.com/Va/Inventory/"
OUTPUT_DIR     = Path(__file__).parent.parent / "output"
OUTPUT_FILE    = OUTPUT_DIR / "index.html"


def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return driver


def upgrade_photo(url):
    return re.sub(r"/resize/\d+x\d+/", "/resize/400x300/", url)


def parse_name_tag(tag):
    m = re.fullmatch(r"([a-z]+)\.([a-z]+)", tag.strip())
    return f"{m.group(1).capitalize()} {m.group(2).capitalize()}" if m else None


def classify_tags(raw_tags):
    result = {"title_status": "pending", "sold_to": None}
    for t in raw_tags:
        t = t.strip().lower()
        if t == "clear":
            result["title_status"] = "clear"
        name = parse_name_tag(t)
        if name:
            result["sold_to"] = name
    return result


def login(driver):
    print("Logging in...")
    driver.get(LOGIN_URL)
    wait = WebDriverWait(driver, 20)
    f = wait.until(EC.presence_of_element_located((By.ID, "UserName")))
    f.clear(); f.send_keys(VAUTO_USERNAME)
    p = driver.find_element(By.ID, "Password")
    p.clear(); p.send_keys(VAUTO_PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit'],input[type='submit']").click()
    wait.until(EC.url_changes(LOGIN_URL))
    print("Logged in:", driver.current_url)


def scrape_inventory(driver):
    print("Loading inventory...")
    driver.get(INVENTORY_URL)
    wait = WebDriverWait(driver, 30)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tr.vehicleRow,tr[data-stocknumber],.inventory-row")))
    time.sleep(3)
    rows = driver.find_elements(By.CSS_SELECTOR, "tr.vehicleRow,tr[data-stocknumber],tr.v-inventory-row")
    if not rows:
        rows = [r for r in driver.find_elements(By.TAG_NAME, "tr") if "cai-media-management" in (r.get_attribute("innerHTML") or "")]
    print(f"Found {len(rows)} rows.")
    vehicles = []
    for row in rows:
        try:
            v = parse_row(row)
            if v: vehicles.append(v)
        except Exception as e:
            print(f"Skipping row: {e}")
    return vehicles


def parse_row(row):
    html = row.get_attribute("innerHTML") or ""
    photo = ""
    for img in row.find_elements(By.TAG_NAME, "img"):
        src = img.get_attribute("src") or ""
        if "cai-media-management" in src:
            photo = upgrade_photo(src); break

    stock = (row.get_attribute("data-stocknumber") or "").strip()
    if not stock:
        m = re.search(r"stock[:\s#]*([A-Z0-9]+)", html, re.IGNORECASE)
        stock = m.group(1) if m else "-"

    ymm = ""
    for sel in ["td.ymm","td.vehicle-name",".vehicleTitle",".ymm"]:
        els = row.find_elements(By.CSS_SELECTOR, sel)
        if els: ymm = els[0].text.strip(); break
    if not ymm:
        m = re.search(r"\b(19|20)\d{2}\b[^\n<]{3,40}", html)
        ymm = m.group(0).strip() if m else "Unknown"

    mileage = ""
    for sel in ["td.mileage",".mileage","td[data-col='mileage']"]:
        els = row.find_elements(By.CSS_SELECTOR, sel)
        if els: mileage = els[0].text.strip(); break
    if not mileage:
        m = re.search(r"([\d,]+)\s*mi", html, re.IGNORECASE)
        mileage = m.group(0) if m else "-"

    tag_els = row.find_elements(By.CSS_SELECTOR, ".tag,.vehicleTag,span.label")
    raw_tags = [t.text.strip() for t in tag_els if t.text.strip()]
    tag_info = classify_tags(raw_tags)

    days = ""
    for sel in ["td.daysInInventory",".days-in-inv","td[data-col='daysInInventory']"]:
        els = row.find_elements(By.CSS_SELECTOR, sel)
        if els: days = els[0].text.strip(); break
    if not days:
        m = re.search(r"\b(\d{1,3})\s*day", html, re.IGNORECASE)
        days = m.group(1) if m else "-"

    mmr = ""
    for sel in ["td.mmr",".mmr-value","td[data-col='mmr']"]:
        els = row.find_elements(By.CSS_SELECTOR, sel)
        if els: mmr = els[0].text.strip(); break
    if not mmr:
        m = re.search(r'mmr["\s>:\$]*(\$?[\d,]+)', html, re.IGNORECASE)
        mmr = m.group(1) if m else "-"

    list_price = ""
    for sel in ["td.listPrice",".list-price","td[data-col='listPrice']","td.price"]:
        els = row.find_elements(By.CSS_SELECTOR, sel)
        if els: list_price = els[0].text.strip(); break
    if not list_price:
        m = re.search(r'list["\s>:\$]*(\$?[\d,]+)', html, re.IGNORECASE)
        list_price = m.group(1) if m else "-"

    appraised = ""
    for sel in ["td.appraisedValue",".appraised","td[data-col='appraisedValue']",".appraiser"]:
        els = row.find_elements(By.CSS_SELECTOR, sel)
        if els: appraised = els[0].text.strip(); break
    if not appraised:
        m = re.search(r'apprais[^\$]*(\$?[\d,]+)', html, re.IGNORECASE)
        appraised = m.group(1) if m else "-"

    return {"photo":photo,"stock":stock,"ymm":ymm,"mileage":mileage,
            "title_status":tag_info["title_status"],"sold_to":tag_info["sold_to"],
            "days":days,"mmr":mmr,"list_price":list_price,"appraised":appraised}


def row_color(v):
    if v["sold_to"]: return "#fffde7"
    return "#e8f5e9" if v["title_status"]=="clear" else "#fff3e0"


def build_html(vehicles):
    now   = datetime.now().strftime("%B %d, %Y %I:%M %p")
    total = len(vehicles)
    avail = sum(1 for v in vehicles if not v["sold_to"])
    sold  = total - avail
    clear = sum(1 for v in vehicles if v["title_status"]=="clear" and not v["sold_to"])
    rows  = ""
    for v in vehicles:
        bg = row_color(v)
        photo_html = (f'<img src="{v["photo"]}" style="width:120px;height:80px;object-fit:cover;border-radius:4px;">'
                      if v["photo"] else '<div style="width:120px;height:80px;background:#ddd;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:11px;color:#999;">No Photo</div>')
        title_b = ('<span style="background:#2e7d32;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">Clear</span>'
                   if v["title_status"]=="clear" else
                   '<span style="background:#e65100;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">Pending</span>')
        sold_b  = (f'<span style="background:#f57f17;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">SOLD - {v["sold_to"]}</span>'
                   if v["sold_to"] else
                   '<span style="background:#1565c0;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">Available</span>')
        rows += f'<tr style="background:{bg};border-bottom:1px solid #e0e0e0;"><td style="padding:10px;text-align:center;">{photo_html}</td><td style="padding:10px;font-weight:600;">{v["ymm"]}</td><td style="padding:10px;color:#555;">{v["stock"]}</td><td style="padding:10px;">{v["mileage"]}</td><td style="padding:10px;">{title_b}</td><td style="padding:10px;">{sold_b}</td><td style="padding:10px;text-align:center;">{v["days"]}</td><td style="padding:10px;font-weight:600;color:#1a237e;">{v["mmr"]}</td><td style="padding:10px;font-weight:700;color:#b71c1c;">{v["list_price"]}</td><td style="padding:10px;color:#4a148c;">{v["appraised"]}</td></tr>'
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>New Rochelle Toyota - Price List</title><style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Segoe UI',Arial,sans-serif;background:#f5f5f5}}header{{background:#1a1a2e;color:#fff;padding:20px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}header h1{{font-size:26px;letter-spacing:1px}}header h1 span{{color:#eb0a1e}}header .sub{{font-size:13px;opacity:.75;margin-top:4px}}.btn{{background:#eb0a1e;color:#fff;border:none;padding:10px 22px;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer}}.stats{{background:#16213e;color:#fff;display:flex;flex-wrap:wrap;border-bottom:3px solid #eb0a1e}}.stat{{padding:14px 28px;text-align:center;flex:1;min-width:130px;border-right:1px solid rgba(255,255,255,.1)}}.stat:last-child{{border-right:none}}.stat .n{{font-size:28px;font-weight:700;color:#eb0a1e}}.stat .l{{font-size:11px;text-transform:uppercase;letter-spacing:1px;opacity:.8;margin-top:2px}}.legend{{display:flex;gap:18px;flex-wrap:wrap;padding:16px 24px;font-size:13px}}.li{{display:flex;align-items:center;gap:6px}}.sw{{width:16px;height:16px;border-radius:3px;border:1px solid #ccc}}.wrap{{overflow-x:auto;padding:20px 24px}}table{{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.12);border-radius:8px;overflow:hidden}}thead tr{{background:#1a1a2e;color:#fff}}th{{padding:12px 10px;font-size:12px;text-transform:uppercase;letter-spacing:.8px;text-align:left;white-space:nowrap}}footer{{text-align:center;padding:18px;font-size:12px;background:#1a1a2e;color:rgba(255,255,255,.5)}}@media print{{.btn{{display:none}}}}</style></head><body><header><div><h1>NEW ROCHELLE <span>TOYOTA</span></h1><div class="sub">Used Car Inventory - Updated {now}</div></div><button class="btn" onclick="window.print()">Print / PDF</button></header><div class="stats"><div class="stat"><div class="n">{total}</div><div class="l">Total</div></div><div class="stat"><div class="n">{avail}</div><div class="l">Available</div></div><div class="stat"><div class="n">{sold}</div><div class="l">Sold</div></div><div class="stat"><div class="n">{clear}</div><div class="l">Clear Title</div></div></div><div class="legend"><div class="li"><div class="sw" style="background:#e8f5e9;"></div>Available - Clear Title</div><div class="li"><div class="sw" style="background:#fff3e0;"></div>Available - Pending</div><div class="li"><div class="sw" style="background:#fffde7;"></div>Sold</div></div><div class="wrap"><table><thead><tr><th>Photo</th><th>Vehicle</th><th>Stock#</th><th>Mileage</th><th>Title</th><th>Status</th><th>Days</th><th>MMR</th><th>List</th><th>We Paid</th></tr></thead><tbody>{rows}</tbody></table></div><footer>New Rochelle Toyota - Internal Use Only - {now}</footer></body></html>"""


def main():
    if not VAUTO_USERNAME or not VAUTO_PASSWORD:
        raise RuntimeError("VAUTO_USERNAME and VAUTO_PASSWORD must be set.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = make_driver()
    try:
        login(driver)
        vehicles = scrape_inventory(driver)
    finally:
        driver.quit()
    print(f"Building HTML for {len(vehicles)} vehicles...")
    OUTPUT_FILE.write_text(build_html(vehicles), encoding="utf-8")
    print(f"Saved: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
