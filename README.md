# Student Skill Exchange

Student Skill Exchange is a peer-to-peer platform enabling students to share skills and request to learn new ones, with AI-powered matching and real-time chat. All exchanges are based on individual interests—there is no requirement for mutual learning.

## Highlights
- AI-driven skill matching and recommendations
- Flexible, interest-based learning requests
- Real-time chat and notifications
- Admin approval for quality and safety
- Modular onboarding and dashboard

## Features
- User authentication and secure registration
- Profile creation with optional skills to teach and skills to learn
- AI-powered skill matching algorithm
- One-way learning requests (mutual learning possible if both users wish)
- Real-time chat after request acceptance
- Admin/user role support and moderation

## Tech Stack
**Backend:** Python (Flask), Flask-SQLAlchemy, Flask-Login, Flask-SocketIO, Flask-Mail, SQLite
**Frontend:** HTML5, CSS3, Bootstrap, Jinja2 Templates
**AI/ML:** Pandas, scikit-learn (for recommendations)

## Documentation
For full system documentation, including background, objectives, system analysis, design, implementation, results, and references, see:

**docs/Student_Skill_Exchange_Documentation.pdf**

## Project Structure
```
app.py                # Main Flask app
models.py             # Database models and relationships
admin_util.py         # Admin utilities
services/
  matching.py         # AI skill matching logic
static/
  css/                # Stylesheets (airecommendation.css, howitworks.css, etc.)
  images/             # UI images (ai/, featuredstudents/, herosection/, etc.)
templates/
  base.html           # Layout
  dashboard.html      # User dashboard
  onboarding.html     # Onboarding wrapper
  onboarding_step1.html
  onboarding_step2.html
  onboarding_step3.html
  onboarding_step4.html
  onboarding_step5.html
  chat.html           # Real-time chat
  matches.html        # Match results
  mentors.html        # Mentor list
  admin_dashboard.html
  admin_pending.html
  edit_profile.html
  edit_profile_picture.html
  login.html
  signup.html
  skills.html
  testimonials.html
  index.html
requirements.txt      # Python dependencies
README.md             # Project documentation
```

## Database Schema

User: id, username, email, password_hash, profile_completed, status, is_admin
Profile: id, user_id, full_name, bio, university, level, availability, mode, profile_picture, skills_offered, skills_wanted
Skill: id, name
ExchangeRequest: id, sender_id, receiver_id, skill_id, status
Session: id, user1, user2, skill1, skill2, status, user1_confirmed, user2_confirmed
Schedule: id, session_id, date, time
Message: id, sender_id, receiver_id, text, file_url, file_name, is_read
Review: id, reviewer_id, reviewed_id, rating, comment
Notification: id, user_id, message, is_read, timestamp

## Security
- Passwords hashed and salted (PBKDF2 + SHA256)
- Secure HTTP sessions
- ORM prevents SQL injection

## Usage Rules & Restrictions
- Users must be approved by admin and have a complete profile with skills to access features.
- Only valid users are shown in matching/search.
- Both users must confirm session completion before feedback is allowed.
- Max 5 exchange requests per user per day.

## How to Run
1. Install dependencies:
  ```
  pip install -r requirements.txt
  ```
2. Run the app:
  ```
  python app.py
  ```
3. Access at `http://localhost:5000`

## Typical User Flow
1. Register → Complete Profile + Skills
2. Wait for Admin Approval
3. Access Dashboard (if approved & profile complete)
4. Search & Match (only valid users shown, sorted by rating)
5. Send Request (max 5/day)
6. Session Created (on request acceptance)
7. Real-time chat enabled for matched users
8. Both users confirm session completion
9. Feedback (only after session completion)

## AI Matching Logic
The core matching logic is implemented in `services/matching.py` using scikit-learn and pandas. It computes skill similarity between users based on offered and wanted skills, and recommends the best matches using cosine similarity.

## Real-Time Chat
Real-time chat is powered by Flask-SocketIO. Users can chat after a request is accepted and a session is created.

## Future Roadmap
- Multi-university support (PostgreSQL migration)
- Enhanced analytics and notifications

## Mail Notification Setup
This project uses Flask-Mail for email notifications. To enable mail notifications:
1. Add these environment variables (or update `app.config` in `app.py`):
  - `MAIL_USERNAME` (your SMTP username/email)
  - `MAIL_PASSWORD` (your SMTP password)
  - `MAIL_DEFAULT_SENDER` (optional, default sender email)
2. The default config uses Gmail SMTP. Update as needed for your provider.

## Requirements
- Flask==3.0.3
- Flask-SQLAlchemy==3.1.1
- Flask-Login==0.6.3
- Flask-Mail
- Flask-SocketIO
- pandas
- scikit-learn
- Werkzeug==3.0.3

---

Let me know if you want to add more details or customize any section!
