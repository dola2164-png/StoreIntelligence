# anomalies.py
import pandas as pd

def detect_anomalies(df):
    """
    Detect transactions with unusually high GMV.
    """
    threshold = df["GMV"].mean() + 2 * df["GMV"].std()
    anomalies = df[df["GMV"] > threshold]
    return anomalies

if __name__ == "__main__":
    df = pd.read_csv("../data/transactions.csv")
    print(detect_anomalies(df))
