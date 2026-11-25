from app import app, db
from models import User
from werkzeug.security import generate_password_hash

with app.app_context():
    # Print all users
    print("All users:", User.query.all())
    # Create admin user if not exists
    if not User.query.filter_by(username="admin").first():
        admin = User(
            email="admin@gmail.com",
            username="admin",
            password_hash=generate_password_hash("admin123"),
            status="approved",
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()
        print("Admin user created!")
    else:
        print("Admin user already exists.")
