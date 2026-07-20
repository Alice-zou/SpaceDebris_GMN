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

	# Begin Robinson Space Debris edit 2026-07-20 by Alice Zou
	# The UV:visible cadence now comes from the RMS config file (Capture/num_uv_measurements and
	# Capture/num_vis_measurements) and is passed in here. The defaults below match what used to be
	# hardcoded, so callers that do not pass a cadence (filter_cycle.py, fw_test.py) are unaffected.
	def __init__(self, definition_file, num_uv_measurements=3, num_vis_measurements=2):
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
		self.num_uv_measurements  = max(1, int(num_uv_measurements))
		self.num_vis_measurements = max(1, int(num_vis_measurements))
		self.num_uv_counter  = 0
	# End Robinson Space Debris
		
	#	f = file('/home/rms/Desktop/filter_wheel_last_init.txt', 'w')
	#	f.write(time.time())
	#	f.close()
		
		
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

	def check_in(self):
#		if log_file_path[-1] != '/':
#			log_file_path = log_file_path + '/'
		log_file_path = '/home/rms/Desktop/filter_wheel.csv'
		# Begin Robinson Space Debris edit 2026-07-20 by Alice Zou
		# Was "self.self.position_name" (AttributeError) and "/n" instead of a newline.
		with open(log_file_path, 'a') as f:
			f.write(str(time.time()) + ', ' + str(self.position_name) + '\n')
		# End Robinson Space Debris

		# Begin Robinson Space Debris edit 2026-07-20 by Alice Zou
		# The measurement just logged above counts towards the active filter's quota, so the switch
		# fires once the quota is reached (">=", not ">"): num_uv_measurements: 3 now yields exactly
		# 3 UV rows per cycle. The old ">" gave one extra block in each filter.
		self.num_uv_counter += 1
		if self.position_name == 'UV':
			if self.num_uv_counter >= self.num_uv_measurements:
				self.num_uv_counter = 0
				self.set_position('Open')
		else:
			if self.num_uv_counter >= self.num_vis_measurements:
				self.num_uv_counter = 0
				self.set_position('UV')
		# End Robinson Space Debris

	def home(self):
		if self.init:
			try:
				if self.wheel:
					self.wheel.home()
					# Always check for command completion every 0.5 seconds for a full 5 seconds before returning
					success = False
					for _ in range(10):
						time.sleep(0.5)
						if not self.wheel.is_homing:
							if self.wheel.is_homed:
								success = True
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
							# Always check for command completion every 0.5 seconds for a full 5 seconds before returning
							success = False
							for _ in range(10):
								time.sleep(0.5)
								if not self.wheel.is_moving:
									if self.wheel.get_current_filter() == pos_idx + 1:
										success = True
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
						# Always check for command completion every 0.5 seconds for a full 5 seconds before returning
						success = False
						for _ in range(10):
							time.sleep(0.5)
							if not self.wheel.is_moving:
								if self.wheel.get_current_filter() == pos_idx + 1:
									success = True
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
