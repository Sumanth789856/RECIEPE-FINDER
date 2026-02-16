import psycopg2
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def setup_database():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            full_name VARCHAR(100),
            email VARCHAR(100),
            gender VARCHAR(20),
            age INT,
            phone_number VARCHAR(20),
            profile_photo VARCHAR(255),
            role VARCHAR(20) DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        print("Users table checked/created.")

        # Create recipes table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id SERIAL PRIMARY KEY,
            title VARCHAR(100) NOT NULL,
            description TEXT,
            ingredients TEXT,
            instructions TEXT,
            video_filename VARCHAR(255),
            category VARCHAR(50),
            cooking_time INT DEFAULT 0,
            views INT DEFAULT 0,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        print("Recipes table checked/created.")

        # Create recipe_likes table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS recipe_likes (
            id SERIAL PRIMARY KEY,
            recipe_id INT REFERENCES recipes(id) ON DELETE CASCADE,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(recipe_id, user_id)
        )
        """)
        print("Recipe likes table checked/created.")

        # Create comments table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            recipe_id INT REFERENCES recipes(id) ON DELETE CASCADE,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            comment TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        print("Comments table checked/created.")

        # Check if admin exists, if not create one
        cursor.execute("SELECT * FROM users WHERE role='admin'")
        if not cursor.fetchone():
            hashed_pw = generate_password_hash("admin123")
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", ('admin', hashed_pw, 'admin'))
            print("Default admin created (username: admin, password: admin123)")

        conn.commit()
        cursor.close()
        conn.close()
        print("PostgreSQL Database setup complete.")
    except Exception as e:
        print(f"Error setting up database: {e}")

if __name__ == "__main__":
    if not DATABASE_URL:
        print("Error: DATABASE_URL not found in .env")
    else:
        setup_database()
