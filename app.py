from flask import Flask, render_template, jsonify
import json
import os
import time

app = Flask(__name__)

LOG_FILE = "phishing_logs.json"
HEARTBEAT_FILE = "heartbeat.txt"


def load_logs():
    if not os.path.exists(LOG_FILE): return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.sort(key=lambda x: x["timestamp"], reverse=True)
            return data
    except:
        return []


def check_agent_status():
    """Checks if agent is running (heartbeat < 30s ago)."""
    if not os.path.exists(HEARTBEAT_FILE):
        return False
    try:
        with open(HEARTBEAT_FILE, "r") as f:
            last_beat = float(f.read().strip())
        return (time.time() - last_beat) < 30
    except:
        return False


@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/api/stats')
def get_stats():
    logs = load_logs()
    total = len(logs)

    now = time.time()
    week_count = len([l for l in logs if l["timestamp"] > (now - 604800)])
    last_score = logs[0]["score"] if logs else 0

    is_active = check_agent_status()

    return jsonify({
        "total": total,
        "week": week_count,
        "last_score": last_score,
        "logs": logs,
        "status": "active" if is_active else "inactive"
    })


if __name__ == '__main__':
    print("🚀 Dashboard running on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)