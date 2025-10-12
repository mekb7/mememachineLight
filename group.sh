sudo tee /etc/udev/rules.d/99-escpos.rules > /dev/null <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0202", MODE="0664", GROUP="dialout"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger