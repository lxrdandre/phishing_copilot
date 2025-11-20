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
# Make sure you have a .env file in the same folder with:
#   OPENAI_API_KEY=...
#   IMAP_PASS="your app password"
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
IMAP_PASS = os.getenv("IMAP_PASS")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set. Check your .env file.")
if not IMAP_PASS:
    raise RuntimeError("IMAP_PASS is not set. Check your .env file.")


# ============================================================
# USER RISK LEVEL (from TrustMeter later)
# ============================================================
# 0   = very resilient, send fewer warnings
# 100 = very vulnerable, send lots of warnings
USER_RISK_LEVEL = 65  # you can overwrite this from your Tk app later


def compute_threshold(user_risk: int) -> int:
    """
    For low-risk users, send warnings only for high phishing_score.
    For high-risk users, be more aggressive.
    """
    if user_risk <= 20:
        return 70  # only very suspicious emails trigger warnings
    elif user_risk <= 60:
        return 50  # medium sensitivity
    else:
        return 30  # high sensitivity: warn even on mildly suspicious emails


# ============================================================
# EMAIL CONFIG (Gmail)
# ============================================================
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "degatmor2@gmail.com"

SMTP_HOST = "smtp.gmail.com"
SMTP_USER = "degatmor2@gmail.com"
SMTP_PASS = IMAP_PASS  # same app password

# Where to send the warning emails
WARNING_RECIPIENT = "degatmor2@gmail.com"


# ============================================================
# OPENAI AGENT (PHISHING COPILOT)
# ============================================================
# Agents SDK will use OPENAI_API_KEY from env. :contentReference[oaicite:0]{index=0}
phishing_agent = Agent(
    name="Phishing Copilot",
    instructions=(
        "You are a phishing detection AI.\n\n"
        "You analyze an email (subject + body) and you MUST respond with ONLY a single JSON object:\n"
        "{\n"
        '  "phishing_score": <integer 0-100>,\n'
        '  "explanation": "why this is suspicious or safe",\n'
        '  "recommendation": "what the user should do"\n'
        "}\n\n"
        "Guidance:\n"
        "- Consider urgency, threats, emotional manipulation, unknown senders, suspicious URLs, mismatched domains.\n"
        "- 0-30 = probably safe\n"
        "- 31-70 = suspicious\n"
        "- 71-100 = likely phishing.\n"
        "- You will also be told USER_RISK (0-100). If USER_RISK is high (80+), "
        "treat borderline emails more aggressively when assigning phishing_score.\n"
        "DO NOT output anything except the JSON object. No prose, no backticks."
    ),
)


def analyze_email_with_agent(subject: str, body: str, user_risk: int) -> dict:
    """
    Call the Agents SDK synchronously and parse the JSON response.
    Returns a dict with phishing_score, explanation, recommendation.
    """
    if subject is None:
        subject = "(no subject)"

    if body is None:
        body = ""

    prompt = f"""
USER_RISK={user_risk}

Analyze the following email and respond ONLY with a JSON object as specified.

EMAIL:
Subject: {subject}
Body:
{body}
"""

    # Run the agent synchronously
    result = Runner.run_sync(phishing_agent, prompt)
    raw_output = result.final_output  # string

    # Try to parse JSON robustly
    try:
        # Sometimes models may accidentally wrap JSON with text, so we try to find the JSON block
        start = raw_output.index("{")
        end = raw_output.rindex("}") + 1
        json_str = raw_output[start:end]
        data = json.loads(json_str)
    except Exception as e:
        print("❌ Could not parse JSON from agent output. Raw output:")
        print(raw_output)
        print("Error:", e)
        # Fallback minimal structure
        data = {
            "phishing_score": 0,
            "explanation": "Failed to parse agent output; assuming safe.",
            "recommendation": "No action.",
        }

    return data


