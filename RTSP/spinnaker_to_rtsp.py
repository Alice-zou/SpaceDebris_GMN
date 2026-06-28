#!/usr/bin/env python3
"""
spinnaker_to_rtsp.py

Captures video from a Spinnaker (FLIR) GigE/USB camera, applies sensor binning,
resizes the frames to 1280x720 (optionally preserving aspect ratio via letterboxing),
and streams it to a local MediaMTX RTSP server.

Compatible with Python 3.10 containing PySpin.
"""

import sys
import os
import time
import socket
import subprocess
import cv2
import numpy as np
import PySpin

import configparser

# ==================== CONFIGURATION ====================
config = configparser.ConfigParser()
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spinnaker.config')

if not os.path.exists(config_path):
    print(f"[Config] Configuration file not found at {config_path}! Exiting.")
    sys.exit(1)

config.read(config_path)

# Camera settings
SERIAL_NUMBER = config.get('Camera', 'serial_number', fallback='').strip()
if SERIAL_NUMBER == '':
    SERIAL_NUMBER = None

BINNING = config.getint('Camera', 'binning', fallback=2)
TARGET_WIDTH = config.getint('Camera', 'target_width', fallback=1280)
TARGET_HEIGHT = config.getint('Camera', 'target_height', fallback=720)
FPS = config.getint('Camera', 'fps', fallback=25)
PRESERVE_ASPECT_RATIO = config.getboolean('Camera', 'preserve_aspect_ratio', fallback=False)

AUTO_EXPOSURE = config.getboolean('Camera', 'auto_exposure', fallback=False)
EXPOSURE_TIME_US = config.getfloat('Camera', 'exposure_time_us', fallback=40000.0)
AUTO_GAIN = config.getboolean('Camera', 'auto_gain', fallback=False)
GAIN_DB = config.getfloat('Camera', 'gain_db', fallback=24.0)

# RTSP settings
RTSP_PORT = config.getint('RTSP', 'port', fallback=8554)
RTSP_PATH = config.get('RTSP', 'path', fallback='live').strip()

# MediaMTX settings
MEDIAMTX_BIN = config.get('MediaMTX', 'bin_path', fallback='/home/rms/Desktop/Workspace/Mediamtx/mediamtx').strip()
MEDIAMTX_CONFIG = config.get('MediaMTX', 'config_path', fallback='/home/rms/Desktop/Workspace/Mediamtx/mediamtx.yml').strip()
# =======================================================


