import imaplib
import email
import smtplib
import ssl
import time
import os
import json
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
# LOAD USER RISK LEVEL
# ============================================================
def load_user_risk():
    """Load score from phishing_users.json"""
    try:
        with open("phishing_users.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            if len(data) == 0:
                return 50
            return int(data[0].get("score", 50))
    except Exception as e:
        print("⚠️ Could not read phishing_users.json → using default risk 50.")
        print("Error:", e)
        return 50


USER_RISK_LEVEL = load_user_risk()


def compute_threshold(user_risk: int) -> int:
    """Risk-based threshold"""
    if user_risk <= 20:
        return 70
    elif user_risk <= 60:
        return 55
    else:
        return 41


# ============================================================
# EMAIL CONFIG (Gmail)
# ============================================================
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "degatmor2@gmail.com"

SMTP_HOST = "smtp.gmail.com"
SMTP_USER = "degatmor2@gmail.com"
SMTP_PASS = IMAP_PASS

WARNING_RECIPIENT = "degatmor2@gmail.com"


# ============================================================
# OPENAI AGENT (PHISHING COPILOT)
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
        "Do NOT output anything except JSON. No backticks."
    ),
)


def analyze_email_with_agent(subject: str, body: str, user_risk: int):
    """Runs the agent and extracts JSON"""
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
        print("Raw output:", raw)
        return {
            "phishing_score": 0,
            "explanation": "Parsing failed.",
            "recommendation": "None.",
        }


# ============================================================
# MOVE PHISHING EMAIL TO SPAM
# ============================================================
def move_to_spam(mail, email_id):
    try:
        mail.store(email_id, '+X-GM-LABELS', '\\Spam')
        mail.store(email_id, '+FLAGS', '\\Deleted')
        print("🗑️ Email successfully moved to Spam + flagged deleted.")
    except Exception as e:
        print("⚠️ Could not move email to spam:", e)


# ============================================================
# SEND WARNING EMAIL
# ============================================================
def send_warning_email(original_subject, score, explanation, recommendation):
    text = (
        "⚠️ Phishing attempt detected!\n\n"
        f"Subject: {original_subject}\n"
        f"Risk Score: {score}/100\n\n"
        f"Explanation:\n{explanation}\n\n"
        f"Recommendation:\n{recommendation}\n\n"
        "The original phishing email has been moved to Spam and deleted."
    )

    msg = MIMEText(text)
    msg["From"] = SMTP_USER
    msg["To"] = WARNING_RECIPIENT
    msg["Subject"] = f"[WARNING] Phishing Email Deleted ({score}/100)"

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ctx) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, WARNING_RECIPIENT, msg.as_string())


# ============================================================
# FETCH UNREAD EMAILS
# ============================================================
def fetch_unread_emails():
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(IMAP_USER, IMAP_PASS)
    mail.select("inbox")

    status, data = mail.search(None, "UNSEEN")
    if status != "OK":
        print("❌ Could not search inbox.")
        return [], None

    ids = data[0].split()
    emails = []

    for eid in ids:
        _, msg_data = mail.fetch(eid, "(RFC822)")
        if not msg_data:
            continue

        msg = email.message_from_bytes(msg_data[0][1])

        from_addr = msg.get("From", "").lower()
        if IMAP_USER.lower() in from_addr:
            print("⏭️ Skipping self-generated email:", from_addr)
            continue

        raw_subj = msg["Subject"]
        if raw_subj:
            s_raw, enc = decode_header(raw_subj)[0]
            subject = (
                s_raw.decode(enc or "utf-8", errors="ignore")
                if isinstance(s_raw, bytes)
                else s_raw
            )
        else:
            subject = "(no subject)"

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

        emails.append({"id": eid, "subject": subject, "body": body})

    return emails, mail


# ============================================================
# MAIN LOOP
# ============================================================
last_no_messages = False

def start_phishing_monitor():
    global last_no_messages

    print("📡 Phishing Copilot started.")
    print(f"User risk level: {USER_RISK_LEVEL}")
    threshold = compute_threshold(USER_RISK_LEVEL)
    print(f"Warning threshold: phishing_score >= {threshold}")

    while True:
        try:
            unread, mail = fetch_unread_emails()

            if unread:
                last_no_messages = False
                print(f"\n📥 {len(unread)} new email(s).")

                for em in unread:
                    subject = em["subject"]
                    body = em["body"]
                    eid = em["id"]

                    print(f"\n🔍 Analyzing: {subject}")

                    analysis = analyze_email_with_agent(subject, body, USER_RISK_LEVEL)
                    score = int(analysis.get("phishing_score", 0))
                    explanation = analysis.get("explanation", "")
                    recommendation = analysis.get("recommendation", "")

                    print(f"   → phishing_score = {score}")

                    if score >= threshold:
                        print("⚠️ PHISHING DETECTED — deleting + warning email")
                        send_warning_email(subject, score, explanation, recommendation)
                        move_to_spam(mail, eid)
                    else:
                        print("✅ Safe. No action.")

                mail.expunge()
                mail.logout()

            else:
                if not last_no_messages:
                    print("📭 No new messages.")
                    last_no_messages = True

        except Exception as e:
            print("❌ Error:", e)

        time.sleep(5)


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    start_phishing_monitor()

