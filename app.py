import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from youtubesearchpython import VideosSearch
import time
import json
from urllib.request import urlopen, Request
from urllib.parse import quote
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

load_dotenv()

# Cloudinary is automatically configured via the CLOUDINARY_URL environment variable
cloudinary.config(secure=True)

def upload_to_cloudinary(file, resource_type="auto"):
    if not file:
        return None
    try:
        upload_result = cloudinary.uploader.upload(file, resource_type=resource_type)
        return upload_result['secure_url']
    except Exception as e:
        print(f"Cloudinary upload error: {e}")
        return None

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your_secret_key")

# Cache for suggestions to improve speed
SUGGESTION_CACHE = {}
CACHE_TIMEOUT = 300 # 5 minutes
app.config['UPLOAD_FOLDER'] = 'static/uploads/videos'
app.config['PROFILE_FOLDER'] = 'static/uploads/profiles'
app.config['THUMBNAIL_FOLDER'] = 'static/uploads/thumbnails'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload size

# Ensure upload directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROFILE_FOLDER'], exist_ok=True)
os.makedirs(app.config['THUMBNAIL_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_image(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def get_db_connection():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=RealDictCursor
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
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        gender = request.form.get('gender')
        age = request.form.get('age')
        phone_number = request.form.get('phone_number')
        
        hashed_pw = generate_password_hash(password)
        
        profile_photo = None
        if 'profile_photo' in request.files:
            file = request.files['profile_photo']
            if file and file.filename != '':
                profile_photo = upload_to_cloudinary(file, resource_type="image")
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
                if cursor.fetchone():
                    flash('Username already exists!', 'danger')
                else:
                    cursor.execute(
                        "INSERT INTO users (username, password, full_name, email, gender, age, phone_number, profile_photo, role) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'user')",
                        (username, hashed_pw, full_name, email, gender, age or None, phone_number, profile_photo)
                    )
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
                    session['profile_photo'] = user.get('profile_photo')
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
            filename = upload_to_cloudinary(file, resource_type="video")
            
            # Handle thumbnail upload (optional)
            thumbnail_filename = None
            if 'thumbnail' in request.files:
                thumb_file = request.files['thumbnail']
                if thumb_file and thumb_file.filename != '' and allowed_image(thumb_file.filename):
                    thumbnail_filename = upload_to_cloudinary(thumb_file, resource_type="image")
            
            conn = get_db_connection()
            try:
                category = request.form.get('category', 'Other')
                cooking_time = request.form.get('cooking_time', 0)
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO recipes (title, description, ingredients, instructions, video_filename, thumbnail, category, cooking_time, user_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (title, description, ingredients, instructions, filename, thumbnail_filename, category, cooking_time, session['user_id'])
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
                        new_video_filename = upload_to_cloudinary(file, resource_type="video")

                # Update thumbnail if new one is uploaded
                new_thumbnail = recipe.get('thumbnail')
                if 'thumbnail' in request.files:
                    thumb_file = request.files['thumbnail']
                    if thumb_file and thumb_file.filename != '' and allowed_image(thumb_file.filename):
                        new_thumbnail = upload_to_cloudinary(thumb_file, resource_type="image")

                category = request.form.get('category', recipe['category'])
                cooking_time = request.form.get('cooking_time', recipe['cooking_time'])
                
                cursor.execute(
                    "UPDATE recipes SET title=%s, description=%s, ingredients=%s, instructions=%s, video_filename=%s, thumbnail=%s, category=%s, cooking_time=%s WHERE id=%s",
                    (title, description, ingredients, instructions, new_video_filename, new_thumbnail, category, cooking_time, id)
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
    analytics_data = {'labels': [], 'views': [], 'likes': []}
    admin_stats = {}
    
    try:
        with conn.cursor() as cursor:
            if session['role'] == 'admin':
                # Admin sees all recipes
                cursor.execute("""
                    SELECT recipes.*, users.username, 
                    (SELECT COUNT(*) FROM recipe_likes WHERE recipe_id = recipes.id) as like_count
                    FROM recipes 
                    JOIN users ON recipes.user_id = users.id 
                    ORDER BY views DESC LIMIT 10
                """)
                top_recipes = cursor.fetchall()
                for r in top_recipes:
                    analytics_data['labels'].append(r['title'][:15] + '...')
                    analytics_data['views'].append(r['views'])
                    analytics_data['likes'].append(r['like_count'])
                
                # Full list for the management table
                cursor.execute("SELECT recipes.*, users.username FROM recipes JOIN users ON recipes.user_id = users.id ORDER BY created_at DESC")
                recipes = cursor.fetchall()

                # Admin-specific stats
                cursor.execute("SELECT COUNT(*) as count FROM users")
                admin_stats['total_users'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) as count FROM recipes")
                admin_stats['total_recipes'] = cursor.fetchone()['count']
                
                # Fetch recent user signups for a mini-trend (last 7 days)
                cursor.execute("SELECT DATE(created_at) as date, COUNT(*) as count FROM users GROUP BY DATE(created_at) ORDER BY date DESC LIMIT 7")
                user_trend = cursor.fetchall()
                admin_stats['user_trend'] = {
                    'labels': [str(t['date']) for t in reversed(user_trend)],
                    'counts': [t['count'] for t in reversed(user_trend)]
                }
            else:
                # User sees only their recipes
                cursor.execute("""
                    SELECT recipes.*, 
                    (SELECT COUNT(*) FROM recipe_likes WHERE recipe_id = recipes.id) as like_count 
                    FROM recipes 
                    WHERE user_id=%s 
                    ORDER BY created_at DESC
                """, (session['user_id'],))
                recipes = cursor.fetchall()
                
                for r in reversed(recipes[:10]): # Show last 10 for chart
                    analytics_data['labels'].append(r['title'][:15] + '...')
                    analytics_data['views'].append(r['views'])
                    analytics_data['likes'].append(r['like_count'])
    finally:
        conn.close()
        
    return render_template('dashboard.html', 
                          recipes=recipes, 
                          analytics=analytics_data, 
                          admin_stats=admin_stats)

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
            profile_photo = upload_to_cloudinary(file, resource_type="image")

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
            if profile_photo:
                session['profile_photo'] = profile_photo
        flash('Profile updated successfully!', 'success')
    except Exception as e:
        flash(f"Error updating profile: {str(e)}", 'danger')
    finally:
        conn.close()
    return redirect(url_for('profile'))

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if new_password != confirm_password:
        flash('New passwords do not match!', 'danger')
        return redirect(url_for('profile'))
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password FROM users WHERE id=%s", (session['user_id'],))
            user = cursor.fetchone()
            
            if user and check_password_hash(user['password'], current_password):
                hashed_pw = generate_password_hash(new_password)
                cursor.execute("UPDATE users SET password=%s WHERE id=%s", (hashed_pw, session['user_id']))
                conn.commit()
                flash('Password updated successfully!', 'success')
            else:
                flash('Incorrect current password!', 'danger')
    except Exception as e:
        flash(f"Error updating password: {str(e)}", 'danger')
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
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
            users = cursor.fetchall()
    finally:
        conn.close()
    return render_template('admin_users.html', users=users)

@app.route('/admin/user_details/<int:user_id>')
def admin_user_details(user_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return {"error": "Unauthorized"}, 403
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
            user = cursor.fetchone()
            if not user:
                return {"error": "User not found"}, 404
            
            # Count user's recipes
            cursor.execute("SELECT COUNT(*) as count FROM recipes WHERE user_id=%s", (user_id,))
            recipe_count = cursor.fetchone()['count']
            
            # Count user's comments
            cursor.execute("SELECT COUNT(*) as count FROM comments WHERE user_id=%s", (user_id,))
            comment_count = cursor.fetchone()['count']
            
            # Count user's likes
            cursor.execute("SELECT COUNT(*) as count FROM recipe_likes WHERE user_id=%s", (user_id,))
            like_count = cursor.fetchone()['count']
            
            user_data = {
                "id": user['id'],
                "username": user['username'],
                "password": user['password'],
                "full_name": user.get('full_name') or '',
                "email": user.get('email') or '',
                "gender": user.get('gender') or '',
                "age": user.get('age') or '',
                "phone_number": user.get('phone_number') or '',
                "profile_photo": user.get('profile_photo') or '',
                "role": user['role'],
                "created_at": user['created_at'].strftime('%B %d, %Y at %I:%M %p') if user.get('created_at') else '',
                "recipe_count": recipe_count,
                "comment_count": comment_count,
                "like_count": like_count
            }
            return user_data
    finally:
        conn.close()

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

@app.route('/admin/reset_password/<int:user_id>', methods=['POST'])
def admin_reset_password(user_id):
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('index'))
    
    new_password = request.form.get('new_password')
    if not new_password or len(new_password) < 6:
        flash('Password must be at least 6 characters long.', 'danger')
        return redirect(url_for('admin_users'))
    
    hashed_password = generate_password_hash(new_password)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET password=%s WHERE id=%s", (hashed_password, user_id))
            conn.commit()
            flash('Password reset successfully!', 'success')
    except Exception as e:
        print(f"Error resetting password: {e}")
        flash('Failed to reset password.', 'danger')
    finally:
        conn.close()
        
    return redirect(url_for('admin_users'))

@app.route('/suggestions')
def suggestions():
    query = request.args.get('q', '').lower().strip()
    if not query:
        return {"suggestions": []}
    
    # Check cache first
    now = time.time()
    if query in SUGGESTION_CACHE:
        cached_data, timestamp = SUGGESTION_CACHE[query]
        if now - timestamp < CACHE_TIMEOUT:
            return {"suggestions": cached_data}
    
    suggestions_list = []
    
    # 1. Get local suggestions (fastest)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT title FROM recipes WHERE title ILIKE %s LIMIT 3",
                (f'%{query}%',)
            )
            suggestions_list.extend([row['title'] for row in cursor.fetchall()])
    except:
        pass
    finally:
        conn.close()
        
    # 2. Get YouTube suggestions (External - cached)
    try:
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q={quote(query)}"
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        # Set a short timeout for the network request
        with urlopen(req, timeout=1.5) as response:
            data = json.loads(response.read().decode())
            if len(data) > 1:
                for s in data[1][:4]:
                    if s not in suggestions_list:
                        suggestions_list.append(s)
    except:
        pass
    
    # Save to cache before returning
    final_suggestions = suggestions_list[:7]
    SUGGESTION_CACHE[query] = (final_suggestions, now)
        
    return {"suggestions": final_suggestions}

if __name__ == '__main__':
    app.run(debug=True)
