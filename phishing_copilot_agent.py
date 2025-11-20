import imaplib
import email
import smtplib
import ssl
import time
import os
import json
import datetime
from email.mime.text import MIMEText
from email.header import decode_header
from dotenv import load_dotenv
from agents import Agent, Runner  # OpenAI Agents SDK

# ============================================================
# LOAD ENV VARIABLES
# ============================================================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
IMAP_PASS = os.getenv("IMAP_PASS")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set. Check your .env file.")
if not IMAP_PASS:
    raise RuntimeError("IMAP_PASS is not set. Check your .env file.")

# ============================================================
# FILES & CONFIG
# ============================================================
PHISHING_LOG_FILE = "phishing_logs.json"
REPORT_TIMESTAMP_FILE = "last_report_time.txt"
USER_DB_FILE = "phishing_users.json"
HEARTBEAT_FILE = "heartbeat.txt"

# Email Config
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "degatmor2@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_USER = "degatmor2@gmail.com"
SMTP_PASS = IMAP_PASS
WARNING_RECIPIENT = "degatmor2@gmail.com"


def update_heartbeat():
    """Updates the heartbeat file so the dashboard knows we are alive."""
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        print(f"⚠️ Failed to update heartbeat: {e}")


# ============================================================
# DATA MANAGEMENT (LOGS & USER RISK)
# ============================================================
def load_user_risk():
    """Load score from phishing_users.json"""
    try:
        if not os.path.exists(USER_DB_FILE):
            return 50
        with open(USER_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not data:
                return 50
            # Assuming we take the risk of the first user or a default
            return int(data[0].get("score", 50))
    except Exception as e:
        print(f"⚠️ Could not read {USER_DB_FILE} → using default risk 50.")
        return 50


USER_RISK_LEVEL = load_user_risk()


def compute_threshold(user_risk: int) -> int:
    """Risk-based threshold"""
    if user_risk <= 20:
        return 70
    elif user_risk <= 60:
        return 50
    else:
        return 30


def log_phishing_event(subject, sender, score, explanation, recommendation, body_snippet):
    """Saves the event to a JSON log file for the Dashboard."""
    entry = {
        "timestamp": time.time(),
        "date_str": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "subject": subject,
        "sender": sender,
        "score": score,
        "explanation": explanation,
        "recommendation": recommendation,
        "body_snippet": body_snippet[:200] + "..." if len(body_snippet) > 200 else body_snippet
    }

    logs = []
    if os.path.exists(PHISHING_LOG_FILE):
        try:
            with open(PHISHING_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except:
            logs = []

    logs.append(entry)

    with open(PHISHING_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


# ============================================================
# WEEKLY REPORT
# ============================================================
def get_logs_last_week():
    if not os.path.exists(PHISHING_LOG_FILE):
        return []

    try:
        with open(PHISHING_LOG_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
    except:
        return []

    one_week_ago = time.time() - (7 * 24 * 3600)
    recent_logs = [entry for entry in logs if entry["timestamp"] > one_week_ago]
    return recent_logs


def check_and_send_weekly_report():
    """Checks if 7 days have passed since last report. If so, sends summary."""
    now = time.time()
    last_time = 0

    if os.path.exists(REPORT_TIMESTAMP_FILE):
        try:
            with open(REPORT_TIMESTAMP_FILE, "r") as f:
                last_time = float(f.read().strip())
        except:
            pass

    # 7 days in seconds = 604800
    if (now - last_time) >= 604800:
        print("📅 Weekly cycle reached. Generating report...")
        recent_logs = get_logs_last_week()
        count = len(recent_logs)

        if count == 0:
            print("ℹ️ No phishing emails this week. Skipping report.")
        else:
            send_weekly_email(count, recent_logs)

        # Update timestamp
        with open(REPORT_TIMESTAMP_FILE, "w") as f:
            f.write(str(now))


def send_weekly_email(count, logs):
    subject_lines = "\n".join([f"- {l['subject']} (Score: {l['score']})" for l in logs[:5]])
    if count > 5:
        subject_lines += f"\n... and {count - 5} more."

    text = (
        f"📊 Weekly Phishing Security Report\n\n"
        f"In the past 7 days, the Phishing Copilot blocked {count} suspicious emails.\n\n"
        f"Top detections:\n{subject_lines}\n\n"
        f"⚠️ IMPORTANT REMINDER:\n"
        f"Please check your Spam folder periodically. While we use AI to detect threats, "
        f"false positives can happen. If a legitimate email was moved to Spam, mark it as 'Not Spam'.\n\n"
        f"Stay safe,\nPhishing Copilot Agent"
    )

    msg = MIMEText(text)
    msg["From"] = SMTP_USER
    msg["To"] = WARNING_RECIPIENT
    msg["Subject"] = f"[Weekly Stats] {count} Phishing Attempts Blocked"

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ctx) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, WARNING_RECIPIENT, msg.as_string())
        print("✅ Weekly report sent successfully.")
    except Exception as e:
        print(f"❌ Failed to send weekly report: {e}")


# ============================================================
# OPENAI AGENT
# ============================================================
phishing_agent = Agent(
    name="Phishing Copilot",
    instructions=(
        "You are a phishing detection AI.\n"
        "You MUST return ONLY a JSON object:\n"
        "{\n"
        '  "phishing_score": 0-100,\n'
        '  "explanation": "...",\n'
        '  "recommendation": "..."\n'
        "}\n\n"
        "0-30=safe, 31-70=suspicious, 71-100=phishing.\n"
        "Factor USER_RISK: high risk = more aggressive scoring.\n"
        "Do NOT output anything except JSON."
    ),
)


def analyze_email_with_agent(subject: str, body: str, user_risk: int):
    prompt = f"""
USER_RISK={user_risk}
Analyze this email. Output ONLY JSON.

Subject: {subject}
Body:
{body}
"""
    result = Runner.run_sync(phishing_agent, prompt)
    raw = result.final_output.strip()

    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except Exception as e:
        print("❌ Failed to parse JSON:", e)
        return {"phishing_score": 0, "explanation": "Parsing failed.", "recommendation": "None."}


# ============================================================
# ACTIONS
# ============================================================
def move_to_spam(mail, email_id):
    try:
        mail.store(email_id, '+X-GM-LABELS', '\\Spam')
        mail.store(email_id, '+FLAGS', '\\Deleted')
        print("🗑️ Email successfully moved to Spam.")
    except Exception as e:
        print("⚠️ Could not move email to spam:", e)

# instant email feedback after detecting phishing attemps.
# def send_warning_email(original_subject, score, explanation, recommendation):
#     text = (
#         "⚠️ Phishing attempt detected!\n\n"
#         f"Subject: {original_subject}\n"
#         f"Risk Score: {score}/100\n\n"
#         f"Explanation:\n{explanation}\n\n"
#         f"The email has been moved to Spam."
#     )
#     msg = MIMEText(text)
#     msg["From"] = SMTP_USER
#     msg["To"] = WARNING_RECIPIENT
#     msg["Subject"] = f"[WARNING] Phishing Email Deleted ({score}/100)"
#
#     try:
#         ctx = ssl.create_default_context()
#         with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ctx) as server:
#             server.login(SMTP_USER, SMTP_PASS)
#             server.sendmail(SMTP_USER, WARNING_RECIPIENT, msg.as_string())
#     except Exception as e:
#         print("❌ Failed to send warning:", e)


# ============================================================
# MAIN LOOP
# ============================================================

def fetch_unread_emails():
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(IMAP_USER, IMAP_PASS)
    mail.select("inbox")

    status, data = mail.search(None, "UNSEEN")
    if status != "OK": return [], None

    ids = data[0].split()
    emails = []

    for eid in ids:
        _, msg_data = mail.fetch(eid, "(RFC822)")
        if not msg_data: continue
        msg = email.message_from_bytes(msg_data[0][1])

        from_addr = msg.get("From", "").lower()
        if IMAP_USER.lower() in from_addr: continue

        # Decode Subject
        raw_subj = msg["Subject"]
        subject = "(no subject)"
        if raw_subj:
            s_raw, enc = decode_header(raw_subj)[0]
            subject = s_raw.decode(enc or "utf-8", errors="ignore") if isinstance(s_raw, bytes) else s_raw

        # Extract Body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(errors="ignore")
                        break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(errors="ignore")

        emails.append({"id": eid, "subject": subject, "body": body, "from": from_addr})

    return emails, mail


last_no_messages = False


# ============================================================
# MAIN LOOP
# ============================================================
def start_phishing_monitor():
    global last_no_messages
    update_heartbeat()
    print("📡 Phishing Copilot started (Background Service).")
    print(f"User risk: {USER_RISK_LEVEL} | Log file: {PHISHING_LOG_FILE}")

    while True:
        try:
            # 1. Check if we need to send weekly report
            check_and_send_weekly_report()

            # 2. Check emails
            unread, mail = fetch_unread_emails()
            threshold = compute_threshold(USER_RISK_LEVEL)

            if unread:
                last_no_messages = False
                print(f"\n📥 {len(unread)} new email(s).")
                for em in unread:
                    subject = em["subject"]
                    body = em["body"]
                    sender = em["from"]
                    eid = em["id"]

                    print(f"\n🔍 Analyzing: {subject}")
                    analysis = analyze_email_with_agent(subject, body, USER_RISK_LEVEL)
                    score = int(analysis.get("phishing_score", 0))
                    explanation = analysis.get("explanation", "")
                    recommendation = analysis.get("recommendation", "")

                    if score >= threshold:
                        print(f"⚠️ PHISHING DETECTED ({score}) — Moving to Spam.")

                        # LOG THE EVENT
                        log_phishing_event(subject, sender, score, explanation, recommendation, body)

                        # uncomment the function as well if you want an instant response after every mail moved to spam
                        # send_warning_email(subject, score, explanation, recommendation)
                        move_to_spam(mail, eid)
                    else:
                        print(f"✅ Safe ({score}). No action.")

                mail.expunge()
                mail.logout()
            else:
                if not last_no_messages:
                    print("📭 No new messages.")
                    last_no_messages = True

        except Exception as e:
            print("❌ Error in main loop:", e)

        time.sleep(10)


if __name__ == "__main__":
    start_phishing_monitor()