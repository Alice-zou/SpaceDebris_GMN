#!/usr/bin/env python3
"""
configure_camera_ips.py

Utility script to list all connected Spinnaker cameras and configure their
IP addresses (either temporarily forcing them or setting a persistent static IP).
"""

import sys
import socket
import struct
import PySpin

def int_to_ip(val):
    try:
        return socket.inet_ntoa(struct.pack("!I", val & 0xFFFFFFFF))
    except Exception:
        return str(val)

def ip_to_int(ip_str):
    try:
        return sum([int(x) << (8 * i) for i, x in enumerate(reversed(ip_str.split('.')))])
    except Exception as e:
        print(f"Invalid IP address format: {ip_str}. Error: {e}")
        return None

def list_cameras():
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()
    num_cams = cam_list.GetSize()
    
    print(f"Detected {num_cams} camera(s) on the network:")
    print("=" * 60)
    
    for i in range(num_cams):
        try:
            cam = cam_list.GetByIndex(i)
            nodemap = cam.GetTLDeviceNodeMap()
            
            serial = PySpin.CStringPtr(nodemap.GetNode("DeviceSerialNumber")).GetValue()
            vendor = PySpin.CStringPtr(nodemap.GetNode("DeviceVendorName")).GetValue()
            model = PySpin.CStringPtr(nodemap.GetNode("DeviceModelName")).GetValue()
            mac_val = PySpin.CIntegerPtr(nodemap.GetNode("GevDeviceMACAddress")).GetValue()
            ip_val = PySpin.CIntegerPtr(nodemap.GetNode("GevDeviceIPAddress")).GetValue()
            subnet_val = PySpin.CIntegerPtr(nodemap.GetNode("GevDeviceSubnetMask")).GetValue()
            
            hex_mac = f"{(mac_val & 0xFFFFFFFFFFFF):012x}"
            mac_str = ":".join(hex_mac[j:j+2] for j in range(0, 12, 2))
            
            print(f"Camera [{i}]:")
            print(f"  Model:         {vendor} {model}")
            print(f"  Serial Number: {serial}")
            print(f"  MAC Address:   {mac_str}")
            print(f"  Current IP:    {int_to_ip(ip_val)}")
            print(f"  Subnet Mask:   {int_to_ip(subnet_val)}")
            print("-" * 60)
            
            del serial, vendor, model, mac_val, ip_val, subnet_val, nodemap, cam
        except Exception as e:
            print(f"  Error reading camera {i}: {e}")
            
    cam_list.Clear()
    system.ReleaseInstance()

def force_temporary_ip(serial, target_ip, subnet_mask="255.255.255.0"):
    """
    Force a temporary IP on a camera. This is useful when the camera is
    on a different subnet and you want to communicate with it immediately
    without changing its persistent configuration. The IP resets on power cycle.
    """
    ip_int = ip_to_int(target_ip)
    subnet_int = ip_to_int(subnet_mask)
    if ip_int is None or subnet_int is None:
        return False
        
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()
    found = False
    
    for cam in cam_list:
        nodemap = cam.GetTLDeviceNodeMap()
        device_serial = PySpin.CStringPtr(nodemap.GetNode("DeviceSerialNumber")).GetValue()
        
        if device_serial == serial:
            print(f"Found camera {serial}. Forcing temporary IP to {target_ip}...")
            try:
                # ForceIP reaches across subnets using MAC broadcast
                cam.ForceIP(ip_int, subnet_int, 0)
                print("Temporary IP forced successfully!")
                found = True
            except Exception as e:
                print(f"Failed to force IP: {e}")
            break
            
    if not found:
        print(f"Camera with serial {serial} not found.")
        
    cam_list.Clear()
    system.ReleaseInstance()
    return found

