
# 📘 **Al Jadeed Notifications Scraper — Simplified Documentation**

## **What This Script Does**

This scraper collects news articles from:

```
https://www.aljadeed.tv/pushed-notifications
```

It automatically:

* Opens the notifications page
* Closes popups and overlays
* Extracts each notification
* Opens the full article
* Scrapes title, date, category, and full body
* Saves everything into a CSV file
* Stops when reaching a specific date
* Keeps a log file of all actions

---

# 🧠 **How the Scraper Works**

## **1. Inputs**

You run the script with:

* `--url` → notifications page
* `--until` → stop when articles get older than this date
* `--csv` → output CSV file
* `--log` → output log file
* `--no-headless` → show browser window

Example:

```
python jadeed-scraper.py `
    --url "https://www.aljadeed.tv/pushed-notifications" `
    --until "2025-11-17 00:00" `
    --csv "aljadeed_news.csv" `
    --log "aljadeed_scraper.log"

```

---

# **2. Browser Setup**

The script launches Chrome using Selenium.

It removes anything that might block clicks:

* Push-notification popup
* Cookie banner
* Hidden overlay layers

Then it waits until the notifications are visible.

---

# **3. Scraping Notifications**

Each notification contains:

* A time (e.g., "13:57")
* A title
* A link to the news article

The script reads these and opens the article in a new tab.

Duplicates are skipped immediately.

---

# **4. Scraping the Article Page**

Inside the article, the script extracts:

### ✔ Title

From the `<h1>` element.

### ✔ Published datetime

From text like `2025-11-18 | 14:22`.

### ✔ Category

Matches known categories (محليات – عربي ودولي – اقتصاد – إلخ).

### ✔ Body

This is the MOST important part.

Al Jadeed articles have **two** description sections:

1. Short description `<span id="..._lblShortDesc">`
2. Long description `<div class="LongDesc">`

The scraper combines both:

```
Short Description

Long Description
```

If no long description exists, the article is marked `"IsNotificationOnly = True"`.

---

# **5. Stop Condition**

If an article’s `PublishedAt` is **older than the `--until` date**, the scraper stops completely.

---

# **6. Pagination (“المزيد”)**

If more notifications exist, the scraper clicks “المزيد”, loads older ones, and repeats.

If the button disappears → no more data.

---

# **7. CSV Output**

Every article is saved **immediately** into the CSV.

* Newest articles are added at the **top**
* Format is UTF-8-SIG (Arabic works in Excel)
* No duplicates are ever added

Columns:

| Column             | Meaning                                |
| ------------------ | -------------------------------------- |
| ScrapedAt          | When the scraper collected the article |
| PublishedAt        | Article’s publish time                 |
| URL                | Article link                           |
| Title              | Article title                          |
| Body               | Full article text                      |
| Category           | Article category                       |
| IsNotificationOnly | True if short description only         |

---

# **8. Logging**

All actions are written to:

* Console (short logs)
* Log file (full detailed logs)

Errors include full tracebacks, which makes debugging easy.

---

# **9. Reliability**

The scraper:

* Retries every article up to 3 times
* Automatically recovers from Selenium errors
* Closes tabs safely
* Continues even if one article fails

---

# ✔ **In Summary**

This scraper:

* Reads notifications
* Opens each article
* Extracts title, date, category, body
* Cleans text
* Writes into CSV
* Avoids duplicates
* Stops at your chosen date
* Logs every step

It is fast, reliable, and fully automated.

---

If you want, I can also generate:

* **A simpler version of the script**
* **A visual flowchart**
* **A version that scrapes multiple news websites automatically**

Just tell me.
