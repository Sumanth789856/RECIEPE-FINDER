import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import pymysql
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from youtubesearchpython import VideosSearch
import time

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your_secret_key")
app.config['UPLOAD_FOLDER'] = 'static/uploads/videos'
app.config['PROFILE_FOLDER'] = 'static/uploads/profiles'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload size

# Ensure upload directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROFILE_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "recipe_video_app"),
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route('/')
def index():
    category = request.args.get('category', 'All')
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if category and category != 'All':
                cursor.execute("SELECT recipes.*, users.username FROM recipes JOIN users ON recipes.user_id = users.id WHERE category=%s ORDER BY created_at DESC", (category,))
            else:
                cursor.execute("SELECT recipes.*, users.username FROM recipes JOIN users ON recipes.user_id = users.id ORDER BY created_at DESC")
            recipes = cursor.fetchall()
    finally:
        conn.close()
        
    # Fetch YouTube videos
    youtube_recipes = []
    try:
        search_query = (category if category and category != 'All' else "popular") + " recipe"
        videosSearch = VideosSearch(search_query, limit = 8)
        youtube_recipes = videosSearch.result().get('result', [])
    except Exception as e:
        print(f"YouTube search error: {e}")
            
    return render_template('index.html', recipes=recipes, youtube_recipes=youtube_recipes, active_category=category)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
                if cursor.fetchone():
                    flash('Username already exists!', 'danger')
                else:
                    cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, 'user')", (username, hashed_pw))
                    conn.commit()
                    flash('Registration successful! Please login.', 'success')
                    return redirect(url_for('login'))
        except Exception as e:
            flash(f"Error: {str(e)}", 'danger')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
                user = cursor.fetchone()
                
                if user and check_password_hash(user['password'], password):
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['role'] = user['role']
                    flash('Logged in successfully!', 'success')
                    return redirect(url_for('dashboard' if user['role'] == 'admin' else 'index'))
                else:
                    flash('Invalid credentials!', 'danger')
        finally:
            conn.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload_recipe():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        
        if 'video' not in request.files:
            flash('No video file part', 'danger')
            return redirect(request.url)
            
        file = request.files['video']
        
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Add timestamp to filename to prevent duplicates
            import time
            filename = f"{int(time.time())}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
            conn = get_db_connection()
            try:
                category = request.form.get('category', 'Other')
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO recipes (title, description, video_filename, category, user_id) VALUES (%s, %s, %s, %s, %s)",
                        (title, description, filename, category, session['user_id'])
                    )
                    conn.commit()
                flash('Recipe uploaded successfully!', 'success')
                return redirect(url_for('index'))
            finally:
                conn.close()
        else:
            flash('Allowed file types are mp4, avi, mov, wmv', 'danger')
            
    return render_template('upload_recipe.html')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_recipe(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM recipes WHERE id=%s", (id,))
            recipe = cursor.fetchone()
            
            if not recipe:
                flash('Recipe not found.', 'danger')
                return redirect(url_for('dashboard'))
                
            # Permission check: Admin or Owner
            if session['role'] != 'admin' and recipe['user_id'] != session['user_id']:
                flash('Permission denied.', 'danger')
                return redirect(url_for('dashboard'))
                
            if request.method == 'POST':
                title = request.form['title']
                description = request.form['description']
                
                # Update video if new one is uploaded
                new_video_filename = recipe['video_filename']
                if 'video' in request.files:
                    file = request.files['video']
                    if file and file.filename != '' and allowed_file(file.filename):
                        # Delete old video
                        old_video_path = os.path.join(app.config['UPLOAD_FOLDER'], recipe['video_filename'])
                        if os.path.exists(old_video_path):
                            os.remove(old_video_path)
                            
                        filename = secure_filename(file.filename)
                        filename = f"{int(time.time())}_{filename}"
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        new_video_filename = filename

                category = request.form.get('category', recipe['category'])
                
                cursor.execute(
                    "UPDATE recipes SET title=%s, description=%s, video_filename=%s, category=%s WHERE id=%s",
                    (title, description, new_video_filename, category, id)
                )
                conn.commit()
                flash('Recipe updated successfully!', 'success')
                return redirect(url_for('dashboard'))
    finally:
        conn.close()
            
    return render_template('edit_recipe.html', recipe=recipe)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if session['role'] == 'admin':
                # Admin sees all recipes
                 cursor.execute("SELECT recipes.*, users.username FROM recipes JOIN users ON recipes.user_id = users.id ORDER BY created_at DESC")
            else:
                # User sees only their recipes
                cursor.execute("SELECT * FROM recipes WHERE user_id=%s ORDER BY created_at DESC", (session['user_id'],))
            recipes = cursor.fetchall()
    finally:
        conn.close()
        
    return render_template('dashboard.html', recipes=recipes)

@app.route('/delete/<int:id>')
def delete_recipe(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Check ownership or admin status before deleting
            cursor.execute("SELECT * FROM recipes WHERE id=%s", (id,))
            recipe = cursor.fetchone()
            
            if recipe:
                if session['role'] == 'admin' or recipe['user_id'] == session['user_id']:
                    # Delete file
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], recipe['video_filename'])
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        
                    cursor.execute("DELETE FROM recipes WHERE id=%s", (id,))
                    conn.commit()
                    flash('Recipe deleted successfully.', 'success')
                else:
                    flash('Permission denied.', 'danger')
            else:
                flash('Recipe not found.', 'danger')
    finally:
        conn.close()

    return redirect(url_for('dashboard'))

