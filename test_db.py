import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="upi_fraud_db",
    user="postgres",
    password="Pranta@123"
)

cursor = conn.cursor()

print("Database connected successfully!")

# Check tables
cursor.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name;
""")

tables = cursor.fetchall()

print("\nTables:")
for table in tables:
    print("-", table[0])

# Check total transactions
cursor.execute("""
    SELECT COUNT(*)
    FROM transactions;
""")

total_transactions = cursor.fetchone()[0]

print("\nTotal transactions:", total_transactions)

# Check fraud distribution
cursor.execute("""
    SELECT
        actual_class,
        COUNT(*)
    FROM transactions
    GROUP BY actual_class
    ORDER BY actual_class;
""")

distribution = cursor.fetchall()

print("\nTransaction distribution:")
for row in distribution:
    print(row)

cursor.close()
conn.close()