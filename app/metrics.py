import pandas as pd

def compute_gmv(df):
    return df["GMV"].sum()

def compute_nmv(df):
    return df["NMV"].sum()

def promo_effectiveness(df):
    return df.groupby("offer_name")["GMV"].sum().to_dict()

if __name__ == "__main__":
    df = pd.read_csv("../data/transactions.csv")
    print("Total GMV:", compute_gmv(df))
    print("Total NMV:", compute_nmv(df))
    print("Promo Effectiveness:", promo_effectiveness(df))
