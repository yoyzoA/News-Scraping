import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Set, Optional

from dateutil import parser as date_parser

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


NOTIF_ITEM_SELECTOR = ".card__item"

NOTIF_TIME_SELECTOR = ".card-date"

NOTIF_LINK_SELECTOR = ".card-title a"

LOAD_MORE_XPATH = "//*[contains(text(), 'المزيد')]"

ARTICLE_TITLE_SELECTOR = "h1" 

ARTICLE_BODY_CANDIDATES = [
    "article p",
    ".news-body p",
    ".article-body p",
]

KNOWN_CATEGORIES = [
    "محليات",
    "عربي و دولي",
    "النشرة",
    "إقتصاد",
    "رياضة",
    "خاص الجديد",
    "فن و منوعات",
]

# CSV columns
CSV_FIELDS = [
    "ScrapedAt",       # When we scraped it
    "PublishedAt",     # Datetime shown on article page (if parsed)
    "URL",
    "Title",
    "Body",
    "Category",
    "IsNotificationOnly",
]


# ---------- LOGGING SETUP ----------

def setup_logger(log_path: str) -> logging.Logger:
    logger = logging.getLogger("aljadeed_scraper")
    logger.setLevel(logging.DEBUG)

    # Console handler (INFO+)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    ch.setFormatter(ch_fmt)

    # File handler (DEBUG+)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(fh_fmt)

    # Avoid duplicate handlers if logger is reused
    if not logger.handlers:
        logger.addHandler(ch)
        logger.addHandler(fh)
    else:
        # Clear and re-add (in case of reruns)
        logger.handlers = []
        logger.addHandler(ch)
        logger.addHandler(fh)

    return logger


# ---------- CSV HELPERS ----------

def load_existing_articles(csv_path: str, logger: logging.Logger):
    """
    Load existing CSV file if it exists, return:
        - existing_rows: list of dicts
        - existing_urls: set of URL strings
    Uses utf-8-sig so Excel handles Arabic nicely.
    """
    existing_rows: List[Dict[str, str]] = []
    existing_urls: Set[str] = set()

    if not os.path.exists(csv_path):
        logger.info("CSV file %s does not exist yet; will create a new one.", csv_path)
        return existing_rows, existing_urls

    logger.info("Loading existing CSV: %s", csv_path)
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_rows.append(row)
            if row.get("URL"):
                existing_urls.add(row["URL"])

    logger.info(
        "Loaded %d existing rows, %d unique URLs.",
        len(existing_rows),
        len(existing_urls),
    )
    return existing_rows, existing_urls


def write_full_csv(
    csv_path: str,
    all_rows: List[Dict[str, str]],
    logger: logging.Logger,
):
    """
    Rewrite the entire CSV file with the given rows.
    The first row in all_rows is considered the most recent.
    Use utf-8-sig so Excel displays Arabic characters correctly.
    """
    tmp_path = csv_path + ".tmp"

    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)

    os.replace(tmp_path, csv_path)
    logger.debug("Wrote %d rows to CSV: %s", len(all_rows), csv_path)


def prepend_article_to_csv_top(
    csv_path: str,
    all_rows: List[Dict[str, str]],
    existing_urls: Set[str],
    article: Dict[str, str],
    logger: logging.Logger,
):
    """
    Insert new article dict at the TOP of all_rows and rewrite the CSV.
    Prevents duplicates using existing_urls.
    """
    url = article.get("URL")
    if not url:
        logger.warning("Article has no URL, skipping: %s", article)
        return

    if url in existing_urls:
        logger.debug("Duplicate URL (already in CSV), skipping: %s", url)
        return

    existing_urls.add(url)
    all_rows.insert(0, article)  # prepend newest at top
    logger.info("Added article: %s", article.get("Title"))

    write_full_csv(csv_path, all_rows, logger)


# ---------- SELENIUM SETUP ----------

