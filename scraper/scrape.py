"""
New Rochelle Toyota - vAuto Used Car Price List Scraper
Cox Automotive SSO two-step login with full diagnostics.
Credentials from environment variables only.
"""

import os, re, sys, time
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
LOGIN_URL     = "https://provision.vauto.app.coxautoinc.com/Va/Login/"
INVENTORY_URL = "https://provision.vauto.app.coxautoinc.com/Va/Inventory/"
OUTPUT_DIR  = Path(__file__).parent.parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "index.html"


def log(msg):
    print(msg, flush=True)


def make_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def upgrade_photo_url(url):
    return re.sub(r"/resize/\d+x\d+/", "/resize/400x300/", url)


def parse_name_tag(tag):
    m = re.fullmatch(r"([a-z]+)\.([a-z]+)", tag.strip())
    if m:
        return f"{m.group(1).capitalize()} {m.group(2).capitalize()}"
    return None


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


def _dump_page_state(driver, label):
    log(f"=== [{label}] ===")
    log(f"  URL   : {driver.current_url}")
    log(f"  Title : {driver.title}")
    try:
        body = driver.find_element(By.TAG_NAME, "body").text[:1500]
        log(f"  Body:\n{body}")
    except Exception as e:
        log(f"  Body: (error: {e})")
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        shot = OUTPUT_DIR / f"debug_{label}.png"
        driver.save_screenshot(str(shot))
        log(f"  Screenshot -> {shot}")
    except Exception as e:
        log(f"  Screenshot failed: {e}")


# ── Login ───────────────────────────────────────────────────────────────────

def login(driver):
    log("--- LOGIN START ---")
    log(f"Navigating to {LOGIN_URL} ...")
    driver.get(LOGIN_URL)
    wait = WebDriverWait(driver, 30)
    time.sleep(2)
    log(f"Redirected to: {driver.current_url}")
    log(f"Page title   : {driver.title}")

    # Step 1: username
    log("Waiting for username field...")
    username_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
        "input[type='text'], input[type='email'], input[name='username'], "
        "input[autocomplete='username'], input[name='identifier']")))
    time.sleep(0.5)
    username_field.clear()
    username_field.send_keys(VAUTO_USERNAME)
    log(f"Entered username (len={len(VAUTO_USERNAME)}).")

    next_btn = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")))
    next_btn.click()
    log("Clicked Next.")
    time.sleep(2)
    log(f"URL after Next  : {driver.current_url}")
    log(f"Title after Next: {driver.title}")

    # Step 2: password
    log("Waiting for password field...")
    try:
        password_field = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
    except Exception:
        _dump_page_state(driver, "no_password_field")
        raise
    time.sleep(0.5)
    password_field.clear()
    password_field.send_keys(VAUTO_PASSWORD)
    log(f"Entered password (len={len(VAUTO_PASSWORD)}).")
    time.sleep(0.5)

    submit_btn = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")))
    submit_btn.click()
    log("Clicked Sign In. Waiting for redirect...")
    time.sleep(2)
    log(f"URL after submit  : {driver.current_url}")
    log(f"Title after submit: {driver.title}")

    _dump_page_state(driver, "after_submit")

    sso_domain = "signin.coxautoinc.com"
    try:
        wait.until(lambda d: sso_domain not in d.current_url)
        log(f"Login successful! Now at: {driver.current_url}")
    except Exception:
        _dump_page_state(driver, "login_timeout")
        raise RuntimeError(
            "Login timed out. Browser stayed on SSO page. "
            "Check after_submit and login_timeout debug output above."
        )
    log("--- LOGIN END ---")
    time.sleep(3)


# ── Inventory ────────────────────────────────────────────────────────────────

def scrape_inventory(driver):
    log("Loading inventory page...")
    driver.get(INVENTORY_URL)
    wait = WebDriverWait(driver, 30)
    log(f"Inventory URL: {driver.current_url}")
    try:
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "tr.vehicleRow, tr[data-stocknumber], .inventory-row")))
    except Exception:
        _dump_page_state(driver, "inventory_load_fail")
        raise
    time.sleep(3)
    rows = driver.find_elements(By.CSS_SELECTOR,
        "tr.vehicleRow, tr[data-stocknumber], tr.v-inventory-row")
    if not rows:
        rows = [r for r in driver.find_elements(By.TAG_NAME, "tr")
                if "cai-media-management" in r.get_attribute("innerHTML")]
    log(f"Found {len(rows)} vehicle rows.")
    vehicles = []
    for row in rows:
        try:
            v = parse_row(driver, row)
            if v: vehicles.append(v)
        except Exception as exc:
            log(f"  Skipping row: {exc}")
    return vehicles


