import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

CSV_PATH = "/app/creditcard.csv"

conn = psycopg2.connect(
    host="db",
    port=5432,
    database="upi_fraud_db",
    user="postgres",
    password="postgres"
)

cursor = conn.cursor()

print("Database connected successfully!", flush=True)

insert_query = """
INSERT INTO transactions (
    transaction_time,
    amount,
    v1, v2, v3, v4, v5, v6, v7, v8, v9, v10,
    v11, v12, v13, v14, v15, v16, v17, v18, v19,
    v20, v21, v22, v23, v24, v25, v26, v27, v28,
    actual_class
)
VALUES %s
"""

columns = (
    ["transaction_time", "amount"]
    + [f"v{i}" for i in range(1, 29)]
    + ["actual_class"]
)

batch_size = 5000
total = 0

print("Loading CSV in chunks...", flush=True)

for df in pd.read_csv(CSV_PATH, chunksize=batch_size):

    df = df.rename(columns={
        "Time": "transaction_time",
        "Amount": "amount",
        "Class": "actual_class"
    })

    df = df.rename(columns={
        f"V{i}": f"v{i}" for i in range(1, 29)
    })

    df = df[columns]

    records = list(
        df.itertuples(index=False, name=None)
    )

    execute_values(
        cursor,
        insert_query,
        records,
        page_size=batch_size
    )

    conn.commit()

    total += len(records)

    print(
        f"Inserted {total} / 284807 rows",
        flush=True
    )

cursor.close()
conn.close()

print("Data loading completed successfully!", flush=True)