def is_port_in_use(port):
    """Check if the given port is already listening (i.e., RTSP server is running)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def start_mediamtx():
    """Start MediaMTX in the background if it's not already running."""
    if is_port_in_use(RTSP_PORT):
        print(f"[RTSP] RTSP port {RTSP_PORT} is already active. Assuming MediaMTX is running.")
        return None

    if not os.path.exists(MEDIAMTX_BIN):
        print(f"[Error] MediaMTX binary not found at: {MEDIAMTX_BIN}")
        print("Please check your path configuration.")
        sys.exit(1)

    print(f"[RTSP] Starting MediaMTX server using config: {MEDIAMTX_CONFIG}...")
    try:
        # Run MediaMTX in background
        proc = subprocess.Popen(
            [MEDIAMTX_BIN, MEDIAMTX_CONFIG],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(2)  # Wait for server initialization
        if proc.poll() is None:
            print("[RTSP] MediaMTX started successfully in background.")
            return proc
        else:
            print("[Error] MediaMTX exited immediately. Check config file.")
            sys.exit(1)
    except Exception as e:
        print(f"[Error] Failed to launch MediaMTX: {e}")
        sys.exit(1)


def configure_camera(cam):
    """Configure camera binning, exposure, gain and frame rate."""
    nodemap = cam.GetNodeMap()

    # Read and print initial camera gain before changing it
    try:
        node_gain = PySpin.CFloatPtr(nodemap.GetNode("Gain"))
        if PySpin.IsAvailable(node_gain) and PySpin.IsReadable(node_gain):
            initial_gain = node_gain.GetValue()
            print(f"[Camera] Initial Gain: {initial_gain:.2f} dB")
        else:
            print("[Camera] Gain node is not readable.")
    except Exception as e:
        print(f"[Camera] Warning: Could not read initial gain: {e}")

    # 1. Setup Binning
    print(f"[Camera] Setting hardware binning to {BINNING}x{BINNING}...")
    node_bin_h = PySpin.CIntegerPtr(nodemap.GetNode("BinningHorizontal"))
    node_bin_v = PySpin.CIntegerPtr(nodemap.GetNode("BinningVertical"))

    if PySpin.IsAvailable(node_bin_h) and PySpin.IsWritable(node_bin_h):
        val = max(node_bin_h.GetMin(), min(node_bin_h.GetMax(), int(BINNING)))
        node_bin_h.SetValue(val)
        print(f"  BinningHorizontal set to {val}")
    else:
        print("  BinningHorizontal node NOT writable/available!")

    if PySpin.IsAvailable(node_bin_v) and PySpin.IsWritable(node_bin_v):
        val = max(node_bin_v.GetMin(), min(node_bin_v.GetMax(), int(BINNING)))
        node_bin_v.SetValue(val)
        print(f"  BinningVertical set to {val}")
    else:
        print("  BinningVertical node NOT writable/available!")

    # Configure Binning Mode to 'Sum' (increases sensitivity for astronomical objects)
    node_bin_h_mode = PySpin.CEnumerationPtr(nodemap.GetNode("BinningHorizontalMode"))
    if PySpin.IsAvailable(node_bin_h_mode) and PySpin.IsWritable(node_bin_h_mode):
        try:
            node_bin_h_mode.FromString("Sum")
            print("  BinningHorizontalMode set to Sum")
        except PySpin.SpinnakerException:
            try:
                node_bin_h_mode.FromString("Average")
                print("  BinningHorizontalMode set to Average")
            except:
                pass

    node_bin_v_mode = PySpin.CEnumerationPtr(nodemap.GetNode("BinningVerticalMode"))
    if PySpin.IsAvailable(node_bin_v_mode) and PySpin.IsWritable(node_bin_v_mode):
        try:
            node_bin_v_mode.FromString("Sum")
            print("  BinningVerticalMode set to Sum")
        except PySpin.SpinnakerException:
            try:
                node_bin_v_mode.FromString("Average")
                print("  BinningVerticalMode set to Average")
            except:
                pass

    # Maximize the acquisition region (Width & Height) to match new binning settings
    node_width = PySpin.CIntegerPtr(nodemap.GetNode("Width"))
    node_height = PySpin.CIntegerPtr(nodemap.GetNode("Height"))
    if PySpin.IsAvailable(node_width) and PySpin.IsWritable(node_width):
        node_width.SetValue(node_width.GetMax())
    if PySpin.IsAvailable(node_height) and PySpin.IsWritable(node_height):
        node_height.SetValue(node_height.GetMax())

    # Read final sensor width/height after binning
    sensor_width = node_width.GetValue()
    sensor_height = node_height.GetValue()
    print(f"[Camera] Sensor output resolution after binning: {sensor_width}x{sensor_height}")

    # 2. Setup Exposure Control
    node_exposure_auto = PySpin.CEnumerationPtr(nodemap.GetNode("ExposureAuto"))
    if PySpin.IsAvailable(node_exposure_auto) and PySpin.IsWritable(node_exposure_auto):
        if AUTO_EXPOSURE:
            node_exposure_auto.FromString("Continuous")
            print("  ExposureAuto set to Continuous (Auto)")
        else:
            node_exposure_auto.FromString("Off")
            print("  ExposureAuto set to Off (Manual)")

            if EXPOSURE_TIME_US is not None:
                node_exposure_time = PySpin.CFloatPtr(nodemap.GetNode("ExposureTime"))
                if PySpin.IsAvailable(node_exposure_time) and PySpin.IsWritable(node_exposure_time):
                    val = max(node_exposure_time.GetMin(), min(node_exposure_time.GetMax(), float(EXPOSURE_TIME_US)))
                    node_exposure_time.SetValue(val)
                    print(f"  ExposureTime set to {val:.1f} us")
                else:
                    print("  ExposureTime node NOT writable/available!")

    # 3. Setup Gain Control
    node_gain_auto = PySpin.CEnumerationPtr(nodemap.GetNode("GainAuto"))
    if PySpin.IsAvailable(node_gain_auto) and PySpin.IsWritable(node_gain_auto):
        if AUTO_GAIN:
            node_gain_auto.FromString("Continuous")
            print("  GainAuto set to Continuous (Auto)")
        else:
            node_gain_auto.FromString("Off")
            print("  GainAuto set to Off (Manual)")

            if GAIN_DB is not None:
                node_gain = PySpin.CFloatPtr(nodemap.GetNode("Gain"))
                if PySpin.IsAvailable(node_gain) and PySpin.IsWritable(node_gain):
                    val = max(node_gain.GetMin(), min(node_gain.GetMax(), float(GAIN_DB)))
                    node_gain.SetValue(val)
                    print(f"  Gain set to {val:.1f} dB")
                else:
                    print("  Gain node NOT writable/available!")

    # 4. Setup Frame Rate (FPS)
    node_fps_enable = PySpin.CBooleanPtr(nodemap.GetNode("AcquisitionFrameRateEnable"))
    if PySpin.IsAvailable(node_fps_enable) and PySpin.IsWritable(node_fps_enable):
        node_fps_enable.SetValue(True)
    else:
        node_fps_auto = PySpin.CEnumerationPtr(nodemap.GetNode("AcquisitionFrameRateAuto"))
        if PySpin.IsAvailable(node_fps_auto) and PySpin.IsWritable(node_fps_auto):
            try:
                node_fps_auto.FromString("Off")
            except:
                pass

    node_fps = PySpin.CFloatPtr(nodemap.GetNode("AcquisitionFrameRate"))
    if PySpin.IsAvailable(node_fps) and PySpin.IsWritable(node_fps):
        val = max(node_fps.GetMin(), min(node_fps.GetMax(), float(FPS)))
        node_fps.SetValue(val)
        print(f"  AcquisitionFrameRate set to {val:.2f} FPS")
    else:
        print("  AcquisitionFrameRate node NOT writable/available!")

    # 5. Optimize Transport Layer and GigE parameters for stability
    try:
        # Check if it is a GigE Vision camera
        nodemap_tldevice = cam.GetTLDeviceNodeMap()
        device_type_node = PySpin.CEnumerationPtr(nodemap_tldevice.GetNode("DeviceType"))
        is_gige = False
        if PySpin.IsAvailable(device_type_node) and PySpin.IsReadable(device_type_node):
            if device_type_node.GetCurrentEntry().GetSymbolic() == "GigEVision":
                is_gige = True

        if is_gige:
            print("  [GigE] Optimizing GigE Vision parameters...")
            # Set Packet Size to match Jumbo Frames MTU of 9000
            node_packet_size = PySpin.CIntegerPtr(nodemap.GetNode("GevSCPSPacketSize"))
            if PySpin.IsAvailable(node_packet_size) and PySpin.IsWritable(node_packet_size):
                # Use 9000 or the maximum supported by the camera, whichever is smaller
                val = min(node_packet_size.GetMax(), 9000)
                node_packet_size.SetValue(val)
                print(f"    GevSCPSPacketSize set to {val}")
            else:
                print("    GevSCPSPacketSize node NOT writable/available!")

            # Set Packet Delay to pace transmission and prevent drops (e.g. 400)
            node_packet_delay = PySpin.CIntegerPtr(nodemap.GetNode("GevSCPD"))
            if PySpin.IsAvailable(node_packet_delay) and PySpin.IsWritable(node_packet_delay):
                node_packet_delay.SetValue(400)
                print("    GevSCPD (packet delay) set to 400")
            else:
                print("    GevSCPD node NOT writable/available!")

        # Set stream buffer count to a higher value for stability
        s_node_map = cam.GetTLStreamNodeMap()
        node_buffer_mode = PySpin.CEnumerationPtr(s_node_map.GetNode("StreamBufferCountMode"))
        if PySpin.IsAvailable(node_buffer_mode) and PySpin.IsWritable(node_buffer_mode):
            node_buffer_mode.FromString("Manual")
            node_buffer_count = PySpin.CIntegerPtr(s_node_map.GetNode("StreamBufferCountNum"))
            if PySpin.IsAvailable(node_buffer_count) and PySpin.IsWritable(node_buffer_count):
                node_buffer_count.SetValue(30)
                print("  [Stream] StreamBufferCountNum set to 30 (expanded for stability)")
    except Exception as e:
        print(f"  [Warning] Failed to optimize TL stream parameters: {e}")

    return sensor_width, sensor_height


def resize_and_pad(frame, target_width, target_height, preserve_aspect_ratio=False):
    """Resize the captured camera frame to the target dimensions."""
    if not preserve_aspect_ratio:
        return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)

    h, w = frame.shape[:2]
    target_aspect = target_width / target_height
    aspect = w / h

    if aspect > target_aspect:
        # Scale to match target width
        new_w = target_width
        new_h = int(target_width / aspect)
    else:
        # Scale to match target height
        new_h = target_height
        new_w = int(target_height * aspect)

    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # Pad with black borders
    if len(frame.shape) == 3:
        padded = np.zeros((target_height, target_width, 3), dtype=np.uint8)
    else:
        padded = np.zeros((target_height, target_width), dtype=np.uint8)

    dy = (target_height - new_h) // 2
    dx = (target_width - new_w) // 2
    padded[dy:dy+new_h, dx:dx+new_w] = resized
    return padded


