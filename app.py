
from functools import wraps
from functools import wraps
import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g
from flask_mail import Mail, Message as MailMessage
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, join_room, leave_room, emit
from models import db, User, Profile, Skill, ExchangeRequest, Message, Review, Session, Schedule, Notification
from services.matching import get_matches
from sqlalchemy import inspect


app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Flask-Mail config (update with your SMTP server details)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')  # set env var or hardcode for demo
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@example.com')

mail = Mail(app)
def send_mail_notification(to, subject, body):
    try:
        msg = MailMessage(subject, recipients=[to], body=body)
        mail.send(msg)
    except Exception as e:
        print(f"Mail send failed: {e}")

db.init_app(app)
socketio = SocketIO(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# --- Online status tracking ---
online_users = set()

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        online_users.add(current_user.id)
        # Join notification room for this user
        join_room(f"notif_{current_user.id}")

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated and current_user.id in online_users:
        online_users.remove(current_user.id)

# Helper for Jinja2 to check if a user is online
@app.context_processor
def inject_online_status():
    def is_online(user_id):
        return user_id in online_users
    return dict(is_online=is_online)

# Add notification when an exchange request is accepted
@app.route('/accept-exchange-request/<int:request_id>', methods=['POST'])
@login_required
def accept_exchange_request(request_id):
    req = ExchangeRequest.query.get_or_404(request_id)
    if req.receiver_id != current_user.id:
        flash('You do not have permission to accept this request.', 'danger')
        return redirect(url_for('dashboard'))
    req.status = 'accepted'
    db.session.commit()
    # Fetch the skill name using skill_id
    skill = Skill.query.get(req.skill_id)
    skill_name = skill.name if skill else 'Unknown Skill'
    # Create session entry (pending)
    # user1: sender, user2: receiver
    existing_session = Session.query.filter_by(user1=req.sender_id, user2=req.receiver_id, skill1=skill_name).first()
    if not existing_session:
        session_entry = Session(user1=req.sender_id, user2=req.receiver_id, skill1=skill_name, status='pending')
        db.session.add(session_entry)
        db.session.commit()
    # Notify sender
    notif = Notification(user_id=req.sender_id, message=f'Your exchange request for {skill_name} was accepted by {current_user.profile.full_name or current_user.username}')
    db.session.add(notif)
    db.session.commit()
    # Send mail notification to sender (if email exists)
    sender = User.query.get(req.sender_id)
    if sender and sender.email:
        send_mail_notification(
            to=sender.email,
            subject="Your exchange request was accepted!",
            body=f"Hi {sender.username},\n\nYour exchange request for {skill_name} was accepted by {current_user.profile.full_name or current_user.username}. Log in to start chatting!\n\n- Student Skill Exchange Team"
        )
    flash('Request accepted!', 'success')
    return redirect(url_for('dashboard'))

# Edit profile route (profile fields and skills)
@app.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    profile = current_user.profile
    skills = Skill.query.all()
    if request.method == 'POST':
        profile.full_name = request.form.get('full_name', profile.full_name)
        # Update username if changed and not taken
        new_username = request.form.get('username', current_user.username)
        if new_username != current_user.username:
            if User.query.filter_by(username=new_username).first():
                flash('Username already taken. Please choose another.', 'danger')
                return render_template('edit_profile.html', profile=profile, skills=skills, offered_ids=[str(skill.id) for skill in profile.skills_offered], wanted_ids=[str(skill.id) for skill in profile.skills_wanted])
            current_user.username = new_username
        profile.bio = request.form.get('bio', profile.bio)
        profile.university = request.form.get('university', profile.university)
        profile.level = request.form.get('level', profile.level)
        profile.availability = request.form.get('availability', profile.availability)
        profile.mode = request.form.get('mode', profile.mode)
        # Update skills offered
        offered_ids = request.form.getlist('skills_offered')
        wanted_ids = request.form.getlist('skills_wanted')
        profile.skills_offered.clear()
        profile.skills_wanted.clear()
        skill_map = {str(skill.id): skill for skill in skills}
        for skill_id in offered_ids:
            skill = skill_map.get(skill_id)
            if skill:
                profile.skills_offered.append(skill)
        for skill_id in wanted_ids:
            skill = skill_map.get(skill_id)
            if skill:
                profile.skills_wanted.append(skill)
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    # Pre-select skills
    offered_ids = [str(skill.id) for skill in profile.skills_offered]
    wanted_ids = [str(skill.id) for skill in profile.skills_wanted]
    return render_template('edit_profile.html', profile=profile, skills=skills, offered_ids=offered_ids, wanted_ids=wanted_ids)
@app.route('/chat/<int:user_id>')
@login_required
def chat(user_id):
    if getattr(current_user, 'status', 'pending') != 'approved':
        flash('Your account is not approved yet. Please wait for admin approval.', 'warning')
        return redirect(url_for('logout'))
    if not getattr(current_user, 'profile_completed', False) or not current_user.profile or not current_user.profile.skills_offered:
        flash('Please complete your profile and add at least one skill to use chat.', 'danger')
        return redirect(url_for('edit_profile'))
    other_user = User.query.get_or_404(user_id)
    if not other_user.profile or getattr(other_user, 'status', 'pending') != 'approved':
        flash('User profile not found or not approved.', 'danger')
        return redirect(url_for('dashboard'))
    # Only allow chat if there is an accepted request between users
    accepted = ExchangeRequest.query.filter(
        ((ExchangeRequest.sender_id == current_user.id) & (ExchangeRequest.receiver_id == user_id) & (ExchangeRequest.status == 'accepted')) |
        ((ExchangeRequest.sender_id == user_id) & (ExchangeRequest.receiver_id == current_user.id) & (ExchangeRequest.status == 'accepted'))
    ).first()
    if not accepted:
        flash('You do not have permission to chat with this user.', 'danger')
        return redirect(url_for('dashboard'))
    room = f"chat_{min(current_user.id, user_id)}_{max(current_user.id, user_id)}"
    # Load previous messages between the two users (both directions)
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.id.asc()).all()
    return render_template('chat.html', other_user=other_user, room=room, messages=messages)

