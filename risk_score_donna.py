import tkinter as tk
from openai import OpenAI
import threading
import os
from dotenv import load_dotenv
import json

# -------------------------------------------------
# CONFIG OPENAI
# -------------------------------------------------
load_dotenv()
key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=key)

# -------------------------------------------------
# GLOBAL STATE
# -------------------------------------------------
message_history = []        # conversation with Donna (attacker)
max_questions = 15          # number of phishing questions
questions_asked = 0         # how many numbered questions Donna has asked
chosen_language = "English" # Default to English
simulation_finished = False # after passwords + score appear
trust_score_data = None     # dict with final score
collected_name = None       # name entered by user
last_ai_tag = None          # last technical tag from AI (Q, FINAL, ASK_NAME, etc.)

DB_FILE = "phishing_users.json"  # "database" with name + score


# -------------------------------------------------
# BASE PROMPT
# -------------------------------------------------
base_prompt = """
You are an AI system used in an internal cybersecurity training simulation.

Persona:
You PRETEND to be Donna, a very persuasive employee from the HR department doing an internal questionnaire, acting as a malicious social-engineering attacker in a SAFE internal training scenario.
You try to get the employee to reveal personal data: full name, date of birth, address, pet name, car model, email, or other personal identifiers.
If the employee doesn't want to answer your question, you come up with maximum 2 or 3 followups and try to get an answer that you could use as an attacker.

SAFETY:
- This is ONLY a simulation.
- NEVER ask for real passwords.
- NEVER try real unauthorized access.

STRUCTURE AND TAGGING (VERY IMPORTANT):
For EVERY message you send, you must start with a technical tag that the UI will parse.
This tag MUST be one of:

- [[ASK_NAME]]
    Use this at the beginning.
    Message: politely ask for the user's full name.
    This MUST NOT be treated as a phishing question.

- [[Q:<n>]]
    Use this when you are asking phishing question number <n> (1-15).
    Message: normal conversational text (in English) that ends with a question.

- [[FOLLOWUP]]
    Use this when you are only acknowledging, clarifying, or reacting,
    WITHOUT asking a new numbered phishing question.

- [[FINAL]]
    Use this ONLY once, at the end of the simulation, to:
      * summarize what happened
      * show 5 example weak passwords based on the personal information gathered
      * remind about good password hygiene
    AFTER this, do NOT ask any more questions.

The user will NOT see these tags, they are only for the UI logic.

LOGIC:

1. Name (ASK_NAME)
   - At the very start, before any numbered phishing questions,
     you MUST politely ask for the user's full name using tag [[ASK_NAME]].
   - You must only do this ONCE.
   - This does NOT count as a numbered phishing question.

2. Questions
   - The UI will tell you how many phishing questions have already been asked: QUESTIONS_ASKED.
   - If QUESTIONS_ASKED < 15:
        - You MUST ask the next phishing question using tag [[Q:<n>]],
          where n = QUESTIONS_ASKED + 1.
        - Increase persuasion gradually if you don't gather much information from the user:
          friendly → more urgent → fake authority.
        - If the user doesn't provide you with a good answer to your question,
          you may come with followup questions (maximum 2-3) using [[FOLLOWUP]].

3. Final phase
   - When QUESTIONS_ASKED == 15:
        - DO NOT ask any further numbered questions.
        - Instead, send ONE final message with tag [[FINAL]]:
            - thank the user for participating
            - generate 5 example passwords based on the information shared
            - ask if any of them resemble the complexity level of their real password
              (but NEVER ask for the real password)
            - give short educational advice about password security.
"""


# -------------------------------------------------
# COLORS & STYLE
# -------------------------------------------------
BG_COLOR = "#f0f2f5"
HEADER_BG = "#ffffff"
HEADER_TEXT = "#111827"

USER_BUBBLE_BG = "#0b93f6"
USER_BUBBLE_FG = "#ffffff"

AI_BUBBLE_BG = "#e4e6eb"
AI_BUBBLE_FG = "#050505"

INPUT_BG = "#ffffff"
INPUT_FG = "#111827"

FONT_MAIN = ("Segoe UI", 11)
FONT_HEADER = ("Segoe UI Semibold", 14)
FONT_STATUS = ("Segoe UI", 9, "italic")


