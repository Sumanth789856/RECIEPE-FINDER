# Recipe Video App

A Flask web application for sharing and viewing recipe videos.

## Features
- **User Authentication**: Register and login for secure access.
- **Admin Dashboard**: Admins can view and delete all videos.
- **Recipe Upload**: Users can upload their own recipe videos with descriptions.
- **Video Player**: Modern video player for viewing recipes.
- **Responsive Design**: Beautiful dark-themed UI.

## Setup Instructions

### 1. Database Setup
Ensure you have MySQL installed and running.
Create a database (default name: `recipe_video_app`) or let the script do it.

Edit the `.env` file with your database credentials:
```
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=recipe_video_app
SECRET_KEY=your_secret_key
```

### 2. Install Dependencies
Open a terminal in this folder and run:
```bash
pip install -r requirements.txt
```

### 3. Initialize Database
Run the setup script to create the necessary tables and default admin account:
```bash
python db_setup.py
```
*Note: A default admin account will be created with username: `admin` and password: `admin123`.*

### 4. Run the Application
Start the Flask development server:
```bash
python app.py
```

Visit `http://127.0.0.1:5000` in your browser.

## Project Structure
- `app.py`: Main application logic.
- `db_setup.py`: Database initialization script.
- `templates/`: HTML files.
- `static/css/`: Styling.
- `static/uploads/`: Storage for uploaded videos.
