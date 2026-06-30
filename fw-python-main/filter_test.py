 
import fw
import time

def print_wheel_data(the_wheel):
	print('----------------------')
	print(the_wheel.position_num)
	print(the_wheel.position_name)
	print(the_wheel.last_command)
	print(the_wheel.last_response)
	print(the_wheel.last_error)
	print('----------------------')
	print()

wheel = fw.FilterWheel('definition_file.csv')
print_wheel_data(wheel)
time.sleep(5)

print(wheel.set_position('2'))
print_wheel_data(wheel)
time.sleep(5)

print(wheel.set_position('D'))
print_wheel_data(wheel)
time.sleep(5)

print(wheel.set_position('wrong'))
print_wheel_data(wheel)
time.sleep(5)

print(wheel.home())
print_wheel_data(wheel)