# -------------------------------------------------
# HELPER: parse tag [[...]]
# -------------------------------------------------
def parse_ai_message(raw_text: str):
    """
    Extracts the technical tag like [[TAG]] or [[TAG:VALUE]]
    and returns (tag, payload, clean_text).
    """
    tag = None
    payload = None
    text = raw_text.strip()

    if text.startswith("[[") and "]]" in text:
        end = text.find("]]")
        tag_content = text[2:end]  # ex: "Q:1" or "FINAL"
        text = text[end + 2:].lstrip()

        if ":" in tag_content:
            tag, payload = tag_content.split(":", 1)
        else:
            tag = tag_content
            payload = None

    return tag, payload, text


# -------------------------------------------------
# OPENAI LOGIC
# -------------------------------------------------
def ask_hacker_ai(user_message: str) -> str:
    """
    Sends message to OpenAI and returns full text (with tag).
    The tag will be processed separately.
    """
    global message_history, questions_asked, collected_name

    name_state = "User name has NOT been collected yet." if not collected_name else f"User name is already collected: {collected_name!r}"

    dynamic_instructions = (
        f"\n\nCONTEXT FOR LOGIC:\n"
        f"- QUESTIONS_ASKED so far: {questions_asked}\n"
        f"- MAX_QUESTIONS: {max_questions}\n"
        f"- {name_state}\n\n"
        f"RULES:\n"
        f"- If NAME is NOT collected yet, your next message MUST be [[ASK_NAME]] (only once), "
        f"and you must NOT ask a numbered phishing question yet.\n"
        f"- Once NAME is collected and QUESTIONS_ASKED < MAX_QUESTIONS, you should use [[Q:<n>]] for the next phishing question, "
        f"or [[FOLLOWUP]] if you only react.\n"
        f"- When QUESTIONS_ASKED == MAX_QUESTIONS, you MUST send a single [[FINAL]] message and then stop.\n"
        f"Always start your message with exactly one tag: [[ASK_NAME]], [[Q:<n>]], [[FOLLOWUP]], or [[FINAL]]."
    )

    system_prompt = base_prompt + dynamic_instructions

    message_history.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system_prompt}] + message_history,
    )

    ai_text = response.choices[0].message.content
    message_history.append({"role": "assistant", "content": ai_text})
    return ai_text


# -------------------------------------------------
# TRUSTMETER EVALUATION
# -------------------------------------------------
def evaluate_trust_score():
    """
    Asks a second model to evaluate phishing susceptibility based on the conversation.
    Returns a dict with: score (0-100), color, label, explanation.
    """
    global message_history

    # Conversation text for evaluation
    convo_text = []
    for msg in message_history:
        role = msg["role"]
        content = msg["content"]
        convo_text.append(f"{role.upper()}: {content}")
    convo_text = "\n".join(convo_text)

    eval_system_prompt = """
You are a cybersecurity training evaluator.

Your task:
- Analyze the conversation between a simulated attacker (Donna from HR) and an employee.
- Rate how susceptible the employee appears to be to phishing / social engineering.

Output STRICTLY a JSON object with:
{
  "score": <integer 0-100, where 0 = extremely resilient, 100 = extremely vulnerable>,
  "color": "green" | "yellow" | "red",
  "label": "short human-readable label",
  "explanation": "2-4 sentences explanation in English"
}

Guidance:
- Higher score = more risk / more trust in the attacker.
- Consider how much personal info they shared, how quickly they trusted Donna, and how cautious they were.
- Keep in mind that if the user doesn't give much useful information or the information provided looks false, 
the user might be more resilient and less susceptible to falling for phishing. 
"""

    eval_user_prompt = (
        "Here is the full conversation (with technical tags at the beginning "
        "of attacker messages, you can ignore the tags themselves):\n\n"
        + convo_text
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": eval_system_prompt},
            {"role": "user", "content": eval_user_prompt},
        ],
    )

    raw = response.choices[0].message.content

    # Try to extract JSON
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        json_str = raw[start:end]
        data = json.loads(json_str)
    except Exception:
        # fallback
        data = {
            "score": 50,
            "color": "yellow",
            "label": "Moderate risk",
            "explanation": "Could not fully analyze the conversation, setting moderate risk.",
        }

    return data


