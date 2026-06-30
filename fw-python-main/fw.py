import ifw 
import hsfw
import time
import copy
import fw_test
import pandas as pd
# make error reset if command is successful
# allow integer for position input
# check for command completion every 0.5 seconds for 5 seconds before time out
'''
t0 = time.time()
while time.time() - t0 < 5:
	time.sleep(0.5)
	check something
	if good, t0 = 0

'''
class FilterWheel:

	def __init__(self, definition_file):
		self.last_command: str = ""  # may not be useful
		self.last_response: str = "" # may not be useful
		self.timeout:       int = 2
		self.retries:       int = 3
		self.last_error: str = "" 
		self.wheel = None
		self.init = False
		self.filter_list: list = []
		self.position_num: int = 0
		self.position_name: str = ""
		
		try:
			df = pd.read_csv(definition_file, dtype=str)
			print("File read successfully!")
			self.filter_list = df['Filter_Name'].tolist() 
			print(self.filter_list)
			
			# Initialize connection with the physical filter wheel
			sns = hsfw.HSFW.get_serial_numbers()
			if sns:
				print(f"Connecting to HSFW Serial: {sns[0]}")
				self.wheel = hsfw.HSFW(sns[0])
				self.wheel.clear_error()
			else:
				print("No HSFW USB devices found. Attempting connection to IFW serial port...")
				self.wheel = ifw.IFW('/dev/ttyAMA10')
				
			self.init = True
			self.home() 
			self.position_num = 0
			self.position_name = self.filter_list[0]
				
		except FileNotFoundError: 
			self.init = False
			self.last_error = "ERROR: Filter definition file missing/malformed"
		except Exception as e:
			self.init = False
			self.last_error = f"ERROR: Initialization failed: {e}"
		
	def home(self):
		if self.init:
			try:
				if self.wheel:
					self.wheel.home()
					# Check for command completion every 0.5 seconds for 5 seconds before timeout
					t0 = time.time()
					success = False
					while time.time() - t0 < 5:
						time.sleep(0.5)
						if not self.wheel.is_homing:
							if self.wheel.is_homed:
								success = True
								break
					if not success:
						raise Exception("Homing timed out after 5 seconds")
				
				self.last_command = "Home the wheel" 
				self.last_response = "Wheel homed"
				self.position_num = 0
				self.position_name = self.filter_list[0]
				self.last_error = ""  # Reset error if command is successful
				return 1
			except Exception as e:
				self.last_error = f"ERROR: Homing failed: {e}"
				return 0
		else:
			self.last_response = "ERROR: Initialization failed"
			return 0 
		
	def set_position(self, parameter):
		if self.init: 
			is_digit = False
			pos_idx = -1
			
			# Allow integer for position input
			if isinstance(parameter, int):
				is_digit = True
				pos_idx = parameter - 1
			elif isinstance(parameter, str) and parameter.isdigit():
				is_digit = True
				pos_idx = int(parameter) - 1

			if is_digit: 
				if 0 <= pos_idx < len(self.filter_list):
					try:
						if self.wheel:
							self.wheel.move_to_filter(pos_idx + 1)
							# Check for command completion every 0.5 seconds for 5 seconds before timeout
							t0 = time.time()
							success = False
							while time.time() - t0 < 5:
								time.sleep(0.5)
								if not self.wheel.is_moving:
									if self.wheel.get_current_filter() == pos_idx + 1:
										success = True
										break
							if not success:
								raise Exception("Filter wheel movement timed out after 5 seconds")
								
						self.position_num = pos_idx
						self.position_name = self.filter_list[pos_idx] 
						self.last_command = f"Set position to {self.position_num + 1}, {self.position_name}"
						self.last_response = f"Position set to {self.position_num}"
						self.last_error = ""  # Reset error if command is successful
						return 1
					except Exception as e:
						self.last_error = f"ERROR: Move failed: {e}"
						return 0
				else:
					self.last_error = "ERROR: parameter out of range."
					return 0
			elif isinstance(parameter, str) and parameter in self.filter_list:
				pos_idx = self.filter_list.index(parameter)
				try:
					if self.wheel:
						self.wheel.move_to_filter(pos_idx + 1)
						# Check for command completion every 0.5 seconds for 5 seconds before timeout
						t0 = time.time()
						success = False
						while time.time() - t0 < 5:
							time.sleep(0.5)
							if not self.wheel.is_moving:
								if self.wheel.get_current_filter() == pos_idx + 1:
									success = True
									break
						if not success:
							raise Exception("Filter wheel movement timed out after 5 seconds")
							
					self.position_num = pos_idx
					self.position_name = parameter
					self.last_command = f"Set position to {self.position_num + 1}, {self.position_name}"
					self.last_response = f"Position set to {self.position_num}"
					self.last_error = ""  # Reset error if command is successful
					return 1
				except Exception as e:
					self.last_error = f"ERROR: Move failed: {e}"
					return 0
			else: 
				self.last_error = "ERROR: parameter not in the list"
				return 0
		else: 
			self.last_response = "ERROR: Initialization failed"
			return 0 
