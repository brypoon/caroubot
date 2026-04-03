curl -LsSf https://astral.sh/uv/install.sh | sh
sudo cp ~/.local/bin/uv /usr/local/bin/uv
sudo chmod +x /usr/local/bin/uv
uv sync

echo "Setting up systemd service..."
sudo tee /etc/systemd/system/caroubot.service <<EOF
[Unit]
Description=Carousell Monitor Bot
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$(pwd)
ExecStart=/usr/local/bin/uv run $(pwd)/main.py

Restart=always
RestartSec=5

# Ensures logs flush immediately
Environment=PYTHONUNBUFFERED=1x

[Install]
WantedBy=multi-user.target
EOF

echo "Creating .env file..."
tee ./.env <<EOF
URL=carousell_search_url
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_telegram_chat_id
EOF

echo "Setup complete. Please edit the .env file with your actual values."
chmod u+x start.sh