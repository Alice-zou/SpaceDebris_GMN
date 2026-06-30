# Optec FW Python classes

These are Python classes to control the Optec HSFW (hsfw.py) and the IFW/IFW2 (ifw.py). A sample use of the classes is found in fw_test.py. The common functions are identical for all models of FilterWheel.

The fw_test demo works with both the HSFW and IFW. Be sure to comment out the model that you do not want to test. There are comments in the example and docstrings in the classes.

The IFW / IFW2 uses serial communication and requires pyserial. Make sure that the user has permission to use Serial Ports if running on linux.

The HSFW uses USB HID and requires the hidapi library. Make sure that the user has permission to access the USB device. A sample Udev rules file can be found here (<https://github.com/OptecInc/fw-development>).
