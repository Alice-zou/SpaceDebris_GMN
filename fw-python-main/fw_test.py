import ifw 
import hsfw
import time
import copy

#This runs the Optec FilterWheel classes through their common methods.
def run_wheel_tests(wheel):
    print("Serial Number:", wheel.serial_number)
    print("Firmware Version:", wheel.firmware_version)
    
    wheel_id = wheel.get_wheel_id()
    print("Wheel ID:", repr(wheel_id))
    
    if wheel_id == '\x00' or wheel_id == '' or not wheel_id:
        print("\n[WARNING] No valid wheel carousel detected by the controller (Wheel ID is null).")
        print("Please check that the filter wheel carousel is fully inserted, the magnetic hub has snapped into place, and the hub tensioner is securely tightened.\n")
        return

    print("Wheel Name:", wheel.get_wheel_name())
    print("Current Filter:", wheel.get_current_filter())
    print("Filter Name:", wheel.get_filter_name())
    print("Number of Filters:", wheel.number_of_filters())

    for i in 'ABCDEFGHIJK':
        print("Number of filters for wheel {}: {}".format(i,wheel.number_of_filters(i)))

    print("Homing wheel...")
    wheel.home()

    #Wait for the wheel to finish homing
    while wheel.is_homing:
        time.sleep(.01)

    if not wheel.is_homed:
        print("Failed to home wheel")
        return

    print("Wheel Name for A:", wheel.get_wheel_name('A'))

    for i in range(1, wheel.number_of_filters() + 1):
        wheel.move_to_filter(i)
        #Wait for the wheel to finish moving
        while wheel.is_moving:
            time.sleep(.01)
        print(wheel.get_current_filter())
        print(wheel.get_filter_name(wheel.get_current_filter()))

    print(wheel.get_filter_names())
    print(wheel.get_wheel_names())

    names = copy.deepcopy(wheel.get_filter_names())

    new_names = []

    for i in range(1, wheel.number_of_filters() + 1):
        new_names.append('QWER{}{}'.format(i, wheel.get_wheel_id()))

    wheel.set_filter_names(new_names)

    print(wheel.get_filter_names())
    print(new_names)

    wheel.set_filter_names(names)

    wheel.close()

def TestHSFW():
    serial_numbers = hsfw.HSFW.get_serial_numbers()
    if not serial_numbers:
        print("No HSFW USB devices found.")
        return

    print("Found HSFW USB Serial Numbers:", serial_numbers)
    
    # Use the first HSFW
    serial_num = serial_numbers[0]
    print(f"Opening HSFW Serial: {serial_num}")
    try:
        wheel = hsfw.HSFW(serial_num)
        status = wheel.get_hsfw_status()
        description = wheel.get_hsfw_description()
        print("Raw Status:", status)
        print("Raw Description:", description)
        
        error_code = status['error_state']
        if error_code != 0:
            error_msg = wheel.get_error_text(error_code)
            print(f"HSFW is reporting an error state {error_code}: {error_msg}")
            print("Attempting to clear error...")
            wheel.clear_error()
            # Refresh status
            status = wheel.get_hsfw_status()
            print("Status after clear:", status)
            
        print("Testing HSFW common methods...")
        run_wheel_tests(wheel)
    except Exception as e:
        print(f"Error testing HSFW: {e}")
        import traceback
        traceback.print_exc()

def TestIFW(comport):
    print(f"testing IFW on port {comport}")
    try:
        wheel = ifw.IFW(comport)
        print(f"IFW Model: {wheel.model}")
        run_wheel_tests(wheel)
    except Exception as e:
        print(f"Error testing IFW on {comport}: {e}")

if __name__ == '__main__':
    print("--- Running Filter Wheel Connection Tests ---")
    TestHSFW()

    print("\n--- Running IFW Tests ---")
    # Try /dev/ttyAMA10 which is the available serial port on the system
    TestIFW("/dev/ttyAMA10")