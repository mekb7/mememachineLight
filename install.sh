#!/bin/bash -x
set -e

echo "=== APT update ==="
# Update and Upgrade
sudo apt update
# sudo apt upgrade -y

echo "=== Setting printer permissions ==="
# Printer Permissions
sudo tee /etc/udev/rules.d/99-escpos.rules > /dev/null <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0202", MODE="0664", GROUP="users"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "=== Installing python and packages ==="
sudo apt-get install -y python3 python3-pip python3-gpiozero python3-lgpio

echo "=== Creating venv and installing requirements ==="
python3 -m venv venv --system-site-packages
source ./venv/bin/activate
pip install -r ./requirements.txt
deactivate

echo "=== Creating output folder ==="
mkdir generated

SERVICE_NAME="mememachineLight"
SCRIPT_PATH="/home/phil/run.sh"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
LOG_DIR="/var/log"

echo "=== Installing ${SERVICE_NAME} systemd service ==="

# Ensure script exists
if [ ! -f "$SCRIPT_PATH" ]; then
  echo "Error: Script not found at $SCRIPT_PATH"
  exit 1
fi

# Make sure it’s executable
chmod +x "$SCRIPT_PATH"

# Create service file
echo "Creating systemd service at $SERVICE_PATH ..."
sudo bash -c "cat > $SERVICE_PATH" <<EOF
[Unit]
Description=MememachineLight
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${SCRIPT_PATH}
WorkingDirectory=$(dirname ${SCRIPT_PATH})
StandardOutput=append:${LOG_DIR}/${SERVICE_NAME}.log
StandardError=append:${LOG_DIR}/${SERVICE_NAME}.err
Restart=always
RestartSec=5
User=pi
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd to recognize new service
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable and start service
echo "Enabling service to start on boot..."
sudo systemctl enable "${SERVICE_NAME}.service"

echo "Starting service..."
sudo systemctl restart "${SERVICE_NAME}.service"

# Show status
sudo systemctl status "${SERVICE_NAME}.service" --no-pager

echo "=== Installation complete ==="
echo "Logs: ${LOG_DIR}/${SERVICE_NAME}.log and ${LOG_DIR}/${SERVICE_NAME}.err"
