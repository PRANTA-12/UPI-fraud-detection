import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

# --------------------------------------------------
# 1. CSV PATH
# --------------------------------------------------

CSV_PATH = r"C:\Users\IT_SHOP\project\creditcard.csv"


# --------------------------------------------------
# 2. DATABASE CONNECTION
# --------------------------------------------------

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="upi_fraud_db",
    user="postgres",
    password="Pranta@123"
)

cursor = conn.cursor()

print("Database connected successfully!")


# --------------------------------------------------
# 3. READ CSV
# --------------------------------------------------

print("Loading CSV...")

df = pd.read_csv(CSV_PATH)

print("CSV loaded successfully!")
print("Rows:", len(df))
print("Columns:", len(df.columns))


# --------------------------------------------------
# 4. PREPARE DATA
# --------------------------------------------------

df = df.rename(columns={
    "Time": "transaction_time",
    "Amount": "amount",
    "Class": "actual_class"
})

df = df.rename(columns={
    f"V{i}": f"v{i}" for i in range(1, 29)
})


# --------------------------------------------------
# 5. SELECT DATABASE COLUMNS
# --------------------------------------------------

columns = [
    "transaction_time",
    "amount"
]

columns += [f"v{i}" for i in range(1, 29)]

columns.append("actual_class")

df = df[columns]


# --------------------------------------------------
# 6. CONVERT DATAFRAME TO RECORDS
# --------------------------------------------------

records = list(df.itertuples(index=False, name=None))

print("Records prepared:", len(records))


# --------------------------------------------------
# 7. INSERT DATA
# --------------------------------------------------

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

print("Inserting data into PostgreSQL...")

batch_size = 5000

for start in range(0, len(records), batch_size):

    batch = records[start:start + batch_size]

    execute_values(
        cursor,
        insert_query,
        batch,
        page_size=batch_size
    )

    conn.commit()

    print(
        f"Inserted {min(start + batch_size, len(records))} "
        f"/ {len(records)} rows"
    )


# --------------------------------------------------
# 8. CLOSE CONNECTION
# --------------------------------------------------

cursor.close()
conn.close()

print("\nData loading completed successfully!")