#!/usr/bin/env python3
#
#  force_IP.py
#  
#  Copyright 2026 Unknown <rms@raspberrypi>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#  


import PySpin

def force_camera_ip(serial, target_ip, subnet_mask="255.255.255.0"):
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()
    
    found = False
    for cam in cam_list:
        nodemap_tldevice = cam.GetTLDeviceNodeMap()
        device_id = PySpin.CStringPtr(nodemap_tldevice.GetNode("DeviceID")).GetValue()
        
        if serial in device_id:
            print(f"Found camera {serial}. Forcing IP to {target_ip}...")
            # This is the magic command that reaches across subnets
            cam.ForceIP(
                sum([int(x) << (8 * i) for i, x in enumerate(reversed(target_ip.split('.')))]),
                sum([int(x) << (8 * i) for i, x in enumerate(reversed(subnet_mask.split('.')))]),
                0 # Gateway
            )
            print("IP Forced successfully!")
            found = True
            break
            
    if not found:
        print(f"Could not find camera {serial} at all. Check the cable/power.")
    
    cam_list.Clear()
    system.ReleaseInstance()

# Force the camera to be 192.168.42.10 (so it matches your 192.168.42.1)
force_camera_ip("26176619", "192.168.42.10")
