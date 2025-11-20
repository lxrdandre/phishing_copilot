🛡️ Phishing Copilot & Social Engineering Trainer - made by me and my friend [David](https://github.com/davidd234) at a hackathon

A comprehensive cybersecurity suite designed to assess user vulnerability via simulation and protect their inbox using an AI-powered monitoring agent.

📂 Project Overview

This solution consists of three integrated components:

The "Donna" Simulator (Assessment): A social engineering training tool where an AI persona ("Donna from HR") attempts to extract sensitive information from the user. It calculates a Risk Score (0-100) based on how much information the user reveals.

Phishing Copilot Agent (Protection): A background service that monitors an IMAP inbox 24/7. It analyzes incoming emails using GPT-4o, detects phishing attempts, moves them to Spam, and creates a log. It adjusts its sensitivity based on the user's Risk Score.

Live Dashboard (Monitoring): A Flask-based web interface to visualize blocked threats, view logs, and check system status in real-time.

🚀 Features

🎭 Social Engineering Simulator (risk_score_donna.py)

Interactive Chat: Real-time conversation with an AI attacker using Tkinter.

Dynamic Tactic: The AI adjusts its persuasion techniques (friendly, urgent, authoritative).

TrustMeter: A secondary AI model analyzes the chat to calculate a final vulnerability score.

Educational Feedback: Provides examples of weak passwords based on revealed data at the end.

📡 Phishing Copilot Agent (phishing_copilot_agent.py)

Adaptive Security: Uses the score from the Simulator to set the blocking threshold (High Risk User = Stricter Filtering).

Auto-Remediation: Automatically moves detected phishing emails to the Spam folder.

Weekly Reports: Sends a summary email every 7 days with statistics.

Heartbeat System: Updates a status file to let the dashboard know the service is alive.

📊 Web Dashboard (app.py)
<img width="1136" height="601" alt="Screenshot 2025-11-20 at 23 42 53" src="https://github.com/user-attachments/assets/b0c2d243-7c3b-402a-b858-65ebd79a8597" />

Live Monitoring: Shows total threats blocked and weekly stats.

System Health: Displays "System Active" or "Inactive" based on agent heartbeat.

Detailed Logs: View subject lines, risk scores, and AI explanations for every blocked email.

Dark Mode UI: Built with Tailwind CSS.

🛠️ Installation

1. Clone the repository

2. Install Dependencies

pip install -r requirements.txt

3. Environment Configuration

Create a .env file in the root directory and add your credentials:

# .env file
OPENAI_API_KEY="sk-proj-..."
IMAP_PASS="your-gmail-app-password"


Note: For Gmail, IMAP_PASS is your App Password, not your login password.

🖥️ Usage Guide

Step 1: Run the Assessment (Optional)

Run the simulator to generate your baseline risk score. This creates phishing_users.json.

python risk_score_donna.py


Step 2: Start the Protection Agent

This script must run in the background to monitor emails.

python phishing_copilot_agent.py


Output: "📡 Phishing Copilot started..."

Step 3: Launch the Dashboard

Open a new terminal window and run the web server.

python app.py


⚠️ Disclaimer

Educational Use Only.
This tool is designed for internal security training and personal inbox protection.

Do not use the "Donna" simulator to target individuals without consent.

Ensure you have authorization to monitor the email inbox provided in the configuration.

The developers are not responsible for any misuse of this software.

🤝 Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Presentation
https://gamma.app/docs/Dont-Get-Hooked-Your-Personal-Anti-Phishing-Guardian-1yiuu6mistit61d
