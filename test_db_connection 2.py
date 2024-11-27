import psycopg2

try:
    connection = psycopg2.connect(
        dbname='secrets', 
        user='mohamed', 
        host='localhost', 
        password='MySecrets'
    )
    print("Connection successful")
except Exception as e:
    print(f"Connection failed: {e}")
