# CSV file 
import pandas as pd

data = {
	'Filter_Position': ['1', '2', '3', '4', '5'],
	'Filter_Name': ['UV', 'Natural Light', 'C', 'D', 'E']
}

df = pd.DataFrame(data)

df.to_csv('definition_file.csv', index=False)
print("definition_file written successfully.")