def create_driver(headless: bool = True) -> webdriver.Chrome:
    """
    Create and return a Selenium Chrome/Chromium driver with sane defaults.
    If you're using Chrome Canary, set options.binary_location accordingly.
    """
    options = webdriver.ChromeOptions()

    # If you use Chrome Canary, uncomment and adjust this line:
    # options.binary_location = r"C:\Users\yorgo\AppData\Local\Google\Chrome SxS\Application\chrome.exe"

    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=ar,en-US")

    # For Canary you can also try chrome_type="chromium", but default usually works:
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


# ---------- ARTICLE SCRAPING ----------

def extract_published_datetime_text(driver: webdriver.Chrome) -> Optional[str]:
    """
    Try to find the element containing the datetime string like:
        '2025-11-18 | 13:57'
    by scanning elements that contain '|' and look like dates.
    """
    import re

    candidates = driver.find_elements(By.XPATH, "//*[contains(text(), '|')]")
    for el in candidates:
        text = el.text.strip()
        if re.search(r"\d{4}-\d{2}-\d{2}\s*\|\s*\d{2}:\d{2}", text):
            return text
    return None


def parse_published_datetime(dt_text: str) -> Optional[datetime]:
    """
    Convert '2025-11-18 | 13:57' to a datetime object.
    If parsing fails, return None.
    """
    try:
        cleaned = dt_text.replace("|", " ")
        cleaned = " ".join(cleaned.split())
        return date_parser.parse(cleaned, dayfirst=False)
    except Exception:
        return None


def extract_category(driver: webdriver.Chrome) -> str:
    """
    Look through all links on the article page and return the first whose
    text matches one of the known categories.
    """
    for a in driver.find_elements(By.TAG_NAME, "a"):
        text = a.text.strip()
        if text in KNOWN_CATEGORIES:
            return text
    return ""


def extract_body(driver: webdriver.Chrome, logger: logging.Logger) -> str:
    """
    Extract the article body from Al Jadeed.
    Body = ShortDesc + LongDesc
    """
    full_text_parts = []

    # 1) SHORT DESCRIPTION
    try:
        short_desc = driver.find_element(
            By.ID, "ctl00_MainContent_ArticleDetailsDescription21_lblShortDesc"
        ).text.strip()
        if short_desc:
            full_text_parts.append(short_desc)
    except:
        logger.debug("Short description not found.")

    # 2) LONG DESCRIPTION
    try:
        long_desc_container = driver.find_element(By.CSS_SELECTOR, ".LongDesc")
        long_desc_text = long_desc_container.text.strip()
        if long_desc_text:
            # Remove "Related Articles" section by truncating if needed
            cleaned = long_desc_text.split("مقالات ذات صلة")[0].strip()
            full_text_parts.append(cleaned)
    except:
        logger.debug("Long description container not found.")

    # If both failed → fallback to generic candidates
    if not full_text_parts:
        logger.debug("Falling back to generic body extraction.")
        paragraphs = []
        for selector in ARTICLE_BODY_CANDIDATES:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, selector)
                for e in elems:
                    txt = e.text.strip()
                    if txt:
                        paragraphs.append(txt)
            except:
                pass

        if paragraphs:
            return "\n".join(paragraphs)

    return "\n\n".join(full_text_parts).strip()


