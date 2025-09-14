import os
from flask import Flask, jsonify, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin, LoginManager, login_required, current_user, login_user, logout_user
from dotenv import load_dotenv
from sqlalchemy.orm import joinedload
from flask_caching import Cache
from flask_cors import CORS
from flask_migrate import Migrate
from datetime import datetime 

load_dotenv()

app = Flask(__name__)
CORS(app)  

try:
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_default_secret_key')
    app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
    connection = engine.connect()
    connection.close()
    print("Successfully connected to PostgreSQL database")
except Exception as e:
    print(f"PostgreSQL connection failed: {e}")
    print("Falling back to SQLite database")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///jobportle.db'
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_default_secret_key')
    app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'

db = SQLAlchemy(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(100), nullable=False)
    heading = db.Column(db.String(100), nullable=True)
    role = db.Column(db.String(100), nullable=False)
    applylink = db.Column(db.String(200), nullable=False)
    desc = db.Column(db.Text, nullable=False)
    company_url = db.Column(db.String(200), nullable=True) 
    created_at = db.Column(db.DateTime, default=datetime.now(datetime.timezone.utc)) 

    def __repr__(self):
        return self.role

    def to_dict(self):
        return {
            'id': self.id,
            'company': self.company,
            'heading': self.heading,
            'role': self.role,
            'applylink': self.applylink,
            'desc': self.desc,
            'company_url': self.company_url,
            'created_at': self.created_at.strftime('%Y-%m-%d') if self.created_at else None 
        }

admin = Admin(app, name='Job Portal Admin', template_mode='bootstrap4')

class MyModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('login'))

    def _description_formatter(view, context, model, name):
        desc = getattr(model, name)
        words = desc.split()[:12]
        return ' '.join(words) + '...' if len(words) >= 12 else desc

    def after_model_change(self, form, model, is_created):
        pass

    column_formatters = {
        'desc': _description_formatter
    }

admin.add_view(MyModelView(Job, db.session))
admin.add_view(MyModelView(User, db.session))

@app.before_request
def before_request():
    if request.path.startswith('/admin') and not current_user.is_authenticated:
        return redirect(url_for('login'))

@app.route('/api/jobs', methods=['GET'])
def get_all_jobs():
    jobs = Job.query.options(joinedload('*')).all()
    return jsonify([job.to_dict() for job in jobs])

@app.route('/api/jobs/<int:job_id>', methods=['GET'])
def get_job(job_id):
    job = Job.query.options(joinedload('*')).get_or_404(job_id)
    return jsonify(job.to_dict())

@app.route('/api/jobs/new', methods=['GET'])
def get_new_jobs():
    jobs = Job.query.options(joinedload('*')).order_by(Job.id.desc()).all()
    return jsonify([job.to_dict() for job in jobs])

@app.route('/api/jobs/role/<string:role>', methods=['GET'])
def get_jobs_by_role(role):
    jobs = Job.query.options(joinedload('*')).filter_by(role=role).all()
    return jsonify([job.to_dict() for job in jobs])

@app.route('/api/jobs/company/<string:company>', methods=['GET'])
def get_jobs_by_company(company):
    jobs = Job.query.options(joinedload('*')).filter_by(company=company).all()
    return jsonify([job.to_dict() for job in jobs])

@app.route('/api/jobs/page/<int:page>', methods=['GET'])
def get_jobs_paginated(page):
    per_page = 20
    jobs = Job.query.options(joinedload('*')).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'jobs': [job.to_dict() for job in jobs.items],
        'total': jobs.total,
        'pages': jobs.pages,
        'current_page': jobs.page
    })

@app.route('/api/jobs/search', methods=['GET'])
def search_jobs():
    query = request.args.get('q', '')
    jobs = Job.query.options(joinedload('*')).filter(
        (Job.role.ilike(f'%{query}%')) |
        (Job.company.ilike(f'%{query}%')) |
        (Job.desc.ilike(f'%{query}%')) |
        (Job.heading.ilike(f'%{query}%'))
    ).all()
    return jsonify([job.to_dict() for job in jobs])

def initialize_database():
    with app.app_context():
        db.create_all()
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash('admin@12345')
            )
            db.session.add(admin_user)
            db.session.commit()

initialize_database()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('admin.index'))
        else:
            return render_template('login.html', error='Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def greet():
    return jsonify({"message": "hello!"})

if __name__ == '__main__':
    app.run(debug=True)