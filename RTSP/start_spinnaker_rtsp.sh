#!/usr/bin/env bash
#
# start_spinnaker_rtsp.sh
# Automates launching the Spinnaker camera to RTSP stream.
#

echo "Optimizing ethernet interface eth0 for GigE Vision..."
# Set MTU to 9000 (Jumbo Frames) if not already set
CURRENT_MTU=$(cat /sys/class/net/eth0/mtu 2>/dev/null)
if [ "$CURRENT_MTU" != "9000" ]; then
    echo "Setting eth0 MTU to 9000..."
    sudo ip link set dev eth0 down && sudo ip link set dev eth0 mtu 9000 && sudo ip link set dev eth0 up
    echo "Wait 10 seconds for camera to reconnect and negotiate IP..."
    sleep 10
fi

# Ensure sysctl buffers are set to 16MB
sudo sysctl -w net.core.rmem_max=16777216 net.core.wmem_max=16777216 >/dev/null

echo "Starting Spinnaker RTSP streamer..."
/home/rms/.pyenv/versions/3.10.14/bin/python /home/rms/Desktop/Workspace/RTSP/spinnaker_to_rtsp.py