def scrape_article_in_new_tab(
    driver: webdriver.Chrome,
    url: str,
    logger: logging.Logger,
    max_retries: int = 3,
) -> Optional[Dict[str, str]]:
    """
    Open article URL in a new tab, scrape metadata and body, then close it.
    Returns a dict or None if all retries fail.
    """
    original_window = driver.current_window_handle

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"[Article Retry {attempt}/{max_retries}] {url}")

            # Open a new tab
            driver.execute_script("window.open(arguments[0]);", url)

            WebDriverWait(driver, 10).until(
                lambda d: len(d.window_handles) > 1
            )
            new_window = [w for w in driver.window_handles if w != original_window][0]
            driver.switch_to.window(new_window)

            # Wait for title as basic readiness
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ARTICLE_TITLE_SELECTOR))
            )

            title_el = driver.find_element(By.CSS_SELECTOR, ARTICLE_TITLE_SELECTOR)
            title = title_el.text.strip()

            # Datetime
            dt_text = extract_published_datetime_text(driver)
            published_at = ""
            published_dt = None
            if dt_text:
                published_dt = parse_published_datetime(dt_text)
                if published_dt:
                    published_at = published_dt.isoformat(timespec="minutes")

            category = extract_category(driver)
            body = extract_body(driver, logger)
            is_notification_only = "True" if not body else "False"

            article = {
                "ScrapedAt": datetime.now().isoformat(timespec="seconds"),
                "PublishedAt": published_at,
                "URL": url,
                "Title": title,
                "Body": body,
                "Category": category,
                "IsNotificationOnly": is_notification_only,
            }

            logger.info("Scraped article: %s (category=%s)", title, category or "N/A")

            driver.close()
            driver.switch_to.window(original_window)
            return article

        except Exception as e:
            logger.error("Error scraping article %s (attempt %d): %s", url, attempt, e)
            logger.debug("Full traceback:", exc_info=True)
            # Ensure we close any new tab we might have opened
            for handle in driver.window_handles:
                if handle != original_window:
                    try:
                        driver.switch_to.window(handle)
                        driver.close()
                    except Exception:
                        pass
            driver.switch_to.window(original_window)
            time.sleep(2)

    logger.error("Giving up on article after %d attempts: %s", max_retries, url)
    return None


# ---------- NOTIFICATIONS PAGINATION & MAIN LOOP ----------

def scrape_notifications_page(
    driver: webdriver.Chrome,
    base_url: str,
    until_dt: datetime,
    csv_path: str,
    logger: logging.Logger,
):
    """
    Main loop:
    - Load notifications page
    - Repeatedly:
        - Collect notification items (new ones since last iteration)
        - For each, open article in new tab and scrape
        - Stop when article's PublishedAt < until_dt
        - Otherwise click "المزيد" to load older notifs
    """
    # Load existing CSV and dedupe set
    all_rows, existing_urls = load_existing_articles(csv_path, logger)

    logger.info("Opening notifications page: %s", base_url)
    driver.get(base_url)

    # --------------------------------------------------
    # FAST POPUP + OVERLAY CLEANUP (optimized)
    # --------------------------------------------------

    # 1. Immediately remove potential blocking overlays (non-blocking)
    try:
        driver.execute_script("""
            var el1 = document.getElementById('dvPushSoftImpRequest');
            if (el1) el1.remove();
            var el2 = document.querySelector('.push-notication-parent');
            if (el2) el2.remove();
        """)
        logger.info("Pre-cleaned notification overlays.")
    except Exception:
        logger.debug("Overlay pre-clean failed (ignored).")

    # 2. Try closing the push notification popup (the close icon)
    try:
        close_btn = driver.find_element(By.CSS_SELECTOR, ".push-notification-close-icon")
        driver.execute_script("arguments[0].click();", close_btn)
        logger.info("Closed push notification popup.")
    except Exception:
        logger.info("No push notification popup detected (or already closed).")

    # 3. For safety, remove overlays again
    try:
        driver.execute_script("""
            var el1 = document.getElementById('dvPushSoftImpRequest');
            if (el1) el1.remove();
            var el2 = document.querySelector('.push-notication-parent');
            if (el2) el2.remove();
        """)
        logger.info("Post-popup overlay cleanup done.")
    except Exception:
        logger.debug("Post-popup overlay cleanup skipped.")

    # 4. Cookie banner — fast, non-blocking (1 second max)
    try:
        cookie_btn = WebDriverWait(driver, 1).until(
            EC.presence_of_element_located(
                (By.XPATH, "//button[contains(text(),'أوافق') or contains(text(),'موافق') or contains(text(),'Accept')]")
            )
        )
        driver.execute_script("arguments[0].click();", cookie_btn)
        logger.info("Accepted cookie banner.")
    except Exception:
        logger.info("No cookie banner found (or failed to click). Continuing...")

    # Wait for notifications to show up
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, NOTIF_ITEM_SELECTOR))
    )

    processed_notif_count = 0
    stop = False

    while not stop:
        logger.info("Collecting notification items...")

        notif_items = driver.find_elements(By.CSS_SELECTOR, NOTIF_ITEM_SELECTOR)
        logger.info("Currently visible notifications: %d", len(notif_items))

        # Process only new items (since last round)
        for idx in range(processed_notif_count, len(notif_items)):
            notif = notif_items[idx]

            # Extract time & URL
            try:
                time_el = notif.find_element(By.CSS_SELECTOR, NOTIF_TIME_SELECTOR)
                notif_time_text = time_el.text.strip()
            except NoSuchElementException:
                notif_time_text = ""

            try:
                link_el = notif.find_element(By.CSS_SELECTOR, NOTIF_LINK_SELECTOR)
                url = link_el.get_attribute("href")
                title_preview = link_el.text.strip()
            except NoSuchElementException:
                logger.warning("Notification item without link, skipping.")
                continue

            if not url:
                logger.warning("Notification link missing URL, skipping.")
                continue

            logger.info(
                "[%d/%d] Time=%s | Title='%s'",
                idx + 1,
                len(notif_items),
                notif_time_text,
                title_preview[:80],
            )

            # Already scraped?
            if url in existing_urls:
                logger.debug("URL already scraped, skipping: %s", url)
                continue

            # Scrape full article in new tab
            article = scrape_article_in_new_tab(driver, url, logger)
            if not article:
                logger.warning("Failed to scrape article, moving on: %s", url)
                continue

            # Determine if we should stop based on published datetime
            published_at_str = article.get("PublishedAt")
            published_dt = None
            if published_at_str:
                try:
                    published_dt = datetime.fromisoformat(published_at_str)
                except Exception:
                    logger.debug("Failed to parse PublishedAt isoformat: %s", published_at_str)

            if published_dt and published_dt < until_dt:
                logger.info(
                    "Article %s is older than 'until' (%s < %s). Stopping.",
                    article["Title"],
                    published_dt,
                    until_dt,
                )
                stop = True
                break

            # Write article to CSV (prepend at top)
            prepend_article_to_csv_top(csv_path, all_rows, existing_urls, article, logger)

        processed_notif_count = len(notif_items)

        if stop:
            break

        # Try to click "more" / "المزيد" to load older notifications
        try:
            logger.info("Trying to click 'more' (المزيد) to load older notifications...")
            more_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, LOAD_MORE_XPATH))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", more_btn)
            time.sleep(0.2)
            driver.execute_script("arguments[0].click();", more_btn)
            time.sleep(1.5)  # wait for new items to load
        except TimeoutException:
            logger.info("No more 'المزيد' button found; reached end of notifications.")
            break

    logger.info("Done. Total rows in CSV now: %d", len(all_rows))


