import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "7842909856a@A")
DB_NAME = os.getenv("DB_NAME", "recipe_video_app")

def create_database():
    # Connect to MySQL server (no database selected yet)
    try:
        conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD)
        cursor = conn.cursor()
        
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        print(f"Database '{DB_NAME}' checked/created.")
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error creating database: {e}")
        return

def create_tables():
    try:
        conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            email VARCHAR(100),
            gender VARCHAR(20),
            phone_number VARCHAR(20),
            profile_photo VARCHAR(255),
            role ENUM('user', 'admin') DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        print("Users table checked/created.")
        
        # Add new columns if they don't exist
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN full_name VARCHAR(100) AFTER username")
        except: pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN email VARCHAR(100) AFTER password")
        except: pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN gender VARCHAR(20) AFTER email")
        except: pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN phone_number VARCHAR(20) AFTER gender")
        except: pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN profile_photo VARCHAR(255) AFTER phone_number")
        except: pass

        # Create recipes table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(100) NOT NULL,
            description TEXT NOT NULL,
            video_filename VARCHAR(255),
            category VARCHAR(50),
            user_id INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)
        print("Recipes table checked/created.")

        # Add category column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE recipes ADD COLUMN category VARCHAR(50) AFTER video_filename")
            print("Category column added to recipes table.")
        except: pass

        # Check if admin exists, if not create one
        cursor.execute("SELECT * FROM users WHERE role='admin'")
        if not cursor.fetchone():
            # Create a default admin
            from werkzeug.security import generate_password_hash
            hashed_pw = generate_password_hash("admin123")
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", ('admin', hashed_pw, 'admin'))
            print("Default admin created (username: admin, password: admin123)")
            conn.commit()

        conn.commit()
        cursor.close()
        conn.close()
        print("Database setup complete.")
    except Exception as e:
        print(f"Error setting up tables: {e}")

if __name__ == "__main__":
    create_database()
    create_tables()
