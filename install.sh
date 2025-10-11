#!/bin/bash -x

# Update and Upgrade
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt update
sudo apt upgrade -y

# Printer Permissions
sudo cat <<EOF >/etc/udev/rules.d/99-escpos.rules
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0202", MODE="0664", GROUP="dialout"
EOF
sudo service udev restart

pip install --user --upgrade pip
sudo apt-get install -y wget python3-opengl

pip install -r ./requirements.txt

sudo systemctl enable pigpiod
sudo systemctl start pigpiod

mkdir generated