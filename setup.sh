curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync

echo "Setting up systemd service..."
sudo tee /etc/systemd/system/caroubot.service <<EOF
[Unit]
Description=Carousell Monitor Bot
After=network.target

USER_NAME=$(whoami)
WORK_DIR=$(pwd)

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${WORK_DIR}
ExecStart=uv run ${WORK_DIR}/main.py

Restart=always
RestartSec=5

# Ensures logs flush immediately
Environment=PYTHONUNBUFFERED=1

# Optional: load .env manually if needed
EnvironmentFile=/home/ec2-user/carousell-bot/.env

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd daemon..."
sudo systemctl daemon-reexec
sudo systemctl daemon-reload

echo "Creating .env file..."
tee ./.env <<EOF
URL=carousell_search_url
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_telegram_chat_id
EOF

echo "Setup complete. Please edit the .env file with your actual values."