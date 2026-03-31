# Enable it (to start on boot):
# sudo systemctl enable caroubot.service

echo "Reloading systemd daemon..."
sudo systemctl daemon-reexec
sudo systemctl daemon-reload

echo "Starting caroubot.service..."
sudo systemctl start caroubot.service
sudo systemctl status caroubot.service