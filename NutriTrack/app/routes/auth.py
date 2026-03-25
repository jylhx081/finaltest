from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from datetime import datetime

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('auth.register'))
            
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('auth.register'))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        # Log the user in directly
        login_user(user)
        user.last_login_time = datetime.now()
        db.session.commit()
        
        flash('注册成功！请完成健康评测以获取定制计划。', 'success')
        return redirect(url_for('auth.assessment'))

    return render_template('register.html')

@auth_bp.route('/assessment', methods=['GET', 'POST'])
@login_required
def assessment():
    if request.method == 'POST':
        # Basic Info
        raw_gender = request.form.get('gender')
        current_user.gender = '男' if raw_gender == 'Male' else '女'
        
        current_user.age = int(request.form.get('age'))
        current_user.height = float(request.form.get('height'))
        current_user.weight = float(request.form.get('weight'))
        
        # Goals
        current_user.target_weight = float(request.form.get('target_weight'))
        deadline_str = request.form.get('goal_deadline')
        if deadline_str:
            current_user.goal_deadline = datetime.strptime(deadline_str, '%Y-%m-%d')
            
        # Map exercise level to frequency and save both
        level_map = {
            'sedentary': '久坐不动',
            'light': '每周1-2次',
            'moderate': '每周3-4次',
            'active': '每周5-6次',
            'very_active': '每天'
        }
        raw_level = request.form.get('exercise_level')
        current_user.exercise_level = raw_level
        current_user.exercise_frequency = level_map.get(raw_level, '久坐不动')
        
        # Preferences
        # Map dietary preference to Chinese
        diet_map = {
            'None': '正常饮食',
            'Vegetarian': '素食',
            'LowCarb': '低碳水',
            'HighProtein': '高蛋白'
        }
        raw_diet = request.form.get('dietary_preference')
        current_user.dietary_preference = diet_map.get(raw_diet, '正常饮食')
        
        current_user.allergies = request.form.get('allergies')
        
        # Infer Health Goal based on weights
        if current_user.target_weight < current_user.weight - 2:
            current_user.health_goal = '减脂'
        elif current_user.target_weight > current_user.weight + 2:
            current_user.health_goal = '增肌'
        else:
            current_user.health_goal = '维持体重'
        
        # Calculate BMI & BMR
        height_m = current_user.height / 100
        current_user.bmi = round(current_user.weight / (height_m * height_m), 1)
        
        if current_user.bmi < 18.5:
            current_user.bmi_category = 'Underweight'
        elif current_user.bmi < 25:
            current_user.bmi_category = 'Normal'
        elif current_user.bmi < 30:
            current_user.bmi_category = 'Overweight'
        else:
            current_user.bmi_category = 'Obese'
            
        # Mifflin-St Jeor Equation
        if current_user.gender == '男':
            current_user.bmr = int(10 * current_user.weight + 6.25 * current_user.height - 5 * current_user.age + 5)
        else:
            current_user.bmr = int(10 * current_user.weight + 6.25 * current_user.height - 5 * current_user.age - 161)
            
        db.session.commit()
        
        flash('评测完成！已为您生成专属仪表盘。', 'success')
        return redirect(url_for('dashboard.index'))
        
    return render_template('assessment.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('auth.login'))
        
        if user.status == 0:
            flash('Account disabled.', 'danger')
            return redirect(url_for('auth.login'))

        login_user(user, remember=remember)
        user.last_login_time = datetime.now()
        db.session.commit()
        
        return redirect(url_for('dashboard.index'))

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
