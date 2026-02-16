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
    sort_by = request.args.get('sort', 'newest')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Base query with view and like counts
            query = """
                SELECT recipes.*, users.username, 
                (SELECT COUNT(*) FROM recipe_likes WHERE recipe_id = recipes.id) as like_count,
                (SELECT COUNT(*) FROM recipe_likes WHERE recipe_id = recipes.id AND user_id = %s) as user_liked
                FROM recipes 
                JOIN users ON recipes.user_id = users.id
            """
            params = [session.get('user_id', 0)]
            
            if category and category != 'All':
                query += " WHERE category=%s"
                params.append(category)
            
            # Ranking/Sorting
            if sort_by == 'oldest':
                query += " ORDER BY created_at ASC"
            elif sort_by == 'shortest':
                query += " ORDER BY cooking_time ASC"
            elif sort_by == 'longest':
                query += " ORDER BY cooking_time DESC"
            else:
                query += " ORDER BY created_at DESC"
                
            cursor.execute(query, tuple(params))
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
            
    return render_template('index.html', recipes=recipes, youtube_recipes=youtube_recipes, active_category=category, sort_by=sort_by)

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
        ingredients = request.form['ingredients']
        instructions = request.form['instructions']
        description = request.form.get('description', '')
        
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
            
            try:
                category = request.form.get('category', 'Other')
                cooking_time = request.form.get('cooking_time', 0)
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO recipes (title, description, ingredients, instructions, video_filename, category, cooking_time, user_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (title, description, ingredients, instructions, filename, category, cooking_time, session['user_id'])
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
                ingredients = request.form['ingredients']
                instructions = request.form['instructions']
                description = request.form.get('description', '')
                
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
                cooking_time = request.form.get('cooking_time', recipe['cooking_time'])
                
                cursor.execute(
                    "UPDATE recipes SET title=%s, description=%s, ingredients=%s, instructions=%s, video_filename=%s, category=%s, cooking_time=%s WHERE id=%s",
                    (title, description, ingredients, instructions, new_video_filename, category, cooking_time, id)
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
    category = request.args.get('category', 'All')
    sort_by = request.args.get('sort', 'relevance')
    
    local_recipes = []
    youtube_recipes = []
    
    if query:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Search in local records with stats
                sql = """
                    SELECT recipes.*, users.username, 
                    (SELECT COUNT(*) FROM recipe_likes WHERE recipe_id = recipes.id) as like_count,
                    (SELECT COUNT(*) FROM recipe_likes WHERE recipe_id = recipes.id AND user_id = %s) as user_liked
                    FROM recipes 
                    JOIN users ON recipes.user_id = users.id 
                    WHERE (title LIKE %s OR description LIKE %s)
                """
                params = [session.get('user_id', 0), f"%{query}%", f"%{query}%"]
                
                if category != 'All':
                    sql += " AND category = %s"
                    params.append(category)
                    
                if sort_by == 'oldest':
                    sql += " ORDER BY created_at ASC"
                elif sort_by == 'shortest':
                    sql += " ORDER BY cooking_time ASC"
                elif sort_by == 'longest':
                    sql += " ORDER BY cooking_time DESC"
                else:
                    sql += " ORDER BY created_at DESC"
                    
                cursor.execute(sql, tuple(params))
                local_recipes = cursor.fetchall()
        finally:
            conn.close()
            
        # YouTube search
        try:
            yt_query = f"{query} {category if category != 'All' else ''} recipe"
            videosSearch = VideosSearch(yt_query, limit = 10)
            youtube_recipes = videosSearch.result().get('result', [])
        except Exception as e:
            print(f"YouTube search error: {e}")
            
    return render_template('index.html', recipes=local_recipes, youtube_recipes=youtube_recipes, query=query, active_category=category, sort_by=sort_by)

@app.route('/like/<int:recipe_id>', methods=['POST'])
def toggle_like(recipe_id):
    if 'user_id' not in session:
        return {"error": "Authentication required"}, 401
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM recipe_likes WHERE recipe_id=%s AND user_id=%s", (recipe_id, session['user_id']))
            like = cursor.fetchone()
            
            if like:
                cursor.execute("DELETE FROM recipe_likes WHERE id=%s", (like['id'],))
                liked = False
            else:
                cursor.execute("INSERT INTO recipe_likes (recipe_id, user_id) VALUES (%s, %s)", (recipe_id, session['user_id']))
                liked = True
            
            cursor.execute("SELECT COUNT(*) as count FROM recipe_likes WHERE recipe_id=%s", (recipe_id,))
            count = cursor.fetchone()['count']
            conn.commit()
            return {"liked": liked, "count": count}
    finally:
        conn.close()

@app.route('/view/<int:recipe_id>', methods=['POST'])
def increment_view(recipe_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE recipes SET views = views + 1 WHERE id=%s", (recipe_id,))
            conn.commit()
            return {"status": "success"}
    finally:
        conn.close()

@app.route('/comments/<int:recipe_id>')
def get_comments(recipe_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT comments.*, users.username, users.profile_photo 
                FROM comments 
                JOIN users ON comments.user_id = users.id 
                WHERE recipe_id = %s 
                ORDER BY created_at DESC
            """, (recipe_id,))
            comments = cursor.fetchall()
            # Convert datetime to string for JSON serialization
            for c in comments:
                c['created_at'] = c['created_at'].strftime('%b %d, %H:%M')
            return {"comments": comments}
    finally:
        conn.close()

@app.route('/comment/post', methods=['POST'])
def post_comment():
    if 'user_id' not in session:
        return {"error": "Authentication required"}, 401
    
    recipe_id = request.form.get('recipe_id')
    comment_text = request.form.get('comment')
    
    if not comment_text:
        return {"error": "Comment cannot be empty"}, 400
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO comments (recipe_id, user_id, comment) VALUES (%s, %s, %s)",
                (recipe_id, session['user_id'], comment_text)
            )
            conn.commit()
            return {"status": "success"}
    finally:
        conn.close()

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
    age = request.form.get('age')
    
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
                    "UPDATE users SET full_name=%s, email=%s, gender=%s, phone_number=%s, age=%s, profile_photo=%s WHERE id=%s",
                    (full_name, email, gender, phone_number, age, profile_photo, session['user_id'])
                )
            else:
                cursor.execute(
                    "UPDATE users SET full_name=%s, email=%s, gender=%s, phone_number=%s, age=%s WHERE id=%s",
                    (full_name, email, gender, phone_number, age, session['user_id'])
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
