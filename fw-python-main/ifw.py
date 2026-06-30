import serial
import serial.tools.list_ports
from enum import Enum


class IFW_Model(Enum):
    IFW = 0
    IFW3 = 1
    Unknown = 2


class IFW:
    '''
    A class to access and control the Optec IFW and IFW2 line of Filter Wheels.

    Requires the COM port of the wheel to function.
    open() can be used to open or change the COM port and must be called before using the wheel.
    '''
    wheel_id = 'A'
    firmware_version = 1.00
    serial_number = '****'
    is_homed = True
    is_homing = False
    is_moving = False
    filter_names = []
    _ser = None
    _connected = False

    model = IFW_Model.Unknown

    def __init__(self, port):
        self.port = port
        self.open()

    def __read_write(self, command, timeout=.5):
        self._ser.timeout = timeout
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()
        self._ser.write(bytes(command, 'utf-8'))

        res = self._ser.readline()

        if b'ER=' in res:
            if b'ER=1' in res:
                self.is_homed = False
                raise Exception(
                    "{message} received. Exceeded 2600 steps while homing. The wheel may be stuck or slipping.".format(message=res))
            elif b'ER=2' in res:
                raise Exception(
                    "{message} received. SBIG pulse is not in specification.".format(message=res))
            elif b'ER=3' in res:
                raise Exception(
                    "{message} received. Invalid Wheel ID.".format(message=res))
            elif b'ER=4' in res:
                self.is_homed = False
                raise Exception(
                    "{message} received. The Wheel failed to reach a position. The wheel may be stuck or slipping.".format(message=res))
            elif b'ER=5' in res:
                raise Exception(
                    "{message} received. Invalid position requested.".format(message=res))
            elif b'ER=6' in res:
                self.is_homed = False
                raise Exception(
                    "{message} received. The Wheel failed to reach a position. The wheel may be stuck or slipping.".format(message=res))
            elif b'ER=7' in res:
                raise Exception(
                    "{message} received. Invalid position requested for this wheel.".format(message=res))
            elif b'ER=8' in res:
                self.is_homed = False
                raise Exception(
                    "{message} received. No 12v power.".format(message=res))
            else:
                raise Exception(
                    "Unknown {message} received".format(message=res))
        else:
            return res

    def open(self, port=None):
        '''Opens the IFW on the specified COM Port. This must be called before the IFW can be used.'''
        if port is not None:
            self.port = port

        if len([port for port in serial.tools.list_ports.comports() if self.port in port]) < 1:
            raise Exception(
                "Port {port} is not attached to the system.".format(port=self.port))

        if self._ser is None:
            self._ser = serial.Serial(self.port, 19200, timeout=.5)

        if not b'!' in self.__read_write("WSMODE"):
            raise Exception(
                "Timed out waiting for response from IFW on port {sport}".format(sport=self.port))

        self._connected = True

        self.get_wheel_id()
        self._get_firmware_version()

        self.model = IFW_Model.Unknown

        if self.firmware_version >= 3 and self.firmware_version < 4:
            self.model = IFW_Model.IFW3
        else:
            self.model = IFW_Model.IFW

        self._get_serial_number()

        self.get_filter_names()

    def close(self):
        '''Closes and releases the connection to the IFW'''
        self._connected = False
        self._ser.write(bytes("WEXITS", 'utf-8'))
        self._ser.close()
        self._ser = None

    def home(self):
        '''
        Homes the Wheel. 
        Make sure to monitor is_homing to block until the home is complete.
        '''
        self._assert_connected()
        self.is_homed = False
        self.is_homing = True
        self.is_moving = True
        timeout = 30
        if self.firmware_version >= 4.0:
            timeout = 7
        try:
            self.wheel_id = self.__read_write("WHOMES", timeout).strip().decode("utf-8")
        except serial.SerialTimeoutException:
            self.is_homing = False
            self.is_homed = False
            self.is_moving = False
            raise Exception("Timed out during a home")
        self.is_homed = True
        self.is_homing = False
        self.is_moving = False

        self.get_current_filter()
        self.get_filter_names()

    def move_to_filter(self, position):
        '''
        Move the Wheel to a given filter. 
        Make sure to monitor is_moving to block until the move is complete.
        '''
        self._assert_connected()

        if position < 1 or position > self.number_of_filters():
            raise Exception("{} is out of range. It must be between 1 and {}".format(
                position, self.number_of_filters()))

        if self.is_moving:
            return

        if not self.is_homed:
            return

        self.is_moving = True

        timeout = 30
        if self.firmware_version >= 4.0:
            timeout = 7
        try:
            done = self.__read_write(
                "WGxxx{}".format(position), timeout).strip()
        except serial.SerialTimeoutException:
            self.is_moving = False
            raise Exception("Timed out during a home")
        finally:
            self.is_moving = False

        self.is_moving = False

    def get_wheel_id(self):
        '''Returns the Wheel ID (A-K) of the current Wheel'''
        self._assert_connected()
        res = self.__read_write("WIDENT")
        self.wheel_id = res.strip().decode("utf-8")
        return self.wheel_id

    def get_current_filter(self):
        '''Returns the current position of the Wheel.'''
        self._assert_connected()
        res = self.__read_write("WFxxxx")
        return int(res)

    def _get_firmware_version(self):
        self._assert_connected()
        try:
            res = self.__read_write("WVxxxx")
            self.firmware_version = float(res.split(b' ')[1])
            res = self.firmware_version
        except serial.SerialTimeoutException:
            self.firmware_version = 1.00
            res = 1.00
        return res

    def _get_serial_number(self):
        self._assert_connected()
        if self.model is IFW_Model.IFW:
            if self.firmware_version > 2.02:
                self.serial_number = self.__read_write(
                    "WNxxxx").split(b' ')[1].strip().decode("utf-8")
                return
        if self.model is IFW_Model.IFW3:
            if self.firmware_version > 2.03:
                self.serial_number = self.__read_write(
                    "WNxxxx").split(b' ')[1].strip().decode("utf-8")
                return
        self.serial_number = '****'

    def _assert_connected(self):
        if not self._connected and self.ser is not None and self.ser.is_open:
            raise Exception(
                "The IFW must be connected to perform this operation")

    def get_filter_names(self):
        '''Returns all names for the current wheel.'''
        self._assert_connected()
        res = self.__read_write("WRxxxx")
        if self.model is IFW_Model.Unknown:
            self._detect_model_from_names(len(res))

        if len(res) < 8 * self.number_of_filters():
            raise Exception(
                "Received incorrect number of characters while reading names from wheel.")

        self.filter_names.clear()

        for i in range(self.number_of_filters()):
            self.filter_names.append(res[i*8:i*8+8].decode('utf-8'))
        return self.filter_names

    def get_filter_name(self, position = None):
        '''Returns the current filter name or the specified filter name.'''
        if position is None:
            position = self.get_current_filter()
        return self.filter_names[position - 1]

    def _detect_model_from_names(self, length):   
        wheel_id = self.wheel_id
        if isinstance(wheel_id, str):
            wheel_id = bytes(wheel_id, 'utf-8')

        if wheel_id in b'ABCDE':
            if length > 42:
                self.model = IFW_Model.IFW3
            else:
                self.model = IFW_Model.IFW
        elif wheel_id in b'FGH':
            if length > 42:
                self.model = IFW_Model.IFW
            else:
                self.model = IFW_Model.IFW3
        elif wheel_id in b'IJK':
            self.model = IFW_Model.IFW
        else:
            self.model = IFW_Model.Unknown

    def number_of_filters(self, wheel_id = None, model = None):
        '''Returns the number of filters on the current Wheel.'''
        if wheel_id is None:
            wheel_id = self.wheel_id
        if model is None:
            model = self.model

        if isinstance(wheel_id, str):
            wheel_id = bytes(wheel_id, 'utf-8')
        if model is IFW_Model.IFW3:
            if wheel_id in b'AB':
                return 9
            elif wheel_id in b'CDE':
                return 6
            elif wheel_id in b'FGH':
                return 5
        else:
            if wheel_id in b'ABCDE':
                return 5
            elif wheel_id in b'FGH':
                return 8
            elif wheel_id in b'IJK':
                return 7
        return 0

    def set_filter_names(self, names, wheel_id = None, model = None):
        '''Sets the filter names for the current or specified wheel.'''
        self._assert_connected()
        if names is None:
            raise Exception("Names must not be None")
        
        if model is None:
            model = self.model

        if wheel_id is None:
            wheel_id = self.wheel_id

        if len(names) is not self.number_of_filters(wheel_id, model):
            raise Exception("You must specify the correct number of names {} for this model.".format(
                self.number_of_filters(wheel_id, model)))

        name_string = ''

        for name in names:
            if name is None:
                raise Exception("Names must not be null")
            if len(name) > 8:
                raise Exception("Names must be less then 8 characters")
            if not any(c in " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ=.#/-" for c in name):
                raise Exception("Names may only contain the following characters: {}".format(
                    " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ=.#/-"))
            name_string += name.ljust(8, ' ')

        if len(name_string) != self.number_of_filters(wheel_id, model) * 8:
            raise Exception(
                "Error storing names to wheel. Incorrect string length.")

        if isinstance(wheel_id, bytes):
            wheel_id = str(wheel_id, 'utf-8')

        if not b'!' in self.__read_write('WLxxx{0}*{1}'.format(wheel_id.strip(), name_string), 2):
            raise Exception(
                "Error Storing names to wheel, device did not respond")

        self.home()


    def get_wheel_name(self, wheel_id = None):
        '''Returns the current wheel name.'''
        if wheel_id is None:
            wheel_id = self.get_wheel_id()
        return "Wheel: {}".format(wheel_id)

    def get_wheel_names(self):
        '''Returns all wheel names'''
        wheels = []

        for i in 'ABCDEFGHIJK':
            wheels.append(self.get_wheel_name(i))

        return wheels

