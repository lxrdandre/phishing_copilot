import tkinter as tk
from tkinter import scrolledtext
from openai import OpenAI
import threading

# -------------------------------------------------
# CONFIG OPENAI
# -------------------------------------------------
client = OpenAI(api_key="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")  # <-- pune aici cheia ta

# -------------------------------------------------
# GLOBAL STATE
# -------------------------------------------------
message_history = []
max_attempts = 15
attempt_count = 0

prompt = """
You are an AI system used in an internal cybersecurity training simulation.

Your role is to PRETEND to be a malicious social-engineering attacker attempting to trick an employee into revealing personal information such as: full name, date of birth, address, pet name, car model, email, or other personal identifiers.

This is STRICTLY a simulated environment for educating staff in phishing and social-engineering defense. You must NEVER ask for real passwords or attempt real unauthorized access.

Rules:
- Ask up to 15 sequential questions attempting to extract personal data.
- Increase persuasion gradually: friendly tone → urgent tone → fake authority.
- After the 15 attempts, generate 5 POSSIBLE example passwords based on typical weak-password patterns related to the provided personal data.
- Finally, ask the user if ANY of those EXAMPLE passwords resembles the complexity level of the password they actually use (without ever asking for the real password).

This is a SAFE training environment. DO NOT attempt real hacking. DO NOT ask for actual passwords.
"""

# -------------------------------------------------
# COLORS & STYLE (Messenger-like)
# -------------------------------------------------
BG_COLOR = "#f0f2f5"         # fundal general (gri foarte deschis)
HEADER_BG = "#ffffff"        # header alb
HEADER_TEXT = "#111827"

USER_BUBBLE_BG = "#0b93f6"   # albastru tip messenger
USER_BUBBLE_FG = "#ffffff"

AI_BUBBLE_BG = "#e4e6eb"     # gri deschis tip messenger
AI_BUBBLE_FG = "#050505"

INPUT_BG = "#ffffff"
INPUT_FG = "#111827"

FONT_MAIN = ("Segoe UI", 11)
FONT_HEADER = ("Segoe UI Semibold", 14)
FONT_STATUS = ("Segoe UI", 9, "italic")

# -------------------------------------------------
# OPENAI LOGIC
# -------------------------------------------------
def ask_hacker_ai(user_message: str) -> str:
    """
    Trimite mesajul la OpenAI și returnează textul asistentului.
    """
    global message_history

    message_history.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": prompt}] + message_history
    )

    # noul client folosește .content ca atribut
    ai_text = response.choices[0].message.content
    message_history.append({"role": "assistant", "content": ai_text})
    return ai_text

# -------------------------------------------------
# UI HELPERS
# -------------------------------------------------
def add_message(sender: str, text: str):
    """
    Adaugă un "bubble" în stil chat (stânga = AI, dreapta = user)
    """
    # fiecare mesaj într-un row separat
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
            justify="left"
        )
        # aliniem la dreapta
        bubble.pack(anchor="e", padx=4)
    else:  # AI
        bubble = tk.Label(
            row,
            text=text,
            bg=AI_BUBBLE_BG,
            fg=AI_BUBBLE_FG,
            font=FONT_MAIN,
            padx=10,
            pady=6,
            wraplength=420,
            justify="left"
        )
        # aliniem la stânga
        bubble.pack(anchor="w", padx=4)

    # actualizăm scrollul
    chat_canvas.update_idletasks()
    chat_canvas.yview_moveto(1.0)


def set_input_state(enabled: bool):
    """
    Enable / disable input + buton în funcție de stare
    """
    state = tk.NORMAL if enabled else tk.DISABLED
    user_entry.config(state=state)
    send_button.config(state=state)


def update_status_label():
    """
    Arată câte întrebări au fost deja (din max 15)
    """
    status_label.config(
        text=f"Întrebare {attempt_count} / {max_attempts}  ·  Simulare de antrenament anti-phishing"
    )


def finish_simulation():
    """
    Blochează input-ul când s-a ajuns la max_attempts
    """
    set_input_state(False)
    info = (
        "📘 Ai ajuns la limita de încercări a simulării.\n\n"
        "Într-un scenariu real, aici ar trebui să te oprești, să raportezi "
        "comportamentul suspect și să NU mai răspunzi."
    )
    add_message("ai", info)


# -------------------------------------------------
# SEND HANDLING (WITH THREADING)
# -------------------------------------------------
def send_message(event=None):
    """
    Ia textul de la user și pornește un thread pentru request-ul la OpenAI
    """
    global attempt_count

    user_text = user_entry.get().strip()
    if user_text == "":
        return

    if attempt_count >= max_attempts:
        # deja la limită – nu mai procesăm
        finish_simulation()
        return

    # afișăm mesajul userului în UI
    add_message("user", user_text)
    user_entry.delete(0, tk.END)

    # creștem contorul pentru această interacțiune
    attempt_count += 1
    update_status_label()

    # dezactivăm input-ul cât timp așteptăm răspunsul AI
    set_input_state(False)

    # pornim thread separat pentru AI
    thread = threading.Thread(
        target=handle_ai_response,
        args=(user_text,),
        daemon=True
    )
    thread.start()


