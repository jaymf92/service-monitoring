import os
import smtplib
import time
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from collections import defaultdict
import psycopg2
load_dotenv()


# Step 1: Minimal bootstrap DB config (used only for first fetch)
BOOTSTRAP_DB = {
    "host": os.getenv("BOOTSTRAP_DB_HOST"),
    "port": int(os.getenv("BOOTSTRAP_DB_PORT", 5432)),
    "dbname": os.getenv("BOOTSTRAP_DB_NAME"),
    "user": os.getenv("BOOTSTRAP_DB_USER"),
    "password": os.getenv("BOOTSTRAP_DB_PASSWORD")
}
# Step 2: Establish DB connection using bootstrap config
def get_db_connection(config=BOOTSTRAP_DB):
    return psycopg2.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["dbname"],
        user=config["user"],
        password=config["password"]
    )

# Step 3: Load all config values (email settings, DB, check interval) from DB
def load_monitor_config():
    config = {}
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM monitor_config")
                for key, value in cur.fetchall():
                    config[key] = value
    except Exception as e:
        print(f"[CONFIG ERROR] Failed to load monitor_config: {e}")
    return config

# Step 4: Load service endpoints from DB
def load_services(config):
    services = defaultdict(dict)
    try:
        with psycopg2.connect(
            host=config["DB_HOST"],
            port=int(config["DB_PORT"]),
            dbname=config["DB_NAME"],
            user=config["DB_USER"],
            password=config["DB_PASSWORD"]
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT app_name, service_type, url FROM monitor_services")
                for app_name, service_type, url in cur.fetchall():
                    services[app_name][service_type.lower()] = url
    except Exception as e:
        print(f"[DB ERROR] Failed to load services: {e}")
    return services

# Step 5: Send email alert using loaded config
def send_email(subject, message, config):
    msg = MIMEMultipart()
    msg['From'] = config["EMAIL_FROM"]
    msg['To'] = config["EMAIL_TO"]
    # Convert comma-separated EMAIL_TO into a list
    recipient_list = [email.strip() for email in config["EMAIL_TO"].split(",")]

    msg['Subject'] = subject
    msg.attach(MIMEText(message, 'plain'))

    try:
        server = smtplib.SMTP(config["SMTP_SERVER"], int(config["SMTP_PORT"]))
        server.starttls()
        server.login(config["EMAIL_FROM"], config["EMAIL_PASSWORD"])

        # Send to all recipients
        server.sendmail(config["EMAIL_FROM"], recipient_list, msg.as_string())

        server.quit()
        print(f"[EMAIL SENT] {subject} to {', '.join(recipient_list)}")
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send email: {e}")

# Step 6: Parse unified health response and return failed services
def parse_health_response(response_json):
    failed = []
    statuses = {}
    details = response_json.get("details", {})
    for name, status in details.items():
        statuses[name] = status
        if status.lower() != "healthy":
            failed.append(f"{name.upper()} Service → {status}")
    return failed, statuses

# Step 7: Check a health endpoint and return status + parsed JSON
def check_endpoint(name, url):
    try:
        response = requests.get(url, timeout=30)
        # Accept response with JSON body (even if status is 503)
        if response.headers.get("content-type", "").startswith("application/json"):
            return True, response.json()
        else:
            print(f"[ERROR] {name} returned {response.status_code} (non-JSON)")
            return False, None
    except requests.RequestException as e:
        print(f"[DOWN] {name} FastAPI not reachable: {e}")
        return False, None

# Step 8: Main monitoring loop
def run_monitor():
    config = load_monitor_config()
    if not config:
        print("[ABORT] No configuration loaded. Exiting.")
        return

    interval = int(config.get("CHECK_INTERVAL", 120))

    while True:
        print("\n--- Running Health Checks ---")
        services = load_services(config)

        for name, endpoints in services.items():
            health_url = endpoints.get("health")
            if not health_url:
                print(f"[SKIPPED] {name} has no health URL configured.")
                continue

            # Step 1: Call health endpoint
            up, response_json = check_endpoint(f"{name}", health_url)

            if not up or not response_json:
                print(f"[DOWN] {name} FastAPI")
                subject = f"[ALERT] {name} FASTAPI is DOWN"
                message = (
                    f"ALERT: FASTAPI is DOWN\n\n"
                    f"Application Name: {name}\n"
                    f"Health Check URL: {health_url}\n\n"
                    f"FastAPI is not reachable or did not return a valid response."
                )
                send_email(subject, message, config)
                continue

            # Step 2: FastAPI is UP
            print(f"[UP] {name} FastAPI")

            failed_services = []
            details = response_json.get("details", {})

            # Step 3: Check each service in 'details'
            db_status = details.get("database", "UNKNOWN")
            gpt_status = details.get("gpt", "UNKNOWN")

            # Log & collect failed services
            if db_status.upper() != "UP":
                print(f"[DOWN] {name} Database")
                failed_services.append(f"DATABASE Service → {db_status}")
            else:
                print(f"[UP] {name} Database")

            if gpt_status.upper() != "UP":
                print(f"[DOWN] {name} GPT")
                failed_services.append(f"GPT Service → {gpt_status}")
            else:
                print(f"[UP] {name} GPT")

            # Step 4: Send a single alert email if any component failed
            if failed_services:
                subject = f"[ALERT] {name} services are DOWN"

                full_status = "\n".join(
                    [f"{k.upper()}: {v}" for k, v in details.items()]
                )

                message = (
                    f"Application Name: {name}\n"
                    f"Health Check URL: {health_url}\n\n"
                    f"The following services are DOWN:\n"
                    + "\n".join(failed_services)
                    + "\n\nFull Health Check Status:\n"
                    + full_status
                )

                send_email(subject, message, config)
            else:
                print(f"[ALL HEALTHY] {name}")

        time.sleep(interval)

# Step 9: Entry point
if __name__ == "__main__":
    run_monitor()