##########################################################################
# Testing of rtsp stream display 
##########################################################################
# % CPU usage
##########################################################################
import PySpin
import subprocess
import numpy as np
import sys

# --- CONFIGURATION ---
SERIAL_NUMBER = '26176619'

# WIDTH = 1280
# HEIGHT = 720
FPS = 25

# MediaMTX RTSP path (localhost if MediaMTX is on the same Pi)
RTSP_URL = "rtsp://192.168.42.10:8554/user=admin&password=&channel=1&stream=0.sdp"

# --- INITIALIZE SPINNAKER ---
system = PySpin.System.GetInstance()
cam_list = system.GetCameras()

try:
    cam = cam_list.GetBySerial(SERIAL_NUMBER)
except:
    print(f"Camera {SERIAL_NUMBER} not found!")
    sys.exit()

cam.Init()
# Set resolution and FPS if needed (or rely on camera's current config) 
# Set maximum binning value
nodemap = cam.GetNodeMap()

# Get Initial Gain value
node_gain = PySpin.CFloatPtr(nodemap.GetNode('Gain'))
     
if PySpin.IsReadable(node_gain):
    current_gain = node_gain.GetValue()
    print(f"Current Gain: {current_gain:.2f} dB")
else:
    print("Gain node not readable.")

node_binning_horizontal = PySpin.CIntegerPtr(nodemap.GetNode("BinningHorizontal"))
node_binning_vertical = PySpin.CIntegerPtr(nodemap.GetNode("BinningVertical"))

# Get maximum binning value
max_binning_h = node_binning_horizontal.GetMax()
max_binning_v = node_binning_vertical.GetMax()

# Set binning to maximum 
node_binning_horizontal.SetValue(max_binning_h)
node_binning_vertical.SetValue(max_binning_v)
print(f"Set Binning Horizontal to {max_binning_h}")
print(f"Set Binning Vertical to {max_binning_v}")

# After binning, the camera automatically updates its Width and Height nodes.
# We must read these to tell FFmpeg what size the frames are.
width = PySpin.CIntegerPtr(nodemap.GetNode('Width')).GetValue()
height = PySpin.CIntegerPtr(nodemap.GetNode('Height')).GetValue()
print(f"Streaming at Resolution: {width}x{height}")

cam.BeginAcquisition()

# --- FFMPEG COMMAND ---
# Note: we use libx264 for H264 encoding and yuv420p for compatibility
command = [
    'ffmpeg',
    '-f', 'rawvideo',
    '-vcodec', 'rawvideo',
    '-pix_fmt', 'rgb24',         # PySpin will convert to RGB8
    '-s', f'{width}x{height}',   # New resolution based on binning 
    '-framerate', str(FPS),
    '-i', '-',                   # Input from pipe
    '-c:v', 'libx264',
    '-preset', 'ultrafast',
    '-tune', 'zerolatency',      # Optimized for live streaming
    '-pix_fmt', 'yuv420p',       # Essential for most RTSP players
    '-f', 'rtsp', 
    '-autoscale',                # FIXED: Added the comma here!
    RTSP_URL
]

# Open the pipe
process = subprocess.Popen(command, stdin=subprocess.PIPE)

print(f"Streaming started at {RTSP_URL}")
print("Press Ctrl+C to stop.")


try:
    while True:
        image_result = cam.GetNextImage(1000)
        
        if not image_result.IsIncomplete():
            # 1. CONVERSION: Spinnaker images must be converted to RGB8 
            # to match the 'rgb24' format expected by FFmpeg
            image_converted = image_result.Convert(PySpin.PixelFormat_RGB8, PySpin.HQ_LINEAR)
            
            # 2. Get the array and write to FFmpeg
            img_data = image_converted.GetNDArray()
            process.stdin.write(img_data.tobytes())
            
        image_result.Release()

except KeyboardInterrupt:
    print("\nStopping stream...")
finally:
    cam.EndAcquisition()
    cam.DeInit()
    del cam
    cam_list.Clear()
    system.ReleaseInstance()
    process.stdin.close()
    process.wait()