# ============================================================
# FUNCTION: SEND WARNING EMAIL
# ============================================================
def send_warning_email(original_subject: str, score: int, explanation: str, recommendation: str):
    text = (
        "⚠️ Possible phishing attempt detected!\n\n"
        f"Subject: {original_subject}\n"
        f"Risk Score: {score} / 100\n\n"
        f"Explanation:\n{explanation}\n\n"
        f"Recommendation:\n{recommendation}\n\n"
        "Stay safe!"
    )

    msg = MIMEText(text)
    msg["From"] = SMTP_USER
    msg["To"] = WARNING_RECIPIENT
    msg["Subject"] = f"[WARNING] Suspicious Email Detected ({score}/100)"

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=context) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [WARNING_RECIPIENT], msg.as_string())


# ============================================================
# FUNCTION: FETCH UNREAD EMAILS VIA IMAP
# ============================================================
def fetch_unread_emails():
    """
    Returns a list of dicts: { 'subject': str, 'body': str }
    """
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(IMAP_USER, IMAP_PASS)
    mail.select("inbox")

    status, messages = mail.search(None, "UNSEEN")
    if status != "OK":
        print("❌ Failed to search inbox.")
        mail.logout()
        return []

    email_ids = messages[0].split()
    emails = []

    for eid in email_ids:
        status, msg_data = mail.fetch(eid, "(RFC822)")
        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        # =====================================================
        # 🚫 SKIP EMAILS SENT BY YOURSELF (prevents self-scanning)
        # =====================================================
        from_addr = msg.get("From", "").lower()
        if IMAP_USER.lower() in from_addr:
            print("⏭️ Skipping self-generated email:", from_addr)
            continue
        # =====================================================

        # Decode subject safely
        raw_subject = msg["Subject"]
        if raw_subject:
            subject_decoded, enc = decode_header(raw_subject)[0]
            if isinstance(subject_decoded, bytes):
                subject = subject_decoded.decode(enc or "utf-8", errors="ignore")
            else:
                subject = subject_decoded
        else:
            subject = "(no subject)"

        # Extract body (text/plain)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition") or "")
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body_bytes = part.get_payload(decode=True)
                        if body_bytes:
                            body = body_bytes.decode(errors="ignore")
                            break
                    except Exception:
                        continue
        else:
            try:
                body_bytes = msg.get_payload(decode=True)
                if body_bytes:
                    body = body_bytes.decode(errors="ignore")
            except Exception:
                body = ""

        emails.append({"subject": subject, "body": body})

    mail.logout()
    return emails


# ============================================================
# MAIN LOOP
# ============================================================
def start_phishing_monitor():
    print("📡 Phishing Copilot (Agents SDK) started. Monitoring inbox...")
    print(f"User risk level: {USER_RISK_LEVEL}")
    threshold = compute_threshold(USER_RISK_LEVEL)
    print(f"Current warning threshold: phishing_score >= {threshold}")

    while True:
        try:
            unread = fetch_unread_emails()

            if unread:
                print(f"📥 Found {len(unread)} new email(s).")

            for email_data in unread:
                subject = email_data["subject"]
                body = email_data["body"]

                print(f"\n🔍 Analyzing email: {subject}")

                analysis = analyze_email_with_agent(subject, body, USER_RISK_LEVEL)
                score = int(analysis.get("phishing_score", 0))
                explanation = analysis.get("explanation", "")
                recommendation = analysis.get("recommendation", "")

                print(f"   → phishing_score = {score}")
                print(f"   → explanation: {explanation[:120]}...")

                if score >= threshold:
                    print(f"⚠️ Suspicious (>= {threshold}). Sending warning email.")
                    send_warning_email(subject, score, explanation, recommendation)
                else:
                    print(f"✅ Below threshold ({threshold}). No warning sent.")

        except Exception as e:
            print("❌ Error in monitor loop:", e)

        # Check every 5 seconds (adjust as you like)
        time.sleep(5)


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    start_phishing_monitor()