def _txt(row, *selectors):
    for sel in selectors:
        els = row.find_elements(By.CSS_SELECTOR, sel)
        if els: return els[0].text.strip()
    return ""


def parse_row(driver, row):
    html = row.get_attribute("innerHTML")
    photo_url = ""
    for img in row.find_elements(By.TAG_NAME, "img"):
        src = img.get_attribute("src") or ""
        if "cai-media-management" in src:
            photo_url = upgrade_photo_url(src); break
    stock = (row.get_attribute("data-stocknumber") or "").strip()
    if not stock:
        m = re.search(r"stock[:\s#]*([A-Z0-9]+)", html, re.IGNORECASE)
        stock = m.group(1) if m else "—"
    ymm = _txt(row, "td.ymm", "td.vehicle-name", ".vehicleTitle", ".ymm")
    if not ymm:
        m = re.search(r"\b(19|20)\d{2}\b[^\n<]{3,40}", html)
        ymm = m.group(0).strip() if m else "Unknown"
    mileage = _txt(row, "td.mileage", ".mileage", "td[data-col='mileage']")
    if not mileage:
        m = re.search(r"([\d,]+)\s*mi", html, re.IGNORECASE)
        mileage = m.group(0) if m else "—"
    tag_els = row.find_elements(By.CSS_SELECTOR, ".tag, .vehicleTag, span.label")
    raw_tags = [t.text.strip() for t in tag_els if t.text.strip()]
    tag_info = classify_tags(raw_tags)
    days = _txt(row, "td.daysInInventory", ".days-in-inv", "td[data-col='daysInInventory']")
    if not days:
        m = re.search(r"\b(\d{1,3})\s*day", html, re.IGNORECASE)
        days = m.group(1) if m else "—"
    mmr = _txt(row, "td.mmr", ".mmr-value", "td[data-col='mmr']")
    if not mmr:
        m = re.search(r'mmr["\s>:$]*\$?([\d,]+)', html, re.IGNORECASE)
        mmr = ("$" + m.group(1)) if m else "—"
    list_price = _txt(row, "td.listPrice", ".list-price", "td[data-col='listPrice']", "td.price")
    if not list_price:
        m = re.search(r'list["\s>:$]*\$?([\d,]+)', html, re.IGNORECASE)
        list_price = ("$" + m.group(1)) if m else "—"
    appraised = _txt(row, "td.appraisedValue", ".appraised", "td[data-col='appraisedValue']")
    if not appraised:
        m = re.search(r'apprais[^$]*\$?([\d,]+)', html, re.IGNORECASE)
        appraised = ("$" + m.group(1)) if m else "—"
    return {"photo": photo_url, "stock": stock, "ymm": ymm, "mileage": mileage,
            "title_status": tag_info["title_status"], "sold_to": tag_info["sold_to"],
            "days": days, "mmr": mmr, "list_price": list_price,
            "appraised": appraised, "raw_tags": raw_tags}


# ── HTML builder ─────────────────────────────────────────────────────────────

def row_color(v):
    if v["sold_to"]:       return "#fffde7"
    if v["title_status"] == "clear": return "#e8f5e9"
    return "#fff3e0"


