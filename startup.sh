#!/bin/bash -x

git clone https://github.com/mekb7/mememachineLight.git

sudo systemctl enable pigpiod
sudo systemctl start pigpiod

PWD=`pwd`
echo $PWD
activate () {
    . $PWD/venv/bin/activate
}

activate
python3 ./mememachine.py
deactivate