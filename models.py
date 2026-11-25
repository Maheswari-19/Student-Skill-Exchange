from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# Association tables for many-to-many relationships
offered = db.Table('offered',
    db.Column('user_id', db.Integer, db.ForeignKey('profile.id')),
    db.Column('skill_id', db.Integer, db.ForeignKey('skill.id'))
)

wanted = db.Table('wanted',
    db.Column('user_id', db.Integer, db.ForeignKey('profile.id')),
    db.Column('skill_id', db.Integer, db.ForeignKey('skill.id'))
)

class Skill(db.Model):
    __tablename__ = 'skill'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class Profile(db.Model):
    __tablename__ = 'profile'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    full_name = db.Column(db.String(150))
    bio = db.Column(db.Text)
    university = db.Column(db.String(150))
    level = db.Column(db.String(50))
    availability = db.Column(db.String(50))
    mode = db.Column(db.String(50))
    profile_picture = db.Column(db.String(255))  # stores filename of uploaded profile picture
    skills_offered = db.relationship('Skill', secondary='offered', backref='offered_by')
    skills_wanted = db.relationship('Skill', secondary='wanted', backref='wanted_by')

class ExchangeRequest(db.Model):
    __tablename__ = 'exchange_request'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    skill_id = db.Column(db.Integer, db.ForeignKey('skill.id'))
    status = db.Column(db.String(20), default='pending')

class Message(db.Model):
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    text = db.Column(db.Text)
    file_url = db.Column(db.String(255))  # stores filename/path of uploaded file
    file_name = db.Column(db.String(255)) # original filename for display
    is_read = db.Column(db.Boolean, default=False)

class Review(db.Model):
    __tablename__ = 'review'
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    rating = db.Column(db.Integer)
    comment = db.Column(db.Text)

class Session(db.Model):
    __tablename__ = 'session'
    id = db.Column(db.Integer, primary_key=True)
    user1 = db.Column(db.Integer, db.ForeignKey('user.id'))
    user2 = db.Column(db.Integer, db.ForeignKey('user.id'))
    skill1 = db.Column(db.String(100))
    skill2 = db.Column(db.String(100))
    status = db.Column(db.String(50))  # pending / completed
    user1_confirmed = db.Column(db.Boolean, default=False)
    user2_confirmed = db.Column(db.Boolean, default=False)

class Schedule(db.Model):
    __tablename__ = 'schedule'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'))
    date = db.Column(db.String(50))
    time = db.Column(db.String(50))
class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=db.func.now())

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    profile_completed = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending/approved/rejected
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    profile = db.relationship('Profile', backref='user', uselist=False, cascade="all, delete-orphan")
    requests_sent = db.relationship('ExchangeRequest', foreign_keys=[ExchangeRequest.sender_id], backref='sender')
    requests_received = db.relationship('ExchangeRequest', foreign_keys=[ExchangeRequest.receiver_id], backref='receiver')
    messages_sent = db.relationship('Message', foreign_keys=[Message.sender_id], backref='sender_msg')
    messages_received = db.relationship('Message', foreign_keys=[Message.receiver_id], backref='receiver_msg')
    reviews_given = db.relationship('Review', foreign_keys=[Review.reviewer_id], backref='reviewer')
    reviews_received = db.relationship('Review', foreign_keys=[Review.reviewed_id], backref='reviewed')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