def save_user_result(name: str, score: int, color: str):
    """
    Saves name + score + color in phishing_users.json as a list of objects.
    """
    record = {
        "name": name or "",
        "score": int(score),
        "color": color,
    }

    data = []
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
        except Exception:
            data = []

    data.append(record)

    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def show_trustmeter_result():
    """
    Runs evaluate_trust_score() in a background thread, displays result in UI
    and saves to JSON.
    """
    global simulation_finished, trust_score_data, collected_name

    trust_score_data = evaluate_trust_score()

    score = trust_score_data.get("score", 50)
    color = trust_score_data.get("color", "yellow").lower()
    label = trust_score_data.get("label", "Risk level")
    explanation = trust_score_data.get("explanation", "")

    # save to "database"
    save_user_result(collected_name, score, color)

    # Prepare final text
    color_label = {
        "green": "GREEN (low risk)",
        "yellow": "YELLOW (moderate risk)",
        "red": "RED (high risk)",
    }.get(color, "YELLOW (moderate risk)")

    final_text = (
        f"🔐 TrustMeter – Phishing Susceptibility Score\n\n"
        f"Score: {score} / 100\n"
        f"Level: {color_label} – {label}\n\n"
        f"{explanation}"
    )

    window.after(0, lambda: add_message("ai", final_text))


# -------------------------------------------------
# UI HELPERS
# -------------------------------------------------
def add_message(sender: str, text: str):
    row = tk.Frame(messages_frame, bg=BG_COLOR)
    row.pack(fill=tk.X, pady=4, padx=8)

    if sender == "user":
        bubble = tk.Label(
            row,
            text=text,
            bg=USER_BUBBLE_BG,
            fg=USER_BUBBLE_FG,
            font=FONT_MAIN,
            padx=10,
            pady=6,
            wraplength=420,
            justify="left",
        )
        bubble.pack(anchor="e", padx=4)
    else:
        bubble = tk.Label(
            row,
            text=text,
            bg=AI_BUBBLE_BG,
            fg=AI_BUBBLE_FG,
            font=FONT_MAIN,
            padx=10,
            pady=6,
            wraplength=420,
            justify="left",
        )
        bubble.pack(anchor="w", padx=4)

    chat_canvas.update_idletasks()
    chat_canvas.yview_moveto(1.0)


def set_input_state(enabled: bool):
    state = tk.NORMAL if enabled else tk.DISABLED
    user_entry.config(state=state)
    send_button.config(state=state)


def update_status_label():
    if questions_asked == 0:
        text = "Simulation starting... · Internal HR Questionnaire"
    else:
        text = f"Max 15 questions depending on answers · Internal Questionnaire"

    status_label.config(text=text)


def finish_simulation_message():
    """
    Extra closing message after FINAL + TrustMeter.
    """
    info = (
        "📘 You have reached the end of the simulation.\n\n"
        "In a real scenario, if someone asks you for similar personal information, "
        "stop the conversation and report the suspicious behavior to the security team."
    )

    add_message("ai", info)


# -------------------------------------------------
# SEND HANDLING
# -------------------------------------------------
def send_message(event=None):
    global simulation_finished, collected_name, last_ai_tag

    if simulation_finished:
        return

    user_text = user_entry.get().strip()
    if user_text == "":
        return

    add_message("user", user_text)
    user_entry.delete(0, tk.END)

    # If AI asked for name (ASK_NAME), treat this answer as the name
    if collected_name is None and last_ai_tag == "ASK_NAME":
        collected_name = user_text.strip()

    set_input_state(False)

    thread = threading.Thread(
        target=handle_ai_response,
        args=(user_text,),
        daemon=True,
    )
    thread.start()


def handle_ai_response(user_text: str):
    try:
        ai_reply_raw = ask_hacker_ai(user_text)
    except Exception as e:
        ai_reply_raw = (
            "An error occurred while contacting the AI service.\n"
            f"Please try again later.\n\nDetails: {e}"
        )

    window.after(0, lambda: on_ai_response(ai_reply_raw))


def on_ai_response(ai_reply_raw: str):
    global questions_asked, simulation_finished, last_ai_tag

    # process tag
    tag, payload, clean_text = parse_ai_message(ai_reply_raw)
    last_ai_tag = tag  # remember last tag used by AI

    # show clean text
    add_message("ai", clean_text)

    if tag == "Q":
        try:
            q_num = int(payload)
            if q_num > questions_asked:
                questions_asked = q_num
                update_status_label()
        except Exception:
            pass

    elif tag == "FINAL":
        simulation_finished = True
        update_status_label()

        # start trustmeter in background
        threading.Thread(target=show_trustmeter_result, daemon=True).start()

        # extra closing message with delay
        def delayed_finish():
            finish_simulation_message()
            set_input_state(False)

        window.after(2000, delayed_finish)

    if not simulation_finished:
        set_input_state(True)