# ==============================================================================
# ALTERNATIVE SCRIPTS / BACKUPS
# ==============================================================================
"""
# --- 1. RAW UDP PACKET STREAMER ---
import cv2
import EasyPySpin
import numpy as np
import sys
import time
import socket
import PySpin

def start_camera():
    # 1. Initialize the Spinnaker camera interface
    cap = EasyPySpin.VideoCapture(0)

    if not cap.isOpened():
        print("Could not open Spinnaker camera.")
        sys.exit(1)
        
    try:
        cap.cam.Init() 
        node_buffer_count_mode = cap.cam.GetTLStreamNodeMap().GetNode("StreamBufferCountMode")
        if node_buffer_count_mode:
            PySpin.CEnumerationPtr(node_buffer_count_mode).FromString("Manual")
            node_buffer_count = cap.cam.GetTLStreamNodeMap().GetNode("StreamBufferCountNum")
            if node_buffer_count:
                PySpin.CIntegerPtr(node_buffer_count).SetValue(10)
                print("Successfully expanded Ethernet stream buffers to 10.")
    except Exception as e:
        print(f"Buffer configuration warning bypassed: {e}")
        
    print("Waiting 2 seconds for camera sensor initialization...")
    time.sleep(2.0)

    TARGET_WIDTH = 1280
    TARGET_HEIGHT = 720
    FPS = 25

    print(f"Original Sensor Frame: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
    print(f"Targeting Broadcast Stream: {TARGET_WIDTH}x{TARGET_HEIGHT} at {FPS} FPS")

    # 2. Set up raw Network UDP Sockets
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Increase kernel network buffer to handle large video frames smoothly
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1000000)
    
    # Broadcast to everything on your local network on Port 5005
    TARGET_IP = "255.255.255.255" 
    PORT = 5005
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    print(f"Streaming live video packets directly over raw UDP on port {PORT}...")

    frame_duration = 1.0 / FPS
    MAX_UDP_PACKET_SIZE = 60000  # Avoid splitting network packets manually
    
    try: 
        while True:
            start_time = time.time()
            
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
                
            frame_resized = cv2.resize(frame, (TARGET_WIDTH, TARGET_HEIGHT), interpolation=cv2.INTER_AREA)
            
            # Compress BGR frame matrix to highly optimized JPEG bytes
            # Quality 50 provides excellent 720p clarity while fitting cleanly into a network packet
            success, encoded_img = cv2.imencode('.jpg', frame_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
            
            if success:
                bytes_data = encoded_img.tobytes()
                if len(bytes_data) < MAX_UDP_PACKET_SIZE:
                    # Fire raw image bytes straight across the physical wire network path
                    server_socket.sendto(bytes_data, (TARGET_IP, PORT))
                else:
                    print(f"Frame dropped: size ({len(bytes_data)} bytes) exceeds packet max buffer.")
            
            # Enforce solid frame pacing
            elapsed = time.time() - start_time
            sleep_time = frame_duration - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print("\nStopping network stream safely...")
    finally: 
        cap.release()
        server_socket.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    start_camera()


# --- 2. V4L2 FAKE WEBCAM STREAMER ---
import PySpin
import cv2
import EasyPySpin
import pyfakewebcam
import numpy as np
import logging
import time

# Spinnaker to a webcam
serial = 26176619
# Initialize the spinnaker camea 
def start_camera_v4l2():

    cap = EasyPySpin.VideoCapture(0)

    if not cap.isOpened():
        print("could not open spinnaker camera.")
        exit(1)
        
    try:
        cap.cam.Init() 
        # Increase the stream buffer count for Ethernet stability
        node_buffer_count = cap.cam.GetTLStreamNodeMap().GetNode("StreamBufferCountMode")
        if node_buffer_count:
            PySpin.CEnumerationPtr(node_buffer_count).SetIntValue(2) # Manual
    except:
        pass
        
    print("Waiting 2 seconds for camera sensor initialization...")
    time.sleep(2.0)

    # Set resolution (from .config in RMS code) take full picture, downgrade pixels 
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Desire dimension 
    TARGET_HEIGHT = 720
    TARGET_WIDTH = 1280

    print(f"Original: {orig_w}x{orig_h}")
    print(f"Targeting: {TARGET_WIDTH}X{TARGET_HEIGHT} ")

    fps = 25

    # Create a fakewebcam 
    try: 
        fake = pyfakewebcam.FakeWebcam('/dev/video10', TARGET_WIDTH, TARGET_HEIGHT)
    except Exception as e:
        print(f"Error creating fake webcam: {e}. Did You run 'sudo modprobe v4l2loopback'?")
        sys.exit(1)
     
    print(f"Streaming {TARGET_WIDTH}x{TARGET_HEIGHT} to /dev/video10...")

    try: 
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to capture frame")
                break
            # resize frame
            frame_resized = cv2.resize(frame, (TARGET_WIDTH, TARGET_HEIGHT), interpolation=cv2.INTER_AREA)
            
            # convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
            
            fake.schedule_frame(frame_rgb)
            
            time.sleep(0.001)
            
    except KeyboardInterrupt:
        print("Stopping...")
    finally: 
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    start_camera_v4l2()


# --- 3. RTSP CLIENT DISPLAY ---
# Setting up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("RTSP")

# create camera interface
from camera.capture.rtspcapture import rtspCapture
logger.log(logging.INFO, "Starting Capture")
camera = rtspCapture(configs, rtsp='rtsp://127.0.0.1:8554/test')
logger.log(logging.INFO, "Getting Images")
camera.start()

window_handle = cv2.namedWindow("RTSP", cv2.WINDOW_NORMAL)
while(cv2.getWindowProperty("RTSP", cv2.WND_PROP_VISIBLE) >= 0):
    while not camera.log.empty():
        (level, msg) = camera.log.get_nowait()
        logger.log(level, msg)

    if camera.buffer and camera.buffer.avail > 0:
        frame, ts_ms = camera.buffer.pull(copy=False)
        if frame is not None:
            cv2.imshow('RTSP', frame)
    else:
        time.sleep(0.001)
    if cv2.waitKey(1) & 0xFF == ord('q'): break

camera.close(timeout=2.0)
cv2.destroyAllWindows()
"""