@app.route('/search')
def search():
    query = request.args.get('q', '')
    local_recipes = []
    youtube_recipes = []
    
    if query:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Search in local records
                cursor.execute("SELECT recipes.*, users.username FROM recipes JOIN users ON recipes.user_id = users.id WHERE title LIKE %s OR description LIKE %s", (f"%{query}%", f"%{query}%"))
                local_recipes = cursor.fetchall()
        finally:
            conn.close()
            
        # Always search YouTube as well
        try:
            videosSearch = VideosSearch(query + " recipe", limit = 10)
            results = videosSearch.result()
            youtube_recipes = results.get('result', [])
        except Exception as e:
            print(f"YouTube search error: {e}")
            youtube_recipes = []
            
    return render_template('index.html', recipes=local_recipes, youtube_recipes=youtube_recipes, query=query)

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
            user = cursor.fetchone()
    finally:
        conn.close()
    return render_template('profile.html', user=user)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    gender = request.form.get('gender')
    phone_number = request.form.get('phone_number')
    
    profile_photo = None
    if 'profile_photo' in request.files:
        file = request.files['profile_photo']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            filename = f"{int(time.time())}_{filename}"
            file.save(os.path.join(app.config['PROFILE_FOLDER'], filename))
            profile_photo = filename

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if profile_photo:
                cursor.execute(
                    "UPDATE users SET full_name=%s, email=%s, gender=%s, phone_number=%s, profile_photo=%s WHERE id=%s",
                    (full_name, email, gender, phone_number, profile_photo, session['user_id'])
                )
            else:
                cursor.execute(
                    "UPDATE users SET full_name=%s, email=%s, gender=%s, phone_number=%s WHERE id=%s",
                    (full_name, email, gender, phone_number, session['user_id'])
                )
            conn.commit()
        flash('Profile updated successfully!', 'success')
    except Exception as e:
        flash(f"Error updating profile: {str(e)}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('profile'))

@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, username, full_name, email, role, created_at FROM users ORDER BY created_at DESC")
            users = cursor.fetchall()
    finally:
        conn.close()
    return render_template('admin_users.html', users=users)

@app.route('/admin/toggle_role/<int:user_id>')
def toggle_role(user_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Don't let admin change their own role
            if user_id == session['user_id']:
                flash('You cannot change your own role!', 'danger')
                return redirect(url_for('admin_users'))
                
            cursor.execute("SELECT role FROM users WHERE id=%s", (user_id,))
            user = cursor.fetchone()
            if user:
                new_role = 'admin' if user['role'] == 'user' else 'user'
                cursor.execute("UPDATE users SET role=%s WHERE id=%s", (new_role, user_id))
                conn.commit()
                flash('User role updated!', 'success')
    finally:
        conn.close()
    return redirect(url_for('admin_users'))

@app.route('/admin/delete_user/<int:user_id>')
def delete_user(user_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if user_id == session['user_id']:
                flash('You cannot delete yourself!', 'danger')
                return redirect(url_for('admin_users'))
                
            cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
            conn.commit()
            flash('User deleted successfully.', 'success')
    finally:
        conn.close()
    return redirect(url_for('admin_users'))

if __name__ == '__main__':
    app.run(debug=True)
