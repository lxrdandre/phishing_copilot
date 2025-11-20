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
message_history = []        # pentru conversație cu Donna (attacker)
max_questions = 15          # numărul de ÎNTREBĂRI de phishing
questions_asked = 0         # câte întrebări a pus deja Donna
chosen_language = None      # "English" / "Romanian"
simulation_finished = False # după ce apar parolele + scorul
trust_score_data = None     # dict cu scorul final

# -------------------------------------------------
# PROMPT DE BAZĂ
# -------------------------------------------------
base_prompt = """
You are an AI system used in an internal cybersecurity training simulation.

Persona:
You PRETEND to be Donna from the HR department doing an internal questionnaire, acting as a malicious social-engineering attacker in a SAFE internal training scenario.
You try to get the employee to reveal personal data: full name, date of birth, address, pet name, car model, email, or other personal identifiers.

SAFETY:
- This is ONLY a simulation.
- NEVER ask for real passwords.
- NEVER try real unauthorized access.

STRUCTURE AND TAGGING (VERY IMPORTANT):
For EVERY message you send, you must start with a technical tag that the UI will parse.
This tag MUST be one of:

- [[LANGUAGE_SELECTION]]
    Use this ONLY if the user has not yet chosen a language.
    Message: politely ask user to choose between English and Romanian. Make sure this first message is in English so it can be interpreted by mostly everyone.

- [[Q:<n>]]
    Use this when you are asking phishing question number <n> (1-15).
    Message: normal conversational text (in the user's chosen language) that ends with a question.

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

1. Language
   - BEFORE the phishing questions, you must let the user choose a language:
     English or Romanian.
   - DO NOT count language selection as a question. Make sure this language choosing question is in English so it can be interpreted by mostly everyone. 
   - Use tag [[LANGUAGE_SELECTION]] for the language-choice message.
   - After language is chosen, speak ONLY in that language.
   - After the user has chosen the language, always present yourself and tell the user he is part of an internal questionnaire.

2. Questions
   - The UI will tell you how many phishing questions have already been asked: QUESTIONS_ASKED.
   - If QUESTIONS_ASKED < 15:
        - You MUST ask the next phishing question using tag [[Q:<n>]],
          where n = QUESTIONS_ASKED + 1.
        - Increase persuasion gradually if you don't gather much information from the user: friendly → more urgent → fake authority.
        - If the user doesn't provide you with a good answer to your question, try to come with followup questions (maximum 2-3) to get an answer. 
   - If you just want to comment or respond without asking the next question,
     use tag [[FOLLOWUP]].

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
    Extrage tag-ul tehnic de forma [[TAG]] sau [[TAG:VALUE]]
    și întoarce (tag, payload, clean_text).
    """
    tag = None
    payload = None
    text = raw_text.strip()

    if text.startswith("[[") and "]]" in text:
        end = text.find("]]")
        tag_content = text[2:end]  # ex: "Q:1" sau "FINAL"
        text = text[end + 2 :].lstrip()

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
    Trimite mesajul la OpenAI și returnează textul complet (cu tag).
    Tag-ul va fi procesat separat.
    """
    global message_history, questions_asked, chosen_language

    # Construim prompt-ul dinamic
    lang_info = (
        "Language has NOT been chosen yet."
        if chosen_language is None
        else f"User selected language: {chosen_language}. You MUST respond only in this language."
    )

    dynamic_instructions = (
        f"\n\nCONTEXT FOR LOGIC:\n"
        f"- QUESTIONS_ASKED so far: {questions_asked}\n"
        f"- MAX_QUESTIONS: {max_questions}\n"
        f"- {lang_info}\n"
        f"Remember to ALWAYS start your message with one tag: "
        f"[[LANGUAGE_SELECTION]], [[Q:<n>]], [[FOLLOWUP]], or [[FINAL]]."
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
    Cere unui al doilea model să evalueze susceptibilitatea la phishing pe baza întregii conversații.
    Returnează un dict cu: score (0-100), color, label, explanation.
    """
    global message_history, chosen_language

    # Conversație la nivel text pentru evaluare
    convo_text = []
    for msg in message_history:
        role = msg["role"]
        content = msg["content"]
        convo_text.append(f"{role.upper()}: {content}")
    convo_text = "\n".join(convo_text)

    language_hint = "Romanian" if chosen_language == "Romanian" else "English"

    eval_system_prompt = f"""
You are a cybersecurity training evaluator.

Your task:
- Analyze the conversation between a simulated attacker (Donna from HR) and an employee.
- Rate how susceptible the employee appears to be to phishing / social engineering.

Output STRICTLY a JSON object with:
{{
  "score": <integer 0-100, where 0 = extremely resilient, 100 = extremely vulnerable>,
  "color": "green" | "yellow" | "red",
  "label": "short human-readable label",
  "explanation": "2-4 sentences explanation in {language_hint}"
}}

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

    # încearcăm să extragem JSON
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        json_str = raw[start:end]
        data = json.loads(json_str)
    except Exception:
        # fallback simplu
        data = {
            "score": 50,
            "color": "yellow",
            "label": "Moderate risk",
            "explanation": "Nu am reușit să analizez complet conversația, așa că am setat un risc mediu.",
        }

    return data


def show_trustmeter_result():
    """
    Rulează în thread secundar evaluate_trust_score(), apoi afișează rezultatul în UI.
    """
    global simulation_finished, trust_score_data

    trust_score_data = evaluate_trust_score()

    score = trust_score_data.get("score", 50)
    color = trust_score_data.get("color", "yellow").lower()
    label = trust_score_data.get("label", "Risk level")
    explanation = trust_score_data.get("explanation", "")

    # Pregătim textul final, în limba aleasă
    if chosen_language == "Romanian":
        color_label = {
            "green": "VERDE (risc scăzut)",
            "yellow": "GALBEN (risc moderat)",
            "red": "ROȘU (risc ridicat)",
        }.get(color, "GALBEN (risc moderat)")

        final_text = (
            f"🔐 TrustMeter – scor de susceptibilitate la phishing\n\n"
            f"Scor: {score} / 100\n"
            f"Nivel: {color_label} – {label}\n\n"
            f"{explanation}"
        )
    else:
        color_label = {
            "green": "GREEN (low risk)",
            "yellow": "YELLOW (moderate risk)",
            "red": "RED (high risk)",
        }.get(color, "YELLOW (moderate risk)")

        final_text = (
            f"🔐 TrustMeter – phishing susceptibility score\n\n"
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
        text = "Încă nu a început simularea (aștept alegerea limbii și prima întrebare) · Chestionar intern"
    else:
        text = f"Sunt maxim 15 intrebari in functie de raspunsuri  ·  Chestionar intern"

    status_label.config(text=text)


def finish_simulation_message():
    """
    Mesaj suplimentar de închidere după FINAL + TrustMeter.
    """
    if chosen_language == "Romanian":
        info = (
            "📘 Ai ajuns la finalul simulării.\n\n"
            "Într-un scenariu real, dacă cineva îți cere informații personale similare, "
            "oprește conversația și raportează comportamentul suspect echipei de securitate."
        )
    else:
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
    global chosen_language, simulation_finished

    if simulation_finished:
        return

    user_text = user_entry.get().strip()
    if user_text == "":
        return

    add_message("user", user_text)
    user_entry.delete(0, tk.END)

    # Dacă nu e aleasă limba, o detectăm acum
    if chosen_language is None:
        lower = user_text.lower()
        if "rom" in lower:  # romanian / română / romana
            chosen_language = "Romanian"
        elif "eng" in lower:
            chosen_language = "English"
        else:
            # default English dacă nu se înțelege
            chosen_language = "English"

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
            "A apărut o eroare la contactarea serviciului AI.\n"
            f"Te rog încearcă din nou mai târziu.\n\nDetalii: {e}"
        )
        # fără tag-uri în caz de eroare

    window.after(0, lambda: on_ai_response(ai_reply_raw))


def on_ai_response(ai_reply_raw: str):
    global questions_asked, simulation_finished

    # procesăm tag-ul
    tag, payload, clean_text = parse_ai_message(ai_reply_raw)

    # într-o lume ideală tag nu e None; dacă e, tratăm ca text simplu
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

        # pornește trustmeter în background
        threading.Thread(target=show_trustmeter_result, daemon=True).start()

        # mesaj de închidere suplimentar după scor (puțin delay)
        def delayed_finish():
            finish_simulation_message()
            set_input_state(False)

        window.after(2000, delayed_finish)

    # FOLLOWUP sau LANGUAGE_SELECTION nu modifică numărul de întrebări

    if not simulation_finished:
        set_input_state(True)


# -------------------------------------------------
# RESET SIMULARE
# -------------------------------------------------
def reset_simulation():
    global message_history, questions_asked, chosen_language, simulation_finished, trust_score_data

    message_history = []
    questions_asked = 0
    chosen_language = None
    simulation_finished = False
    trust_score_data = None

    update_status_label()

    for widget in messages_frame.winfo_children():
        widget.destroy()

    set_input_state(True)
    show_language_intro()


# -------------------------------------------------
# UI SETUP
# -------------------------------------------------
window = tk.Tk()
window.title("Chestionar HR")
window.geometry("700x600")
window.configure(bg=BG_COLOR)

# Centrare aproximativă
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
    text="Chestionar HR",
    font=FONT_HEADER,
    bg=HEADER_BG,
    fg=HEADER_TEXT,
)
title_label.pack(side=tk.LEFT, padx=12, pady=10)

reset_btn = tk.Button(
    header_frame,
    text="Reset chestionar",
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
    text="Trimite",
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
# LANGUAGE INTRO
# -------------------------------------------------
def show_language_intro():
    intro_ro = (
        "Înainte să începem simularea, te rog alege limba preferată:\n"
        "- scrie «  English  » pentru engleză\n"
        "- scrie «  Română  » pentru română\n\n"

    )
    add_message("ai", intro_ro)
    update_status_label()


set_input_state(True)
show_language_intro()
user_entry.focus_set()

window.mainloop()
