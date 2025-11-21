import subprocess
import sys
import time

# Start phishing agent
agent = subprocess.Popen([sys.executable, "phishing_copilot_agent.py"])
print("🚀 Started Phishing Copilot Agent.")

# Delay just to ensure heartbeat file is created
time.sleep(2)

# Start Flask dashboard
dashboard = subprocess.Popen([sys.executable, "app.py"])
print("🌐 Started Dashboard at http://127.0.0.1:5000")

# Wait for both to finish (they won’t, they run forever)
agent.wait()
dashboard.wait()
