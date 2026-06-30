import hid

REPORT_TRUE = 255
REPORT_FALSE = 0


class HSFW:
    '''
    A class to access and control the Optec HSFW line of USB Filter Wheels.

    Use the get_serial_numbers method to get all attached HSFW Serial Number. 
    open() can be used to open either 1. the only wheel attached to the system or 2. the wheel with the given serial number.
    '''
    serial_number = '*********'
    firmware_version = 1.00
    _device = None
    _connected = False

    def get_serial_numbers():
        '''Get the serial numbers of the attached wheels'''
        devs = hid.enumerate(0x10c4, 0x82cd)
        sns = []
        for dev in devs:
            sns.append(dev['serial_number'])
        return sns

    def open(self, serial_number=None):
        '''Opens the specified HSFW. This must be called before the HSFW can be used.'''
        if serial_number is not None:
            self.serial_number = serial_number

        if self._device is None:
            self._device = hid.device()
            self._device.open(0x10c4, 0x82cd, self.serial_number)

        _connected = True
        self._get_firmware_version()

    def close(self):
        '''Closes and releases the connection to the HSFW'''
        if self._device is not None:
            self._device.close()
            self._device = None

        _connected = False

    def _getIsHomed(self):
        '''Returns true if the HSFW is homed. Use the is_homed property.'''
        return self.get_hsfw_status()['is_homed']
    is_homed = property(_getIsHomed)

    def _getIsHoming(self):
        '''Returns true if the HSFW is homing. Use the is_homing property.'''
        return self.get_hsfw_status()['is_homing']
    is_homing = property(_getIsHoming)

    def _getIsMoving(self):
        '''Returns true if the HSFW is moving. Use the is_moving property.'''
        return self.get_hsfw_status()['is_moving']
    is_moving = property(_getIsMoving)

    def getErrorState(self):
        '''
        Returns the error state of the HSFW. 
        0 indicates no error. 
        Use clear_error() to clear the error.
        Use get_error_text to get helpful text about the error.
        '''
        return self.get_hsfw_status()['error_state']
    error_state = property(getErrorState)

    def get_error_text(self, error_code = error_state):
        '''Returns a text equivalent for an error code.'''
        if error_code == 0:
            return "No Error Set"
        elif error_code == 1:
            return "12VDC Power is Disconnected"
        elif error_code ==2:
            return "Device Stalled During Move or Home Procedure. Verify wheel is inserted and hub tensioner is secure."
        elif error_code ==3:
            return "Invalid Parameter Received in Output/Feature Report"
        elif error_code ==4:
            return "Attempted to Home Device While Device is Moving"
        elif error_code ==5:
            return "Attempted to Move While Device is Already Moving"
        elif error_code ==6:
            return "Attempted to Move Before the Device Has Been Homed"
        elif error_code ==7:
            return "No wheel was detected in the device. Verify wheel is inserted and hub tensioner is secure."
        elif error_code ==8:
            return "Unable to  determine the WheelID. (Is a magnet missing from wheel?)"
        else:
            return "Unknown error code"


    def get_wheel_id(self):
        '''Returns the Wheel ID (A-K) of the current Wheel'''
        return self.get_hsfw_description()['wheel_id']

    def _get_firmware_version(self):
        description = self.get_hsfw_description()

        major = int(description['firmware_major'])
        minor = int(description['firmware_minor']) / 10.0
        revision = int(description['firmware_revision']) / 100.0

        self.firmware_version = major + minor + revision
        return self.firmware_version


    def _get_serial_number(self):
        return self.serial_number

    def __init__(self, serial_number):
        self.serial_number = serial_number
        self.open()

    def get_hsfw_status(self):
        '''Returns the raw status data for the wheel.'''
        res = self._device.get_input_report(10, 8)

        status = {
            "report_id": res[0],
            "is_homed": res[1] == REPORT_TRUE,
            "is_homing": res[2] == REPORT_TRUE,
            "is_moving": res[3] == REPORT_TRUE,
            "position": res[4],
            "error_state": res[5]
        }
        return status

    def get_hsfw_description(self):
        '''Returns the raw description data for the wheel.'''
        res = self._device.get_input_report(11, 8)

        status = {
            "report_id": res[0],
            "firmware_major": res[1],
            "firmware_minor": res[2],
            "firmware_revision": res[3],
            "filter_count": res[4],
            "wheel_id": chr(res[5]),
            "centering_offset": res[6],
        }
        return status

    def home(self):
        '''
        Homes the Wheel. 
        Make sure to monitor is_homing to block until the home is complete.
        '''
        if self.error_state != 0:
            self.clear_error()

        report_id = 21
        report = [report_id, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        if self._device.send_feature_report(report) == 0:
            raise Exception("Failed to home")

        res = self._device.get_feature_report(report_id, 14)
        if res == 0:
            raise Exception("Failed to home")

        if res[0] != report_id:
            raise Exception("Failed to home")

        home_resp = res[1]

        res = self._device.get_feature_report(report_id, 14)
        if res == 0:
            raise Exception("Failed to home")

        error_resp = res[1]

        if error_resp != REPORT_FALSE or home_resp != REPORT_TRUE:
            raise Exception("Failed to home")

    def move_to_filter(self, position):
        '''
        Move the Wheel to a given filter. 
        Make sure to monitor is_moving to block until the move is complete.
        '''
        description = self.get_hsfw_description()

        if position < 1 or description['filter_count'] < position:
            raise Exception("{} is out of range. It must be between 1 and {}".format(
                position, description['filter_count']))

        report_id = 20
        report = [report_id, position, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        if self._device.send_feature_report(report) == 0:
            raise Exception("Failed to move")

        res = self._device.get_feature_report(report_id, 14)
        if res == 0:
            raise Exception("Failed to move")

        if res[0] != report_id:
            raise Exception("Failed to move")

        move_resp = res[1]

        res = self._device.get_feature_report(report_id, 14)
        if res == 0:
            raise Exception("Failed to move")

        error_resp = res[1]

        if error_resp != REPORT_FALSE or move_resp != REPORT_TRUE:
            raise Exception("Failed to move")

    def number_of_filters(self):
        '''Returns the number of filters on the current Wheel.'''
        return self.get_hsfw_description()['filter_count']

    def get_current_filter(self):
        '''Returns the current position of the Wheel.'''
        return self.get_hsfw_status()['position']

    def clear_error(self):
        '''Clears any error set in the wheel.'''
        self._device.write([2, 0])

    def get_wheel_name(self, wheel_id = None):
        '''Returns the current wheel name.'''
        if wheel_id is None:
            wheel_id = self.get_wheel_id()


        flash_read_wheel_name = 5
        name_report = [22, flash_read_wheel_name, ord(wheel_id), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] 
        if self._device.send_feature_report(name_report) == 0:
            raise Exception("Failed to get wheel name")
        
        resp1 = self._device.get_feature_report(22, 14)

        resp2 = self._device.get_feature_report(22, 14)

        if resp1[1] != resp2[1] or resp1[1] != flash_read_wheel_name:
            raise Exception("Failed to get wheel name")

        if resp1[2] != resp2[2] or resp1[2] != 0:
            raise Exception("Failed to get wheel name")

        if resp1[3] != resp2[3] or resp1[3] != ord(wheel_id):
            raise Exception("Failed to get wheel name")

        if resp1[4] != resp2[4] or resp1[4] != 0:
            raise Exception("Failed to get wheel name")

        return  bytes(resp2[6:]).decode('utf-8')

    def get_wheel_names(self):
        '''Returns all wheel names'''
        wheels = []

        for i in 'ABCDEFGHIJK':
            wheels.append(self.get_wheel_name(i))

        return wheels

    def get_filter_name(self, position = None, wheel_id = None):
        '''Returns the current filter name or the specified filter name.'''
        if wheel_id is None:
            wheel_id = self.get_wheel_id()

        if position is None:
            position = self.get_current_filter()

        flash_read_wheel_name = 3
        name_report = [22, flash_read_wheel_name, ord(wheel_id), position, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] 
        if self._device.send_feature_report(name_report) == 0:
            raise Exception("Failed to get filter name")
        
        resp1 = self._device.get_feature_report(22, 14)

        resp2 = self._device.get_feature_report(22, 14)

        if resp1[1] != resp2[1] or resp1[1] != flash_read_wheel_name:
            raise Exception("Failed to get filter name")

        if resp1[2] != resp2[2] or resp1[2] != 0:
            raise Exception("Failed to get filter name")

        if resp1[3] != resp2[3] or resp1[3] != ord(wheel_id):
            raise Exception("Failed to get filter name")

        if resp1[4] != resp2[4] or resp1[4] != position:
            raise Exception("Failed to get filter name")

        return  bytes(resp2[6:]).decode('utf-8')

    def get_filter_names(self, wheel_id=None):
        '''Returns all names for the current wheel or the specified wheel.'''
        if wheel_id is None:
            wheel_id = self.get_wheel_id()

        filters = []

        for i in range(1, self.number_of_filters(wheel_id) + 1):
            filters.append(self.get_filter_name(i, wheel_id))

        return filters


    def number_of_filters(self, wheel_id = None):
        '''Returns the number of filters on the current wheel or specified wheel.'''
        if wheel_id is None:
            wheel_id = self.get_wheel_id()

        if isinstance(wheel_id, str):
            wheel_id = bytes(wheel_id, 'utf-8')

        if wheel_id in b'ABCDE':
            return 5
        elif wheel_id in b'FGH':
            return 8
        elif wheel_id in b'IJK':
            return 7
        else:
            return self.get_hsfw_description()['filter_count']

    def set_filter_names(self, names, wheel_id = None):
        '''Sets the filter names for the current or specified wheel.'''
        if wheel_id is None:
            wheel_id = self.get_wheel_id()

        if not self._check_valid_wheel_id(wheel_id):
            raise Exception("Invalid wheel_id")

        if len(names) is not self.number_of_filters(wheel_id):
            raise Exception("You must specify the correct number of names {} for this model.".format(
                self.number_of_filters(wheel_id)))

        for name in names:
            if name is None:
                raise Exception("Names must not be null")
            if len(name) > 8:
                raise Exception("Names must be less then 8 characters")
        index = 1
        for name in names:
            if name != self.get_filter_name(index):
                self.set_filter_name(name, index, wheel_id)
            index = index +1

    def set_filter_name(self, name, position, wheel_id = None):
        '''Sets the filter name for the position or current or specified wheel.'''
        if wheel_id is None:
            wheel_id = self.get_wheel_id()

        if not self._check_valid_wheel_id(wheel_id):
            raise Exception("Invalid wheel_id")

        if self.firmware_version < 1.03 and wheel_id in 'IJK':
            raise Exception("Can't set IJK for older firmware")

        if name is None:
            raise Exception("Names must not be null")
        if len(name) > 8:
            raise Exception("Names must be less then 8 characters")

        flash_update_filter_name = 2
        flashops_command = 22

        name = name.ljust(8, ' ')

        data = [flashops_command, flash_update_filter_name, ord(wheel_id), position, ord(name[0]), ord(name[1]), ord(name[2]), ord(name[3]), ord(name[4]), ord(name[5]), ord(name[6]), ord(name[7]), 0, 0]

        if self._device.send_feature_report(data) == 0:
            raise Exception("Failed to set filter name")
        
        resp1 = self._device.get_feature_report(22, 14)

        resp2 = self._device.get_feature_report(22, 14)

        if resp1[1] != resp2[1] or resp1[1] != flash_update_filter_name:
            raise Exception("Failed to set filter name")

        if resp1[2] != resp2[2] or resp1[2] != 0:
            raise Exception("Failed to set filter name")

        if resp1[3] != resp2[3] or resp1[3] != ord(wheel_id):
            raise Exception("Failed to set filter name")

        if resp1[4] != resp2[4] or resp1[4] != position:
            raise Exception("Failed to set filter name")


    def _check_valid_wheel_id(self, wheel_id):
        return wheel_id in 'ABCDEFGHIJK'
