import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="upi_fraud_db",
    user="postgres",
    password="Pranta@123"
)

cursor = conn.cursor()

# Create transactions table
cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id SERIAL PRIMARY KEY,
    transaction_time DOUBLE PRECISION,
    amount NUMERIC(12,2),

    v1 DOUBLE PRECISION,
    v2 DOUBLE PRECISION,
    v3 DOUBLE PRECISION,
    v4 DOUBLE PRECISION,
    v5 DOUBLE PRECISION,
    v6 DOUBLE PRECISION,
    v7 DOUBLE PRECISION,
    v8 DOUBLE PRECISION,
    v9 DOUBLE PRECISION,
    v10 DOUBLE PRECISION,
    v11 DOUBLE PRECISION,
    v12 DOUBLE PRECISION,
    v13 DOUBLE PRECISION,
    v14 DOUBLE PRECISION,
    v15 DOUBLE PRECISION,
    v16 DOUBLE PRECISION,
    v17 DOUBLE PRECISION,
    v18 DOUBLE PRECISION,
    v19 DOUBLE PRECISION,
    v20 DOUBLE PRECISION,
    v21 DOUBLE PRECISION,
    v22 DOUBLE PRECISION,
    v23 DOUBLE PRECISION,
    v24 DOUBLE PRECISION,
    v25 DOUBLE PRECISION,
    v26 DOUBLE PRECISION,
    v27 DOUBLE PRECISION,
    v28 DOUBLE PRECISION,

    actual_class INTEGER
);
""")

# Create fraud predictions table
cursor.execute("""
CREATE TABLE IF NOT EXISTS fraud_predictions (
    prediction_id SERIAL PRIMARY KEY,
    transaction_id INTEGER REFERENCES transactions(transaction_id),

    fraud_probability DOUBLE PRECISION,
    predicted_class INTEGER,

    model_name VARCHAR(50),
    threshold DOUBLE PRECISION,

    prediction_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

conn.commit()

print("Tables created successfully!")

cursor.close()
conn.close()