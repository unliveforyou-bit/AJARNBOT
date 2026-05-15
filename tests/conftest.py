"""
pytest configuration — set required env vars before any module import
"""
import os

os.environ.setdefault('DISCORD_TOKEN',        'PYTEST_FAKE_TOKEN')
os.environ.setdefault('VOICE_LOG_CHANNEL_ID', '111111111111111111')
os.environ.setdefault('FLASK_SECRET',         'pytest_secret_key_32chars_xxxxxx')
os.environ.setdefault('OUTBOUND_WEBHOOK_URL', '')   # disable webhook
