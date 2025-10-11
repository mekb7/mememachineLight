sudo cat > /etc/udev/rules.d/99-escpos.rules <<- "EOF"
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0202", MODE="666", GROUP="users"
EOF
sudo /etc/init.d/udev restart