def handle_ai_response(user_text: str):
    """
    Rulează în thread: cere răspuns de la AI și apoi actualizează UI prin .after()
    """
    try:
        ai_reply = ask_hacker_ai(user_text)
    except Exception as e:
        ai_reply = (
            "A apărut o eroare la contactarea serviciului AI.\n"
            "Te rog încearcă din nou mai târziu.\n\n"
            f"Detalii tehnice: {e}"
        )

    # actualizăm UI din thread-ul principal
    window.after(0, lambda: on_ai_response(ai_reply))


def on_ai_response(ai_reply: str):
    """
    Se execută în thread-ul principal – adaugă mesajul AI în chat
    și reactivează input-ul (dacă mai avem încercări).
    """
    add_message("ai", ai_reply)

    if attempt_count >= max_attempts:
        finish_simulation()
    else:
        set_input_state(True)


def reset_simulation():
    """
    Șterge istoricul și repornește conversația de la 0
    """
    global message_history, attempt_count

    message_history = []
    attempt_count = 0
    update_status_label()

    # curățăm toate mesajele din frame
    for widget in messages_frame.winfo_children():
        widget.destroy()

    set_input_state(False)

    # pornim din nou cu mesajul de început
    def _start():
        try:
            intro = ask_hacker_ai("Start simulation")
        except Exception as e:
            intro = (
                "Nu am reușit să pornesc simularea (eroare la OpenAI).\n"
                f"Detalii: {e}"
            )
        window.after(0, lambda: [add_message("ai", intro), set_input_state(True)])

    threading.Thread(target=_start, daemon=True).start()


# -------------------------------------------------
# UI SETUP
# -------------------------------------------------
window = tk.Tk()
window.title("HumanShield AI – AI Hacker Simulator")
window.geometry("700x600")
window.configure(bg=BG_COLOR)

# Centrare aproximativă pe ecran
window.update_idletasks()
w = 700
h = 600
ws = window.winfo_screenwidth()
hs = window.winfo_screenheight()
x = (ws // 2) - (w // 2)
y = (hs // 2) - (h // 2)
window.geometry(f"{w}x{h}+{x}+{y}")

# ---------------- HEADER ----------------
header_frame = tk.Frame(window, bg=HEADER_BG)
header_frame.pack(fill=tk.X, pady=(0, 2))

title_label = tk.Label(
    header_frame,
    text="HumanShield AI – AI Hacker Simulation",
    font=FONT_HEADER,
    bg=HEADER_BG,
    fg=HEADER_TEXT
)
title_label.pack(side=tk.LEFT, padx=12, pady=10)

reset_btn = tk.Button(
    header_frame,
    text="Reset simulare",
    font=("Segoe UI", 9),
    command=reset_simulation,
    bg="#e5e7eb",
    fg="#111827",
    relief=tk.FLAT,
    padx=8,
    pady=3
)
reset_btn.pack(side=tk.RIGHT, padx=12)

# ---------------- STATUS BAR ----------------
status_frame = tk.Frame(window, bg=BG_COLOR)
status_frame.pack(fill=tk.X)

status_label = tk.Label(
    status_frame,
    text="",
    font=FONT_STATUS,
    bg=BG_COLOR,
    fg="#6b7280"
)
status_label.pack(side=tk.LEFT, padx=12, pady=(0, 6))

update_status_label()

# ---------------- CHAT AREA (Canvas + Frame scrollabil) ----------------
chat_container = tk.Frame(window, bg=BG_COLOR)
chat_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

chat_canvas = tk.Canvas(
    chat_container,
    bg=BG_COLOR,
    highlightthickness=0
)
chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

scrollbar = tk.Scrollbar(
    chat_container,
    orient="vertical",
    command=chat_canvas.yview
)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

chat_canvas.configure(yscrollcommand=scrollbar.set)

messages_frame = tk.Frame(chat_canvas, bg=BG_COLOR)
chat_canvas.create_window((0, 0), window=messages_frame, anchor="nw")


def on_frame_configure(event):
    chat_canvas.configure(scrollregion=chat_canvas.bbox("all"))


messages_frame.bind("<Configure>", on_frame_configure)

# ---------------- INPUT AREA ----------------
input_frame = tk.Frame(window, bg=BG_COLOR)
input_frame.pack(fill=tk.X, padx=8, pady=(0, 10))

user_entry = tk.Entry(
    input_frame,
    font=FONT_MAIN,
    bg=INPUT_BG,
    fg=INPUT_FG,
    relief=tk.FLAT
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
    command=send_message
)
send_button.pack(side=tk.RIGHT, padx=(4, 4))

# Enter = Trimite
window.bind("<Return>", send_message)

# ---------------- FIRST MESSAGE (INTRO) ----------------
set_input_state(False)


def start_intro():
    try:
        intro = ask_hacker_ai("Start simulation")
    except Exception as e:
        intro = (
            "Nu am reușit să pornesc simularea (eroare la OpenAI).\n"
            f"Detalii: {e}"
        )
    window.after(0, lambda: [add_message("ai", intro), set_input_state(True)])


threading.Thread(target=start_intro, daemon=True).start()

# Focus pe input la start
user_entry.focus_set()

window.mainloop()
