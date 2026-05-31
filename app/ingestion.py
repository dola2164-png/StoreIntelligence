import pandas as pd

# Load transactions
transactions = pd.read_csv("../data/transactions.csv")

# Load store layout (Excel or CSV)
try:
    layout = pd.read_excel("../data/store_layout.xlsx")
except:
    layout = pd.read_csv("../data/store_layout.csv")

print("Transactions loaded:", transactions.shape)
print("Layout loaded:", layout.shape)