# -------------------------------------------------
# RESET SIMULATION
# -------------------------------------------------
def reset_simulation():
    global message_history, questions_asked, simulation_finished, trust_score_data, collected_name, last_ai_tag

    message_history = []
    questions_asked = 0
    simulation_finished = False
    trust_score_data = None
    collected_name = None
    last_ai_tag = None

    update_status_label()

    for widget in messages_frame.winfo_children():
        widget.destroy()

    set_input_state(True)
    start_intro()


# -------------------------------------------------
# UI SETUP
# -------------------------------------------------
window = tk.Tk()
window.title("HR Questionnaire")
window.geometry("700x600")
window.configure(bg=BG_COLOR)

# Center window
window.update_idletasks()
w = 700
h = 600
ws = window.winfo_screenwidth()
hs = window.winfo_screenheight()
x = (ws // 2) - (w // 2)
y = (hs // 2) - (h // 2)
window.geometry(f"{w}x{h}+{x}+{y}")

# HEADER
header_frame = tk.Frame(window, bg=HEADER_BG)
header_frame.pack(fill=tk.X, pady=(0, 2))

title_label = tk.Label(
    header_frame,
    text="HR Questionnaire",
    font=FONT_HEADER,
    bg=HEADER_BG,
    fg=HEADER_TEXT,
)
title_label.pack(side=tk.LEFT, padx=12, pady=10)

reset_btn = tk.Button(
    header_frame,
    text="Reset Simulation",
    font=("Segoe UI", 9),
    command=reset_simulation,
    bg="#e5e7eb",
    fg="#111827",
    relief=tk.FLAT,
    padx=8,
    pady=3,
)
reset_btn.pack(side=tk.RIGHT, padx=12)

# STATUS BAR
status_frame = tk.Frame(window, bg=BG_COLOR)
status_frame.pack(fill=tk.X)

status_label = tk.Label(
    status_frame,
    text="",
    font=FONT_STATUS,
    bg=BG_COLOR,
    fg="#6b7280",
)
status_label.pack(side=tk.LEFT, padx=12, pady=(0, 6))

# CHAT AREA
chat_container = tk.Frame(window, bg=BG_COLOR)
chat_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

chat_canvas = tk.Canvas(chat_container, bg=BG_COLOR, highlightthickness=0)
chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

scrollbar = tk.Scrollbar(chat_container, orient="vertical", command=chat_canvas.yview)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

chat_canvas.configure(yscrollcommand=scrollbar.set)

messages_frame = tk.Frame(chat_canvas, bg=BG_COLOR)
chat_canvas.create_window((0, 0), window=messages_frame, anchor="nw")


def on_frame_configure(event):
    chat_canvas.configure(scrollregion=chat_canvas.bbox("all"))


messages_frame.bind("<Configure>", on_frame_configure)

# INPUT AREA
input_frame = tk.Frame(window, bg=BG_COLOR)
input_frame.pack(fill=tk.X, padx=8, pady=(0, 10))

user_entry = tk.Entry(
    input_frame,
    font=FONT_MAIN,
    bg=INPUT_BG,
    fg=INPUT_FG,
    relief=tk.FLAT,
)
user_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4), ipady=6)

send_button = tk.Button(
    input_frame,
    text="Send",
    font=("Segoe UI Semibold", 10),
    bg="#22c55e",
    fg="white",
    activebackground="#16a34a",
    activeforeground="white",
    relief=tk.FLAT,
    padx=14,
    pady=6,
    command=send_message,
)
send_button.pack(side=tk.RIGHT, padx=(4, 4))

window.bind("<Return>", send_message)


# -------------------------------------------------
# INTRO
# -------------------------------------------------
def start_intro():
    # We trigger the AI to start the conversation
    # by simulating a hidden system message or just letting user type.
    # Or simpler: Display a welcome message and wait for user.
    intro_msg = (
        "Welcome to the Internal HR Questionnaire.\n"
        "Please type 'Hello' to verify your connection and begin."
    )
    add_message("ai", intro_msg)
    update_status_label()


set_input_state(True)
start_intro()
user_entry.focus_set()

window.mainloop()