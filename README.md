# NeuroTrace 🧠

NeuroTrace is a modern, real-time productivity and activity tracking system. It consists of a **Chrome Extension (Manifest V3)** that silently monitors your active tabs and a **Django ASGI Backend** that processes, categorizes, and displays your activity in a beautiful, real-time dashboard.

![NeuroTrace Dashboard UI]() <!-- Add a screenshot link here before pushing to GitHub! -->

## Features 🚀

- **Real-Time Live Tracking:** Watch your activity stream update instantly on your dashboard via WebSockets.
- **Smart Categorization:** Automatically classifies websites as **Productive**, **Distracting**, or **Neutral** to give you an accurate Focus Index.
- **Accurate Duration Metrics:** Utilizes event-driven `page_enter` and `page_exit` markers rather than polling, ensuring pixel-perfect time tracking.
- **Intelligent AFK Detection:** Automatically detects when you step away from your computer (idle > 60s) or lock your screen, pausing the timer so your metrics remain perfectly accurate.
- **Secure Multi-User Accounts:** Features a modern glassmorphism login system, allowing multiple users to track their activity on the same server, with the Chrome extension syncing directly via secure session cookies.
- **Auto-Healing Extension:** The background script automatically recovers from server restarts and ensures no data is dropped.

## Tech Stack 🛠

**Backend:**
- Python 3
- Django 4.2
- Django REST Framework
- Django Channels (WebSockets)
- Daphne (ASGI Server)
- SQLite (Local) / PostgreSQL (Production ready)

**Frontend & Extension:**
- Vanilla JavaScript
- Chrome Extension API (Manifest V3)
- HTML5 / Vanilla CSS (Modern Glassmorphism UI)
- Chart.js

---

## Installation & Setup 💻

### 1. Backend Setup

First, clone the repository and set up a Python virtual environment:

```bash
git clone https://github.com/YourUsername/NeuroTrace.git
cd NeuroTrace
python -m venv venv

# Activate the virtual environment:
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate
```

Install the dependencies:
```bash
pip install -r requirements.txt
```

Run the database migrations:
```bash
python manage.py migrate
```

Start the ASGI development server:
```bash
python manage.py runserver
```
*The server will start on `http://127.0.0.1:8000/`. You can navigate there to create your account!*

### 2. Chrome Extension Setup

1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Toggle **"Developer mode"** on in the top right corner.
3. Click **"Load unpacked"** in the top left.
4. Select the `extension/` folder located inside the cloned `NeuroTrace` repository.
5. The extension is now active! Ensure you are logged into your dashboard at `http://127.0.0.1:8000/` so the extension can securely sync your data.

## Deployment 🌍

NeuroTrace is designed to be easily deployed to **Render.com**. 
*(Deployment instructions coming soon...)*

## License 📜

MIT License. Feel free to use and modify!
