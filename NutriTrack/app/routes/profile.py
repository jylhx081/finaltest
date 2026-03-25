# app/routes/profile.py - 更新后的个人信息路由文件

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models.user import User
from werkzeug.security import check_password_hash, generate_password_hash

# 创建蓝图
profile_bp = Blueprint('profile', __name__, url_prefix='/profile')


# ====================== 个人中心首页 ======================
@profile_bp.route('/')
@profile_bp.route('/index')
@login_required
def index():
    """个人中心首页"""
    return render_template('profile.html')


# ====================== 设置页面 ======================
@profile_bp.route('/settings')
@login_required
def settings():
    """设置页面"""
    return render_template('settings.html')


# ====================== 更新个人信息 ======================
@profile_bp.route('/update_info', methods=['POST'])
@login_required
def update_info():
    """更新个人信息"""
    try:
        user = User.query.get(current_user.id)

        # 更新年龄
        age = request.form.get('age')
        if age:
            user.age = int(age)

        # 更新性别
        gender = request.form.get('gender')
        if gender:
            user.gender = gender

        # 更新身高体重
        height = request.form.get('height')
        weight = request.form.get('weight')

        if height:
            user.height = float(height)

        if weight:
            user.weight = float(weight)

        # 更新运动频率
        exercise_frequency = request.form.get('exercise_frequency')
        if exercise_frequency:
            user.exercise_frequency = exercise_frequency

        # 重新计算BMI
        if user.height and user.weight:
            user.bmi = round(user.weight / ((user.height / 100) ** 2), 2)

            # 根据BMI设置分类
            if user.bmi < 18.5:
                user.bmi_category = '偏瘦'
            elif 18.5 <= user.bmi < 24:
                user.bmi_category = '正常'
            elif 24 <= user.bmi < 28:
                user.bmi_category = '超重'
            else:
                user.bmi_category = '肥胖'

        # 重新计算BMR（基础代谢率）并根据运动频率调整
        if user.age and user.gender and user.height and user.weight:
            if user.gender == '男' or user.gender == 'Male':
                # 男性：BMR = 10 * 体重(kg) + 6.25 * 身高(cm) - 5 * 年龄 + 5
                base_bmr = 10 * user.weight + 6.25 * user.height - 5 * user.age + 5
            else:
                # 女性：BMR = 10 * 体重(kg) + 6.25 * 身高(cm) - 5 * 年龄 - 161
                base_bmr = 10 * user.weight + 6.25 * user.height - 5 * user.age - 161

            # 根据运动频率调整BMR
            exercise_factor = 1.2  # 默认久坐不动
            if user.exercise_frequency == '每周1-2次':
                exercise_factor = 1.375
            elif user.exercise_frequency == '每周3-4次':
                exercise_factor = 1.55
            elif user.exercise_frequency == '每周5-6次':
                exercise_factor = 1.725
            elif user.exercise_frequency == '每天':
                exercise_factor = 1.9

            user.bmr = round(base_bmr * exercise_factor)

        db.session.commit()
        flash('个人信息更新成功！', 'success')
        return redirect(url_for('profile.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'更新失败：{str(e)}', 'error')
        return redirect(url_for('profile.index'))


# ====================== 更新饮食习惯 ======================
@profile_bp.route('/update_eating_habits', methods=['POST'])
@login_required
def update_eating_habits():
    """更新饮食习惯"""
    try:
        user = User.query.get(current_user.id)

        # 更新饮食偏好
        dietary_preference = request.form.get('dietary_preference')
        if dietary_preference:
            user.dietary_preference = dietary_preference

        # 更新过敏食物
        allergies = request.form.get('allergies')
        if allergies:
            user.allergies = allergies

        # 更新喜爱的食物
        favorite_foods = request.form.get('favorite_foods')
        if favorite_foods:
            user.favorite_foods = favorite_foods

        db.session.commit()
        flash('饮食习惯更新成功！', 'success')
        return redirect(url_for('profile.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'更新失败：{str(e)}', 'error')
        return redirect(url_for('profile.index'))


# ====================== 更新运动习惯 ======================
@profile_bp.route('/update_exercise_habits', methods=['POST'])
@login_required
def update_exercise_habits():
    """更新运动习惯"""
    try:
        user = User.query.get(current_user.id)

        # 更新运动频率
        exercise_frequency = request.form.get('exercise_frequency')
        if exercise_frequency:
            user.exercise_frequency = exercise_frequency

        # 更新运动强度
        exercise_level = request.form.get('exercise_level')
        if exercise_level:
            user.exercise_level = exercise_level

        # 重新计算BMR（基础代谢率）并根据运动频率调整
        if user.age and user.gender and user.height and user.weight:
            if user.gender == '男' or user.gender == 'Male':
                # 男性：BMR = 10 * 体重(kg) + 6.25 * 身高(cm) - 5 * 年龄 + 5
                base_bmr = 10 * user.weight + 6.25 * user.height - 5 * user.age + 5
            else:
                # 女性：BMR = 10 * 体重(kg) + 6.25 * 身高(cm) - 5 * 年龄 - 161
                base_bmr = 10 * user.weight + 6.25 * user.height - 5 * user.age - 161

            # 根据运动频率调整BMR
            exercise_factor = 1.2  # 默认久坐不动
            if user.exercise_frequency == '每周1-2次':
                exercise_factor = 1.375
            elif user.exercise_frequency == '每周3-4次':
                exercise_factor = 1.55
            elif user.exercise_frequency == '每周5-6次':
                exercise_factor = 1.725
            elif user.exercise_frequency == '每天':
                exercise_factor = 1.9

            user.bmr = round(base_bmr * exercise_factor)

        db.session.commit()
        flash('运动习惯更新成功！', 'success')
        return redirect(url_for('profile.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'更新失败：{str(e)}', 'error')
        return redirect(url_for('profile.index'))


# ====================== 更新健康目标 ======================
@profile_bp.route('/update_health_goal', methods=['POST'])
@login_required
def update_health_goal():
    """更新健康目标"""
    try:
        user = User.query.get(current_user.id)

        # 更新健康目标
        health_goal = request.form.get('health_goal')
        if health_goal:
            user.health_goal = health_goal

        db.session.commit()
        flash('健康目标更新成功！', 'success')
        return redirect(url_for('profile.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'更新失败：{str(e)}', 'error')
        return redirect(url_for('profile.index'))


# ====================== 修改密码 ======================
@profile_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """修改密码"""
    try:
        user = User.query.get(current_user.id)

        # 获取表单数据
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # 验证当前密码
        if not check_password_hash(user.password_hash, current_password):
            flash('当前密码错误！', 'error')
            return redirect(url_for('profile.settings'))

        # 验证新密码和确认密码是否一致
        if new_password != confirm_password:
            flash('新密码和确认密码不一致！', 'error')
            return redirect(url_for('profile.settings'))

        # 更新密码
        user.set_password(new_password)
        db.session.commit()

        flash('密码修改成功！', 'success')
        return redirect(url_for('profile.settings'))

    except Exception as e:
        db.session.rollback()
        flash(f'密码修改失败：{str(e)}', 'error')
        return redirect(url_for('profile.settings'))
