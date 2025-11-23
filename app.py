from flask import Flask, jsonify, request
import sqlite3
import os

app = Flask(__name__)

class BotManager:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect('bot_status.db')
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS bot_status (status TEXT)')
        cursor.execute("INSERT OR IGNORE INTO bot_status VALUES ('active')")
        conn.commit()
        conn.close()
    
    def get_status(self):
        conn = sqlite3.connect('bot_status.db')
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM bot_status")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 'active'
    
    def set_status(self, status):
        conn = sqlite3.connect('bot_status.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE bot_status SET status = ?", (status,))
        conn.commit()
        conn.close()

manager = BotManager()

@app.route('/')
def home():
    return "🤖 Бот работает! Статус: " + manager.get_status()

@app.route('/api/status')
def status():
    return jsonify({'status': manager.get_status()})

@app.route('/api/toggle', methods=['POST'])
def toggle():
    current = manager.get_status()
    new_status = 'inactive' if current == 'active' else 'active'
    manager.set_status(new_status)
    return jsonify({'status': new_status})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
