from database.prepper import wake_up_server
from database.database import get_connection


print("Connection initiated")
wake_up_server()

def test_connection():
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 AS test_value;")

            row = cursor.fetchone()

            if row and row.test_value == 1:
                print("Azure SQL connection successful.")
                return True

            print("Azure SQL connection test returned an unexpected result.")
            return False

    except Exception as e:
        print("Azure SQL connection failed.")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")
        return False
    
test_connection()