def build_html(vehicles):
    now   = datetime.now().strftime("%B %d, %Y %I:%M %p")
    total = len(vehicles)
    avail = sum(1 for v in vehicles if not v["sold_to"])
    sold  = total - avail
    clear = sum(1 for v in vehicles if v["title_status"]=="clear" and not v["sold_to"])

    rows_html = ""
    for v in vehicles:
        bg = row_color(v)
        photo = (f'<img src="{v["photo"]}" style="width:120px;height:80px;object-fit:cover;border-radius:4px;">'
                 if v["photo"] else
                 '<div style="width:120px;height:80px;background:#ddd;border-radius:4px;display:flex;align-items:center;justify-content:center;color:#999;font-size:11px;">No Photo</div>')
        t_badge = ('<span style="background:#2e7d32;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">&#10003; Clear</span>'
                   if v["title_status"]=="clear" else
                   '<span style="background:#e65100;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">Pending</span>')
        s_badge = (f'<span style="background:#f57f17;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">SOLD &mdash; {v["sold_to"]}</span>'
                   if v["sold_to"] else
                   '<span style="background:#1565c0;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;">Available</span>')
        rows_html += f"""
        <tr style="background:{bg};border-bottom:1px solid #e0e0e0;">
          <td style="padding:10px;text-align:center;">{photo}</td>
          <td style="padding:10px;font-weight:600;">{v['ymm']}</td>
          <td style="padding:10px;color:#555;">{v['stock']}</td>
          <td style="padding:10px;">{v['mileage']}</td>
          <td style="padding:10px;">{t_badge}</td>
          <td style="padding:10px;">{s_badge}</td>
          <td style="padding:10px;text-align:center;">{v['days']}</td>
          <td style="padding:10px;font-weight:600;color:#1a237e;">{v['mmr']}</td>
          <td style="padding:10px;font-weight:700;color:#b71c1c;">{v['list_price']}</td>
          <td style="padding:10px;color:#4a148c;">{v['appraised']}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>New Rochelle Toyota &mdash; Used Car Price List</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',Arial,sans-serif;background:#f5f5f5}}
    header{{background:#1a1a2e;color:#fff;padding:20px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
    header h1{{font-size:26px;letter-spacing:1px}} header h1 span{{color:#eb0a1e}}
    header .sub{{font-size:13px;opacity:.75;margin-top:4px}}
    .pbtn{{background:#eb0a1e;color:#fff;border:none;padding:10px 22px;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer}}
    .pbtn:hover{{background:#c0081a}}
    .stats{{background:#16213e;color:#fff;display:flex;flex-wrap:wrap;border-bottom:3px solid #eb0a1e}}
    .stat{{padding:14px 28px;text-align:center;flex:1;min-width:130px;border-right:1px solid rgba(255,255,255,.1)}}
    .stat:last-child{{border-right:none}}
    .stat .num{{font-size:28px;font-weight:700;color:#eb0a1e}} .stat .lbl{{font-size:11px;text-transform:uppercase;letter-spacing:1px;opacity:.8;margin-top:2px}}
    .tw{{overflow-x:auto;padding:20px 24px}}
    table{{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.12);border-radius:8px;overflow:hidden}}
    thead tr{{background:#1a1a2e;color:#fff}}
    thead th{{padding:12px 10px;font-size:12px;text-transform:uppercase;letter-spacing:.8px;text-align:left;white-space:nowrap}}
    tbody tr:hover{{filter:brightness(.97)}}
    .leg{{display:flex;gap:18px;flex-wrap:wrap;padding:0 24px 20px;font-size:13px}}
    .li{{display:flex;align-items:center;gap:6px}} .sw{{width:16px;height:16px;border-radius:3px;border:1px solid #ccc}}
    footer{{text-align:center;padding:18px;font-size:12px;background:#1a1a2e;color:rgba(255,255,255,.5)}}
    @media print{{.pbtn{{display:none}}header,thead tr,.stats{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}
  </style>
</head><body>
<header>
  <div><h1>NEW ROCHELLE <span>TOYOTA</span></h1><div class="sub">Used Car Price List &nbsp;&middot;&nbsp; Updated {now}</div></div>
  <button class="pbtn" onclick="window.print()">Print / Save PDF</button>
</header>
<div class="stats">
  <div class="stat"><div class="num">{total}</div><div class="lbl">Total</div></div>
  <div class="stat"><div class="num">{avail}</div><div class="lbl">Available</div></div>
  <div class="stat"><div class="num">{sold}</div><div class="lbl">Sold</div></div>
  <div class="stat"><div class="num">{clear}</div><div class="lbl">Clear Title</div></div>
</div>
<div class="leg">
  <div class="li"><div class="sw" style="background:#e8f5e9"></div> Available &mdash; Clear Title</div>
  <div class="li"><div class="sw" style="background:#fff3e0"></div> Available &mdash; Pending Title</div>
  <div class="li"><div class="sw" style="background:#fffde7"></div> Sold</div>
</div>
<div class="tw"><table>
<thead><tr><th>Photo</th><th>Vehicle</th><th>Stock #</th><th>Mileage</th><th>Title</th><th>Status</th><th>Days</th><th>MMR</th><th>List Price</th><th>We Paid</th></tr></thead>
<tbody>{rows_html}</tbody>
</table></div>
<footer>New Rochelle Toyota &mdash; Internal Use Only &mdash; {now}</footer>
</body></html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not VAUTO_USERNAME or not VAUTO_PASSWORD:
        raise RuntimeError("VAUTO_USERNAME and VAUTO_PASSWORD must be set.")
    log(f"Username length : {len(VAUTO_USERNAME)}")
    log(f"Password length : {len(VAUTO_PASSWORD)}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = make_driver(headless=True)
    try:
        login(driver)
        vehicles = scrape_inventory(driver)
    finally:
        driver.quit()
    log(f"Scraped {len(vehicles)} vehicles. Building HTML...")
    html = build_html(vehicles)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    log(f"Saved -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()