def main():
    # Start MediaMTX
    mtx_proc = start_mediamtx()

    # Initialize PySpin System
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()

    if cam_list.GetSize() == 0:
        print("[Error] No Spinnaker cameras detected! Please check connection.")
        cam_list.Clear()
        system.ReleaseInstance()
        if mtx_proc:
            mtx_proc.terminate()
        sys.exit(1)

    cam = None
    if SERIAL_NUMBER:
        try:
            cam = cam_list.GetBySerial(str(SERIAL_NUMBER))
            print(f"[Camera] Found camera with requested serial {SERIAL_NUMBER}.")
        except Exception:
            print(f"[Warning] Camera with serial {SERIAL_NUMBER} not found. Fallback to first available.")
            cam = cam_list.GetByIndex(0)
    else:
        cam = cam_list.GetByIndex(0)

    # Get device ID / Serial for logging
    nodemap_tldevice = cam.GetTLDeviceNodeMap()
    device_id_node = PySpin.CStringPtr(nodemap_tldevice.GetNode("DeviceSerialNumber"))
    device_serial = device_id_node.GetValue() if PySpin.IsAvailable(device_id_node) else "Unknown"
    print(f"[Camera] Using camera serial: {device_serial}")

    # Initialize and configure camera
    cam.Init()
    try:
        sensor_w, sensor_h = configure_camera(cam)
    except Exception as e:
        print(f"[Error] Failed to configure camera settings: {e}")
        cam.DeInit()
        del cam
        cam_list.Clear()
        system.ReleaseInstance()
        if mtx_proc:
            mtx_proc.terminate()
        sys.exit(1)

    # Start Acquisition
    cam.BeginAcquisition()
    print("[Camera] Acquisition started.")

    # Setup FFmpeg pipe to push stream to MediaMTX
    rtsp_url = f"rtsp://127.0.0.1:{RTSP_PORT}/{RTSP_PATH}"
    ffmpeg_cmd = [
        'ffmpeg',
        '-y',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'rgb24',
        '-s', f'{TARGET_WIDTH}x{TARGET_HEIGHT}',
        '-framerate', str(FPS),
        '-i', '-',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-pix_fmt', 'yuv420p',
        '-f', 'rtsp',
        rtsp_url
    ]

    print(f"[FFmpeg] Starting stream encoder pushing to {rtsp_url}...")
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    print("\n=======================================================")
    print(f"RTSP stream is live at: {rtsp_url}")
    print(f"Update your RMS config to: device: {rtsp_url}")
    print("Press Ctrl+C to stop streaming.")
    print("=======================================================\n")

    # Initialize ImageProcessor
    processor = PySpin.ImageProcessor()
    processor.SetColorProcessing(PySpin.SPINNAKER_COLOR_PROCESSING_ALGORITHM_HQ_LINEAR)

    try:
        frame_count = 0
        last_log_time = time.time()
        
        while True:
            # Grab frame with a timeout of 1000ms
            image_result = cam.GetNextImage(1000)

            if image_result.IsIncomplete():
                print(f"[Warning] Image incomplete: {image_result.GetImageStatus()}")
                image_result.Release()
                continue

            # Convert to RGB8 using image processor
            image_converted = processor.Convert(image_result, PySpin.PixelFormat_RGB8)
            
            # Extract raw image data as NumPy Array
            img_data = image_converted.GetNDArray()
            image_result.Release()

            # Resize/pad to TARGET_WIDTH x TARGET_HEIGHT
            frame_resized = resize_and_pad(img_data, TARGET_WIDTH, TARGET_HEIGHT, PRESERVE_ASPECT_RATIO)

            # Write the raw RGB bytes directly to FFmpeg pipe
            ffmpeg_proc.stdin.write(frame_resized.tobytes())
            frame_count += 1

            # Log status periodically
            now = time.time()
            if now - last_log_time >= 5.0:
                elapsed = now - last_log_time
                actual_fps = frame_count / elapsed
                print(f"[Stream] Active - Pushing at {actual_fps:.2f} FPS (Resolution: {TARGET_WIDTH}x{TARGET_HEIGHT})")
                frame_count = 0
                last_log_time = now

    except KeyboardInterrupt:
        print("\n[Stream] Stopping stream gracefully...")
    except Exception as e:
        print(f"\n[Error] Runtime exception: {e}")
    finally:
        # 1. Close FFmpeg stdin and wait for process to terminate
        if ffmpeg_proc:
            try:
                ffmpeg_proc.stdin.close()
                ffmpeg_proc.wait(timeout=2.0)
            except Exception:
                ffmpeg_proc.kill()
            print("[FFmpeg] Process stopped.")

        # 2. Release Camera Resources
        if cam:
            try:
                if cam.IsStreaming():
                    cam.EndAcquisition()
                cam.DeInit()
            except Exception as e:
                print(f"[Warning] Error during camera release: {e}")
            
            # Crucial: Delete local Python references to prevent swig destruct errors
            del cam

        cam_list.Clear()
        system.ReleaseInstance()
        print("[Camera] PySpin system resources released.")

        # 3. Terminate MediaMTX if started by this script
        if mtx_proc:
            mtx_proc.terminate()
            mtx_proc.wait()
            print("[RTSP] MediaMTX server stopped.")


if __name__ == "__main__":
    main()