def set_persistent_ip(serial, target_ip, subnet_mask="255.255.255.0", gateway="0.0.0.0"):
    """
    Set a persistent static IP address. This writes to the camera's
    internal flash and persists across reboots/power cycles.
    """
    ip_int = ip_to_int(target_ip)
    subnet_int = ip_to_int(subnet_mask)
    gw_int = ip_to_int(gateway)
    if ip_int is None or subnet_int is None or gw_int is None:
        return False
        
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()
    found = False
    
    for cam in cam_list:
        nodemap_tl = cam.GetTLDeviceNodeMap()
        device_serial = PySpin.CStringPtr(nodemap_tl.GetNode("DeviceSerialNumber")).GetValue()
        
        if device_serial == serial:
            print(f"Found camera {serial}. Initializing for persistent IP setup...")
            try:
                # Must initialize the camera to access GenICam application nodes
                cam.Init()
                nodemap = cam.GetNodeMap()
                
                # 1. Enable Persistent IP configuration
                gev_pers_ip_auto = PySpin.CBooleanPtr(nodemap.GetNode("GevCurrentIPConfigurationPersistentIP"))
                if PySpin.IsWritable(gev_pers_ip_auto):
                    gev_pers_ip_auto.SetValue(True)
                    print("  Persistent IP configuration enabled.")
                else:
                    print("  Error: GevCurrentIPConfigurationPersistentIP is not writable.")
                    
                # 2. Write the persistent IP
                gev_pers_ip = PySpin.CIntegerPtr(nodemap.GetNode("GevPersistentIPAddress"))
                if PySpin.IsWritable(gev_pers_ip):
                    gev_pers_ip.SetValue(ip_int)
                    print(f"  Persistent IP set to {target_ip}.")
                else:
                    print("  Error: GevPersistentIPAddress is not writable.")
                    
                # 3. Write the persistent subnet mask
                gev_pers_subnet = PySpin.CIntegerPtr(nodemap.GetNode("GevPersistentSubnetMask"))
                if PySpin.IsWritable(gev_pers_subnet):
                    gev_pers_subnet.SetValue(subnet_int)
                    print(f"  Persistent Subnet Mask set to {subnet_mask}.")
                else:
                    print("  Error: GevPersistentSubnetMask is not writable.")
                    
                # 4. Write the persistent gateway
                gev_pers_gw = PySpin.CIntegerPtr(nodemap.GetNode("GevPersistentGateway"))
                if PySpin.IsWritable(gev_pers_gw):
                    gev_pers_gw.SetValue(gw_int)
                    print(f"  Persistent Gateway set to {gateway}.")
                
                print("Persistent static IP address successfully configured!")
                found = True
                cam.DeInit()
            except Exception as e:
                print(f"Failed to set persistent IP: {e}")
                try:
                    cam.DeInit()
                except:
                    pass
            break
            
    if not found:
        print(f"Camera with serial {serial} not found or unreachable.")
        
    cam_list.Clear()
    system.ReleaseInstance()
    return found

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python configure_camera_ips.py list")
        print("  python configure_camera_ips.py force <serial> <ip> [subnet]")
        print("  python configure_camera_ips.py persistent <serial> <ip> [subnet] [gateway]")
        sys.exit(1)
        
    cmd = sys.argv[1].lower()
    if cmd == "list":
        list_cameras()
    elif cmd == "force":
        if len(sys.argv) < 4:
            print("Error: Serial and IP address are required.")
            sys.exit(1)
        sub = sys.argv[4] if len(sys.argv) > 4 else "255.255.255.0"
        force_temporary_ip(sys.argv[2], sys.argv[3], sub)
    elif cmd == "persistent":
        if len(sys.argv) < 4:
            print("Error: Serial and IP address are required.")
            sys.exit(1)
        sub = sys.argv[4] if len(sys.argv) > 4 else "255.255.255.0"
        gw = sys.argv[5] if len(sys.argv) > 5 else "0.0.0.0"
        set_persistent_ip(sys.argv[2], sys.argv[3], sub, gw)
    else:
        print(f"Unknown command: {cmd}")
