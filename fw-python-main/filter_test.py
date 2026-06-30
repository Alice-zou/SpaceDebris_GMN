import fw
import time

def print_wheel_data(the_wheel):
	print("+" + "="*45 + "+")
	print(f"| Position (0-based Index): {the_wheel.position_num}")
	print(f"| Position Name          : {the_wheel.position_name}")
	print(f"| Last Command           : {the_wheel.last_command}")
	print(f"| Last Response          : {the_wheel.last_response}")
	print(f"| Last Error             : {repr(the_wheel.last_error) if the_wheel.last_error else 'None'}")
	print("+" + "="*45 + "+")
	print()

print("Initializing Filter Wheel...")
wheel = fw.FilterWheel('definition_file.csv')
print_wheel_data(wheel)

print(">>> Command: Set position to string '2'")
status = wheel.set_position('2')
print(f"Command Status: {'SUCCESS' if status else 'FAILED'}")
print_wheel_data(wheel)

print(">>> Command: Set position to string 'D'")
status = wheel.set_position('D')
print(f"Command Status: {'SUCCESS' if status else 'FAILED'}")
print_wheel_data(wheel)

print(">>> Command: Set position to integer 3 (new feature)")
status = wheel.set_position(3)
print(f"Command Status: {'SUCCESS' if status else 'FAILED'}")
print_wheel_data(wheel)

print(">>> Command: Set position to 'wrong' (should fail)")
status = wheel.set_position('wrong')
print(f"Command Status: {'SUCCESS' if status else 'FAILED'}")
print_wheel_data(wheel)

print(">>> Command: Home the wheel")
status = wheel.home()
print(f"Command Status: {'SUCCESS' if status else 'FAILED'}")
print_wheel_data(wheel)