# ---------- MAIN ENTRYPOINT ----------

def parse_args():
    parser = argparse.ArgumentParser(description="Scrape Al Jadeed pushed notifications with Selenium.")
    parser.add_argument(
        "--url",
        required=True,
        help="Notifications URL, e.g. https://www.aljadeed.tv/pushed-notifications",
    )
    parser.add_argument(
        "--until",
        required=True,
        help='Scrape back until this datetime (inclusive). Example: "2025-11-17 00:00"',
    )
    parser.add_argument(
        "--csv",
        default="aljadeed_news.csv",
        help="Path to output CSV file (default: aljadeed_news.csv)",
    )
    parser.add_argument(
        "--log",
        default="aljadeed_scraper.log",
        help="Path to log file (default: aljadeed_scraper.log)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run Chrome with a visible window (not headless).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Parse 'until' datetime (assumed local time, same as website)
    try:
        until_dt = date_parser.parse(args.until)
    except Exception as e:
        print(f"Could not parse --until '{args.until}': {e}")
        sys.exit(1)

    logger = setup_logger(args.log)
    logger.info("Starting scraper.")
    logger.info("Notifications URL: %s", args.url)
    logger.info("Until datetime: %s", until_dt.isoformat())

    driver = None
    try:
        driver = create_driver(headless=not args.no_headless)
        scrape_notifications_page(driver, args.url, until_dt, args.csv, logger)

    except WebDriverException as e:
        logger.error("WebDriverException: %s", e, exc_info=True)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user (Ctrl+C).")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
    finally:
        if driver:
            driver.quit()
        logger.info("Scraper finished.")


if __name__ == "__main__":
    main()