# SocketIO event for chat
@socketio.on('send_message')
def handle_send_message(data):
    room = data['room']
    message = data['message']
    username = data['username']
    sender_id = data.get('sender_id')
    receiver_id = data.get('receiver_id')
    # Save message to database
    if sender_id and receiver_id:
        msg = Message(sender_id=sender_id, receiver_id=receiver_id, text=message)
        db.session.add(msg)
        # Create notification for receiver
        notif = Notification(user_id=receiver_id, message=f'New message from {username}')
        db.session.add(notif)
        db.session.commit()
    emit('receive_message', {'message': message, 'username': username}, room=room)
    # Real-time notification for receiver (if online)
    if receiver_id:
        notif_room = f"notif_{receiver_id}"
        emit('notify', {'type': 'message', 'text': f'New message from {username}'}, room=notif_room, namespace='/')

# SocketIO event for joining room
@socketio.on('join')
def handle_join(data):
    join_room(data['room'])


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    def _column_exists(table_name, column_name):
        result = db.session.execute(db.text(f"PRAGMA table_info({table_name})"))
        return any(row[1] == column_name for row in result)

    # Auto-fix: Add is_admin column to user table if missing
    if not _column_exists('user', 'is_admin'):
        db.session.execute(db.text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
        db.session.commit()

    if not inspect(db.engine).has_table('session'):
        db.session.execute(db.text("CREATE TABLE session (id INTEGER PRIMARY KEY AUTOINCREMENT, user1 INTEGER, user2 INTEGER, skill1 VARCHAR(100), skill2 VARCHAR(100), status VARCHAR(50))"))

    # Auto-fix: Add user1_confirmed and user2_confirmed columns to session table if missing
    if not _column_exists('session', 'user1_confirmed'):
        db.session.execute(db.text("ALTER TABLE session ADD COLUMN user1_confirmed BOOLEAN DEFAULT 0"))
    if not _column_exists('session', 'user2_confirmed'):
        db.session.execute(db.text("ALTER TABLE session ADD COLUMN user2_confirmed BOOLEAN DEFAULT 0"))

    db.create_all()

    # Keep local SQLite schema in sync for newly added onboarding fields.
    if not _column_exists('user', 'profile_completed'):
        db.session.execute(db.text("ALTER TABLE user ADD COLUMN profile_completed BOOLEAN DEFAULT 0"))
    # Auto-fix: Add status column to user table if missing
    if not _column_exists('user', 'status'):
        db.session.execute(db.text("ALTER TABLE user ADD COLUMN status VARCHAR(20) DEFAULT 'pending'"))
        db.session.commit()
    if not _column_exists('profile', 'full_name'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN full_name VARCHAR(150)"))
    if not _column_exists('profile', 'university'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN university VARCHAR(150)"))
    if not _column_exists('profile', 'level'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN level VARCHAR(50)"))
    if not _column_exists('profile', 'availability'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN availability VARCHAR(50)"))
    if not _column_exists('profile', 'mode'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN mode VARCHAR(50)"))
    if not _column_exists('profile', 'profile_picture'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN profile_picture VARCHAR(255)"))
    db.session.commit()
    # Seed and update skills list
    default_skills = [
        'Python', 'JavaScript', 'HTML/CSS', 'UI/UX Design', 'Calculus', 'Physics', 'Photography', 'Video Editing',
        'Public Speaking', 'Machine Learning', 'Java', 'C Programming', 'Data Structures & Algorithms (DSA)',
        'SQL / Databases', 'Web Development', 'Operating Systems', 'Computer Networks', 'Software Engineering',
        'Artificial Intelligence (AI)', 'Data Science', 'Cybersecurity', 'Cloud Computing', 'Blockchain',
        'Internet of Things (IoT)', 'Graphic Design', 'Content Writing', 'Digital Marketing', 'Presentation Skills',
        'Communication Skills', 'Git & GitHub', 'VS Code', 'Figma', 'Canva', 'Excel', 'PowerPoint'
    ]
    existing_skills = {skill.name for skill in Skill.query.all()}
    for skill_name in default_skills:
        if skill_name not in existing_skills:
            db.session.add(Skill(name=skill_name))
    db.session.commit()
    # Auto-fix: Add is_read column to message table if missing
    if not _column_exists('message', 'is_read'):
        db.session.execute(db.text("ALTER TABLE message ADD COLUMN is_read BOOLEAN DEFAULT 0"))
        db.session.commit()
    # Auto-fix: Add file_url and file_name columns to message table if missing
    if not _column_exists('message', 'file_url'):
        db.session.execute(db.text("ALTER TABLE message ADD COLUMN file_url VARCHAR(255)"))
    if not _column_exists('message', 'file_name'):
        db.session.execute(db.text("ALTER TABLE message ADD COLUMN file_name VARCHAR(255)"))
    db.session.commit()
    # ...existing code...

# Place all route definitions after app and db initialization
@app.route('/edit-profile-picture', methods=['GET', 'POST'])
@login_required
def edit_profile_picture():
    profile = current_user.profile
    if request.method == 'POST':
        try:
            if 'profile_picture' not in request.files:
                flash('Please upload a profile picture.', 'warning')
                return render_template('edit_profile_picture.html', profile=profile)
            file = request.files['profile_picture']
            if file.filename == '':
                flash('No selected file.', 'warning')
                return render_template('edit_profile_picture.html', profile=profile)
            if file:
                filename = file.filename
                upload_folder = os.path.join('static', 'images', 'profile_pics')
                os.makedirs(upload_folder, exist_ok=True)
                filepath = os.path.join(upload_folder, filename)
                file.save(filepath)
                profile.profile_picture = filename
                db.session.commit()
                flash('Profile picture updated successfully!', 'success')
                return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Failed to upload profile picture: {str(e)}', 'danger')
            return render_template('edit_profile_picture.html', profile=profile)
    return render_template('edit_profile_picture.html', profile=profile)

@app.route('/send-exchange-request', methods=['POST'])
@login_required
def send_exchange_request():
    # Enforce profile completion and at least one skill to send requests
    if not getattr(current_user, 'profile_completed', False) or not current_user.profile or not current_user.profile.skills_offered:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='Please complete your profile and add at least one skill to send requests.'), 400
        flash('Please complete your profile and add at least one skill to send requests.', 'danger')
        return redirect(url_for('edit_profile'))
    from datetime import datetime
    from sqlalchemy import func
    today = datetime.utcnow().date()
    requests_today = ExchangeRequest.query.filter(
        ExchangeRequest.sender_id == current_user.id,
        func.date(ExchangeRequest.id) == today
    ).count()
    if requests_today >= 5:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='Request limit reached (5 per day). Try again tomorrow.'), 400
        flash('Request limit reached (5 per day). Try again tomorrow.', 'warning')
        return redirect(url_for('dashboard'))
    receiver_id = request.form.get('receiver_id')
    skill_id = request.form.get('skill_id')
    if not receiver_id or not skill_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='Invalid request.'), 400
        flash('Invalid request.', 'danger')
        return redirect(url_for('dashboard'))
    existing = ExchangeRequest.query.filter_by(sender_id=current_user.id, receiver_id=receiver_id, skill_id=skill_id, status='pending').first()
    if existing:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='You have already sent a request for this skill.'), 400
        flash('You have already sent a request for this skill.', 'info')
        return redirect(url_for('dashboard'))
    new_request = ExchangeRequest(sender_id=current_user.id, receiver_id=receiver_id, skill_id=skill_id, status='pending')
    db.session.add(new_request)
    notif = Notification(user_id=receiver_id, message=f'New exchange request from {current_user.profile.full_name or current_user.username}')
    db.session.add(notif)
    db.session.commit()
    notif_room = f"notif_{receiver_id}"
    emit('notify', {'type': 'request', 'text': f'New exchange request from {current_user.profile.full_name or current_user.username}'}, room=notif_room, namespace='/')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(success=True)
    flash('Exchange request sent!', 'success')
    return redirect(url_for('dashboard'))
@app.route('/reject-exchange-request/<int:request_id>', methods=['POST'])
@login_required
def reject_exchange_request(request_id):
    req = ExchangeRequest.query.get_or_404(request_id)
    if req.receiver_id != current_user.id:
        flash('You do not have permission to reject this request.', 'danger')
        return redirect(url_for('dashboard'))
    req.status = 'rejected'
    db.session.commit()
    flash('Request rejected.', 'info')
    return redirect(url_for('dashboard'))

    # Keep local SQLite schema in sync for newly added onboarding fields.
    if not _column_exists('user', 'profile_completed'):
        db.session.execute(db.text("ALTER TABLE user ADD COLUMN profile_completed BOOLEAN DEFAULT 0"))

    if not _column_exists('profile', 'full_name'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN full_name VARCHAR(150)"))

    if not _column_exists('profile', 'university'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN university VARCHAR(150)"))

    if not _column_exists('profile', 'level'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN level VARCHAR(50)"))

    if not _column_exists('profile', 'availability'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN availability VARCHAR(50)"))

    if not _column_exists('profile', 'mode'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN mode VARCHAR(50)"))

    if not _column_exists('profile', 'profile_picture'):
        db.session.execute(db.text("ALTER TABLE profile ADD COLUMN profile_picture VARCHAR(255)"))

    db.session.commit()

    # Seed default skills if none exist
    if not Skill.query.first():
        default_skills = [
            'Python', 'JavaScript', 'HTML/CSS', 'UI/UX Design', 
            'Calculus', 'Physics', 'Photography', 'Video Editing',
            'Public Speaking', 'Machine Learning'
        ]
        for skill_name in default_skills:
            db.session.add(Skill(name=skill_name))
        db.session.commit()


def _onboarding_data():
    if 'onboarding' not in session:
        session['onboarding'] = {}
    return session['onboarding']


def _is_profile_complete(user):
    if not user:
        return False

    if getattr(user, 'profile_completed', False):
        return True

    # Backward compatibility for users created before profile_completed existed.
    if user.profile:
        user.profile_completed = True
        db.session.commit()
        return True

    return False


def get_skill_catalog():
    return [
        {'name': 'Web Development', 'students': '1,200+', 'icon': 'fas fa-code', 'theme': 'blue'},
        {'name': 'Graphic Design', 'students': '950+', 'icon': 'fas fa-palette', 'theme': 'sunset'},
        {'name': 'Data Science', 'students': '800+', 'icon': 'fas fa-chart-line', 'theme': 'mint'},
        {'name': 'Language Learning', 'students': '1,100+', 'icon': 'fas fa-language', 'theme': 'amber'},
        {'name': 'Marketing', 'students': '600+', 'icon': 'fas fa-bullhorn', 'theme': 'royal'},
        {'name': 'Public Speaking', 'students': '450+', 'icon': 'fas fa-microphone', 'theme': 'rose'},
        {'name': 'AI & Machine Learning', 'students': '700+', 'icon': 'fas fa-robot', 'theme': 'violet'},
        {'name': 'UI/UX Design', 'students': '520+', 'icon': 'fas fa-vector-square', 'theme': 'sky'},
        {'name': 'Video Editing', 'students': '580+', 'icon': 'fas fa-video', 'theme': 'teal'},
        {'name': 'Photography', 'students': '640+', 'icon': 'fas fa-camera', 'theme': 'indigo'},
        {'name': 'Calculus Help', 'students': '500+', 'icon': 'fas fa-calculator', 'theme': 'orange'},
        {'name': 'Physics Coaching', 'students': '430+', 'icon': 'fas fa-atom', 'theme': 'green'},
        {'name': 'Python Programming', 'students': '920+', 'icon': 'fab fa-python', 'theme': 'blue'},
        {'name': 'JavaScript', 'students': '860+', 'icon': 'fab fa-js', 'theme': 'gold'},
        {'name': 'Content Writing', 'students': '540+', 'icon': 'fas fa-pen-nib', 'theme': 'slate'},
    ]


def get_featured_mentors():
    return [
        {'name': 'Aarav Sharma', 'role': 'Web Development Mentor', 'image': 'stu1.jpg', 'badge': 'Top Rated'},
        {'name': 'Ishita Verma', 'role': 'AI & Machine Learning', 'image': 'stu2.jpg', 'badge': 'AI Expert'},
        {'name': 'Rohan Iyer', 'role': 'Graphic Design Mentor', 'image': 'stu3.jpg', 'badge': 'Design Pro'},
        {'name': 'Ananya Patel', 'role': 'Data Science Mentor', 'image': 'stu4.jpg', 'badge': 'Data Coach'},
        {'name': 'Karan Malhotra', 'role': 'Public Speaking Mentor', 'image': 'stu5.jpg', 'badge': 'Speaker'},
        {'name': 'Meera Nair', 'role': 'Marketing Mentor', 'image': 'stu6.jpg', 'badge': 'Growth Lead'},
        {'name': 'Vikram Rao', 'role': 'Python Programming', 'image': 'stu7.jpg', 'badge': 'Python Star'},
        {'name': 'Priya Kulkarni', 'role': 'UI/UX Design Mentor', 'image': 'stu8.jpg', 'badge': 'UX Coach'},
        {'name': 'Aditya Menon', 'role': 'Video Editing Mentor', 'image': 'stu9.jpg', 'badge': 'Video Pro'},
        {'name': 'Sneha Reddy', 'role': 'Language Learning', 'image': 'stu10.jpg', 'badge': 'Fluent Guide'},
        {'name': 'Nikhil Bansal', 'role': 'Calculus Mentor', 'image': 'stu11.jpg', 'badge': 'Math Ace'},
    ]


def get_testimonials():
    return [
        {
            'name': 'Riya Sharma',
            'university': 'IIT Delhi',
            'image': 'testimo1.jpg',
            'rating': 5,
            'quote': 'Exchanging skills on this platform helped me build confidence and connect with amazing peers.'
        },
        {
            'name': 'Arjun Menon',
            'university': 'NIT Trichy',
            'image': 'testimo2.jpg',
            'rating': 5,
            'quote': 'I found the right mentors quickly and improved my portfolio with practical projects.'
        },
        {
            'name': 'Priya Patel',
            'university': 'Delhi University',
            'image': 'testimo3.jpg',
            'rating': 5,
            'quote': 'The skill exchange model is brilliant. I taught design and learned machine learning in return.'
        },
        {
            'name': 'Rahul Verma',
            'university': 'IIT Bombay',
            'image': 'testimo4.jpg',
            'rating': 5,
            'quote': 'The AI recommendations matched me with students who were exactly aligned with my learning goals.'
        },
        {
            'name': 'Sneha Reddy',
            'university': 'Anna University',
            'image': 'testimo5.jpg',
            'rating': 5,
            'quote': 'I got internship guidance and public speaking feedback from mentors here. Super useful community.'
        },
        {
            'name': 'Karan Iyer',
            'university': 'BITS Pilani',
            'image': 'testimo6.jpg',
            'rating': 5,
            'quote': 'Very easy to use and the sessions are practical. The credit-based exchange keeps everyone active.'
        },
        {
            'name': 'Sriram Gupta',
            'university': 'VIT Vellore',
            'image': 'testimo7.jpg',
            'rating': 5,
            'quote': 'Loved the collaborative environment. I improved both technical skills and communication skills.'
        },
        {
            'name': 'Vikram Rao',
            'university': 'University of Hyderabad',
            'image': 'testimo8.jpg',
            'rating': 5,
            'quote': 'This platform made learning affordable and interactive. Highly recommended for all students.'
        },
    ]

@app.route('/')
def index():
    skill_catalog = get_skill_catalog()
    featured_mentors = get_featured_mentors()
    testimonials = get_testimonials()
    return render_template(
        'index.html',
        popular_skills=skill_catalog[:9],
        featured_mentors=featured_mentors[:8],
        testimonials=testimonials[:3]
    )


@app.route('/skills')
def skills():
    skill_catalog = get_skill_catalog()
    return render_template('skills.html', skill_catalog=skill_catalog)


@app.route('/mentors')
def mentors():
    mentor_catalog = get_featured_mentors()
    return render_template('mentors.html', mentor_catalog=mentor_catalog)


@app.route('/testimonials')
def testimonials():
    all_testimonials = get_testimonials()
    return render_template('testimonials.html', testimonials=all_testimonials)


@app.route('/matches')
@login_required
def matches():
    if getattr(current_user, 'status', 'pending') != 'approved':
        flash('Your account is not approved yet. Please wait for admin approval.', 'warning')
        return redirect(url_for('logout'))
    if not getattr(current_user, 'profile_completed', False) or not current_user.profile or not current_user.profile.skills_offered:
        flash('Please complete your profile and add at least one skill to use matching.', 'danger')
        return redirect(url_for('edit_profile'))
    users = User.query.filter(User.status == 'approved', User.profile_completed == True).all()
    # Only include users with at least one skill
    users = [u for u in users if u.profile and u.profile.skills_offered]
    # Advanced: Sort by average rating (descending)
    def avg_rating(user):
        reviews = user.reviews_received
        if not reviews:
            return 0
        return sum(r.rating for r in reviews if r.rating) / max(1, len([r for r in reviews if r.rating]))
    users.sort(key=avg_rating, reverse=True)
    results = get_matches(current_user, users)
    return jsonify(results)


@app.route('/ai-recommendations')
@login_required
def ai_recommendations():
    if getattr(current_user, 'status', 'pending') != 'approved':
        flash('Your account is not approved yet. Please wait for admin approval.', 'warning')
        return redirect(url_for('logout'))
    if not getattr(current_user, 'profile_completed', False) or not current_user.profile or not current_user.profile.skills_offered:
        flash('Please complete your profile and add at least one skill to use recommendations.', 'danger')
        return redirect(url_for('edit_profile'))
    users = User.query.filter(User.status == 'approved', User.profile_completed == True).all()
    users = [u for u in users if u.profile and u.profile.skills_offered]
    def avg_rating(user):
        reviews = user.reviews_received
        if not reviews:
            return 0
        return sum(r.rating for r in reviews if r.rating) / max(1, len([r for r in reviews if r.rating]))
    users.sort(key=avg_rating, reverse=True)
    results = get_matches(current_user, users)
    return render_template('matches.html', matches=results)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, 'is_admin', False):
            return redirect(url_for('admin_panel'))
        if _is_profile_complete(current_user):
            return redirect(url_for('dashboard'))
        return redirect(url_for('onboarding_step1'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            if getattr(user, 'is_admin', False):
                return redirect(url_for('admin_panel'))
            if not _is_profile_complete(user):
                flash('Please complete onboarding to continue.', 'info')
                return redirect(url_for('onboarding_step1'))
            return redirect(url_for('dashboard'))
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html')
# Admin dashboard route
@app.route('/admin')
@login_required
def admin_panel():
    if not getattr(current_user, 'is_admin', False):
        return "Unauthorized", 403
    users = User.query.filter(User.status == 'pending').all()
    # Query completed sessions
    completed_sessions = Session.query.filter_by(status='completed').all()
    session_data = []
    for s in completed_sessions:
        user1 = User.query.get(s.user1)
        user2 = User.query.get(s.user2)
        session_data.append({
            'user1_name': user1.username if user1 else 'Unknown',
            'user2_name': user2.username if user2 else 'Unknown',
            'skill1': s.skill1,
            'skill2': s.skill2
        })
    return render_template('admin_dashboard.html', users=users, completed_sessions=session_data)

# Route to handle ending a session by either user
@app.route('/end-session/<int:other_user_id>', methods=['POST'])
@login_required
def end_session(other_user_id):
    # Find the session between the two users (either direction)
    session_obj = Session.query.filter(
        ((Session.user1 == current_user.id) & (Session.user2 == other_user_id)) |
        ((Session.user1 == other_user_id) & (Session.user2 == current_user.id))
    ).first()
    if not session_obj:
        return jsonify({'message': 'Session not found.', 'completed': False}), 404

    # Mark the current user as having ended the session
    if session_obj.user1 == current_user.id:
        session_obj.user1_confirmed = True
    elif session_obj.user2 == current_user.id:
        session_obj.user2_confirmed = True

    # If both users have ended, mark as completed
    completed = False
    if session_obj.user1_confirmed and session_obj.user2_confirmed:
        session_obj.status = 'completed'
        completed = True

    db.session.commit()
    # Debug print
    print(f"[DEBUG] Session ID: {session_obj.id}, user1: {session_obj.user1}, user2: {session_obj.user2}, user1_confirmed: {session_obj.user1_confirmed}, user2_confirmed: {session_obj.user2_confirmed}, status: {session_obj.status}")
    msg = 'Session ended. Waiting for the other user.'
    if completed:
        msg = 'Session completed!'
    return jsonify({'message': msg, 'completed': completed})
    


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    skills = Skill.query.all()
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        university = request.form.get('university')
        bio = request.form.get('bio')
        offered_ids = request.form.getlist('skills_offered')
        user_exists = User.query.filter((User.username == username) | (User.email == email)).first()
        if user_exists:
            flash('Username or Email already exists', 'danger')
        else:
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            new_user.profile_completed = False
            db.session.add(new_user)
            db.session.commit()
            # Create profile with registration info
            profile = Profile(user_id=new_user.id, full_name=full_name, bio=bio, university=university)
            # Add offered skills
            skill_map = {str(skill.id): skill for skill in skills}
            for skill_id in offered_ids:
                skill = skill_map.get(skill_id)
                if skill:
                    profile.skills_offered.append(skill)
            db.session.add(profile)
            db.session.commit()
            flash('Account created! Please wait for admin approval.', 'success')
            return redirect(url_for('login'))
    return render_template('signup.html', skills=skills)

@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    if _is_profile_complete(current_user):
        return redirect(url_for('dashboard'))

    return redirect(url_for('onboarding_step1'))


@app.route('/onboarding/step1', methods=['GET', 'POST'])
@login_required
def onboarding_step1():
    if _is_profile_complete(current_user):
        return redirect(url_for('dashboard'))
    onboarding = _onboarding_data()
    if request.method == 'POST':
        onboarding['full_name'] = request.form.get('full_name', '').strip()
        onboarding['bio'] = request.form.get('bio', '').strip()
        onboarding['university'] = request.form.get('university', '').strip()
        session.modified = True
        return redirect(url_for('onboarding_step2'))

    return render_template('onboarding_step1.html', data=onboarding)


@app.route('/onboarding/step2', methods=['GET', 'POST'])
@login_required
def onboarding_step2():
    if _is_profile_complete(current_user):
        return redirect(url_for('dashboard'))

    onboarding = _onboarding_data()
    skills = Skill.query.all()
    if request.method == 'POST':
        selected = request.form.getlist('skills_offered')
        if not selected:
            flash('Please select at least one offered skill.', 'warning')
            return render_template('onboarding_step2.html', data=onboarding, skills=skills)
        onboarding['skills_offered'] = selected
        session.modified = True
        return redirect(url_for('onboarding_step3'))

    return render_template('onboarding_step2.html', data=onboarding, skills=skills)


@app.route('/onboarding/step3', methods=['GET', 'POST'])
@login_required
def onboarding_step3():
    if _is_profile_complete(current_user):
        return redirect(url_for('dashboard'))

    onboarding = _onboarding_data()
    skills = Skill.query.all()
    if request.method == 'POST':
        selected = request.form.getlist('skills_wanted')
        if not selected:
            flash('Please select at least one wanted skill.', 'warning')
            return render_template('onboarding_step3.html', data=onboarding, skills=skills)
        onboarding['skills_wanted'] = selected
        session.modified = True
        return redirect(url_for('onboarding_step5'))

    return render_template('onboarding_step3.html', data=onboarding, skills=skills)






@app.route('/onboarding/step5', methods=['GET', 'POST'])
@login_required
def onboarding_step5():
    if _is_profile_complete(current_user):
        return redirect(url_for('dashboard'))

    onboarding = _onboarding_data()
    if request.method == 'POST':
        level = request.form.get('level', '')
        availability = request.form.get('availability', '')
        if not level:
            flash('Please choose your skill level.', 'warning')
            return render_template('onboarding_step5.html', data=onboarding)
        if not availability:
            flash('Please choose your availability.', 'warning')
            return render_template('onboarding_step5.html', data=onboarding)
        onboarding['level'] = level
        onboarding['availability'] = availability
        session.modified = True
        return redirect(url_for('onboarding_step6'))
    return render_template('onboarding_step5.html', data=onboarding)


@app.route('/onboarding/step6', methods=['GET', 'POST'])
@login_required
def onboarding_step6():
    if _is_profile_complete(current_user):
        return redirect(url_for('dashboard'))

    onboarding = _onboarding_data()
    if request.method == 'POST':
        mode = request.form.get('mode', '')
        if not mode:
            flash('Please choose your learning mode.', 'warning')
            return render_template('onboarding_step6.html', data=onboarding)
        onboarding['mode'] = mode
        session.modified = True
        return redirect(url_for('onboarding_step7'))

    return render_template('onboarding_step6.html', data=onboarding)


@app.route('/onboarding/step7', methods=['GET', 'POST'])
@login_required
def onboarding_step7():
    if _is_profile_complete(current_user):
        return redirect(url_for('dashboard'))

    onboarding = _onboarding_data()
    skills = Skill.query.all()
    skill_map = {str(skill.id): skill for skill in skills}

    offered_ids = onboarding.get('skills_offered', [])
    wanted_ids = onboarding.get('skills_wanted', [])
    offered_preview = [skill_map[skill_id].name for skill_id in offered_ids if skill_id in skill_map]
    wanted_preview = [skill_map[skill_id].name for skill_id in wanted_ids if skill_id in skill_map]

    if request.method == 'POST':
        profile = current_user.profile or Profile(user_id=current_user.id)
        profile.full_name = onboarding.get('full_name')
        profile.bio = onboarding.get('bio')
        profile.university = onboarding.get('university')
        profile.level = onboarding.get('level')
        profile.availability = onboarding.get('availability')
        profile.mode = onboarding.get('mode')
        profile.profile_picture = onboarding.get('profile_picture')

        profile.skills_offered.clear()
        profile.skills_wanted.clear()

        for skill_id in offered_ids:
            skill = skill_map.get(skill_id)
            if skill:
                profile.skills_offered.append(skill)

        for skill_id in wanted_ids:
            skill = skill_map.get(skill_id)
            if skill:
                profile.skills_wanted.append(skill)

        db.session.add(profile)
        current_user.profile_completed = True
        db.session.commit()

        session.pop('onboarding', None)
        flash('Onboarding completed successfully!', 'success')
        return redirect(url_for('dashboard'))

    return render_template(
        'onboarding_step5.html',
        data=onboarding,
        offered_preview=offered_preview,
        wanted_preview=wanted_preview
    )

@app.route('/dashboard')
@login_required
def dashboard():
    # All exchange requests (sent or received)
    user = current_user
    all_exchange_requests = ExchangeRequest.query.filter(
        (ExchangeRequest.sender_id == user.id) | (ExchangeRequest.receiver_id == user.id)
    ).order_by(ExchangeRequest.id.desc()).all()
    if not _is_profile_complete(current_user):
        flash('Please complete onboarding to access the dashboard.', 'warning')
        return redirect(url_for('onboarding_step1'))
    if getattr(current_user, 'status', 'pending') != 'approved':
        flash('Your account is not approved yet. Please wait for admin approval.', 'warning')
        return redirect(url_for('logout'))
    # Enforce profile completion and at least one skill
    if not getattr(current_user, 'profile_completed', False) or not current_user.profile or not current_user.profile.skills_offered:
        flash('Please complete your profile and add at least one skill to access the dashboard.', 'danger')
        return redirect(url_for('edit_profile'))

    user = current_user
    profile = user.profile
    # Stats
    skills_offered_count = len(profile.skills_offered) if profile else 0
    skills_learning_count = len(profile.skills_wanted) if profile else 0
    requests_pending = ExchangeRequest.query.filter_by(receiver_id=user.id, status='pending').count()

    # Recommended users with match score and details
    def calculate_match(user_profile, other_profile):
        score = 0
        # Skill match
        for skill in user_profile.skills_wanted:
            if skill in other_profile.skills_offered:
                score += 2
        for skill in user_profile.skills_offered:
            if skill in other_profile.skills_wanted:
                score += 2
        # Level match (bonus)
        if user_profile.level and other_profile.level and user_profile.level == other_profile.level:
            score += 1
        # Availability match (bonus)
        if user_profile.availability and other_profile.availability and user_profile.availability == other_profile.availability:
            score += 1
        return score

    recommended_users = []
    skill_name_to_id = {s.name: s.id for s in Skill.query.all()}
    if profile:
        all_users = User.query.all()
        for other in all_users:
            if other.id == user.id or not other.profile:
                continue
            match_score = calculate_match(profile, other.profile)
            if match_score > 0:
                # Find the first skill they offer that I want
                match_skill_id = None
                for s in other.profile.skills_offered:
                    if s.name in [sw.name for sw in profile.skills_wanted]:
                        match_skill_id = s.id
                        break
                # Calculate max possible score for normalization
                max_score = 2 * (len(profile.skills_wanted) + len(profile.skills_offered)) + 2
                percent = int((match_score / max_score) * 100) if max_score > 0 else 0
                recommended_users.append({
                    'id': other.id,
                    'full_name': other.profile.full_name or other.username,
                    'profile_picture': other.profile.profile_picture,
                    'skills_offered': [s.name for s in other.profile.skills_offered],
                    'skills_wanted': [s.name for s in other.profile.skills_wanted],
                    'match_percent': percent,
                    'level': other.profile.level,
                    'availability': other.profile.availability,
                    'match_skill_id': match_skill_id,
                })
        recommended_users.sort(key=lambda x: x['match_percent'], reverse=True)
        recommended_users = recommended_users[:5]

    # Pending requests
    requests = ExchangeRequest.query.filter_by(receiver_id=user.id, status='pending').all()

    # Active exchanges
    active_exchanges = Session.query.filter(
        ((Session.user1 == user.id) | (Session.user2 == user.id)) & (Session.status == 'active')
    ).all()

    # Completed sessions
    completed_sessions = Session.query.filter(
        ((Session.user1 == user.id) | (Session.user2 == user.id)) & (Session.status == 'completed')
    ).all()

    # Recent reviews
    recent_reviews = Review.query.filter(
        (Review.reviewer_id == user.id) | (Review.reviewed_id == user.id)
    ).order_by(Review.id.desc()).limit(5).all()

    # Notifications
    notifications = Notification.query.filter_by(user_id=user.id, is_read=False).all()
    # Recent messages
    messages = Message.query.filter(
        (Message.sender_id == user.id) | (Message.receiver_id == user.id)
    ).order_by(Message.id.desc()).limit(5).all()

    # Requests sent by the user
    requests_sent = ExchangeRequest.query.filter_by(sender_id=user.id).all()
    # Requests received and accepted by the user
    requests_accepted = ExchangeRequest.query.filter_by(receiver_id=user.id, status='accepted').all()

    # Build a skill_id to skill name dictionary for template use
    skills_dict = {s.id: s.name for s in Skill.query.all()}
    return render_template(
        'dashboard.html',
        user=user,
        profile=profile,
        skills_offered_count=skills_offered_count,
        skills_learning_count=skills_learning_count,
        requests_pending=requests_pending,
        recommended_users=recommended_users,
        requests=requests,
        active_exchanges=active_exchanges,
        completed_sessions=completed_sessions,
        recent_reviews=recent_reviews,
        notifications=notifications,
        messages=messages,
        requests_sent=requests_sent,
        requests_accepted=requests_accepted,
        skills_dict=skills_dict,
        all_exchange_requests=all_exchange_requests
    )

# Move this route outside the dashboard function
@app.route('/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return ('', 204)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

# --- Admin Approve/Reject Routes ---
@app.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
def admin_approve(user_id):
    if not getattr(current_user, 'is_admin', False):
        return "Unauthorized", 403
    user = User.query.get_or_404(user_id)
    user.status = 'approved'
    db.session.commit()
    flash(f'User {user.username} approved.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
def admin_reject(user_id):
    if not getattr(current_user, 'is_admin', False):
        return "Unauthorized", 403
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} rejected and deleted.', 'info')
    return redirect(url_for('admin_panel'))

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
