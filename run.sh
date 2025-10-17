#!/bin/bash -x
set -e

PWD=`pwd`
echo $PWD
activate () {
    . $PWD/venv/bin/activate
}

activate
python3 ./mememachine.py
deactivate