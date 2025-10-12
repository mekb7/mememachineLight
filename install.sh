#!/bin/bash -x

# Update and Upgrade
sudo apt update
sudo apt upgrade -y

# Printer Permissions
sudo tee /etc/udev/rules.d/99-escpos.rules > /dev/null <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0202", MODE="0664", GROUP="dialout"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger

sudo apt-get install -y python3 python3-pip

python3 -m venv venv
source ./venv/bin/activate
pip install -r ./requirements.txt
deactivate

sudo systemctl enable pigpiod
sudo systemctl start pigpiod

mkdir generated