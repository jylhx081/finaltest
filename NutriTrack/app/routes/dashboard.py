from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models.record import DietRecord, Feedback, DishRating
from app.models.user import User
from app.models.food import Dish, DishIngredient, NutritionFacts
from app.utils.recommendation import recommend_dishes
import pandas as pd
from datetime import datetime, date, timedelta
import requests

dashboard_bp = Blueprint('dashboard', __name__)

# Doubao / 豆包 API 配置（用于仪表盘 AI 对话）
DOUBAO_API_KEY = 'af393bda-ddf7-48cb-9c93-fe5aba81b3eb'
DOUBAO_API_URL = 'https://ark.cn-beijing.volces.com/api/v3/chat/completions'
DOUBAO_MODEL_ID = 'ep-20260228024230-tg9rm'

def get_all_dishes_with_nutrition(user_id):
    """Helper to fetch all dishes visible to user (global + own) with their calculated total nutrients."""
    dishes = Dish.query.filter(Dish.visible_to_user(user_id)).all()
    dish_pool = []
    
    for dish in dishes:
        # Calculate nutrients for this dish
        dish_ingredients = DishIngredient.query.filter_by(dish_id=dish.dish_id).all()
        
        calories = 0
        protein = 0
        fat = 0
        carbs = 0
        
        for di in dish_ingredients:
            nutrition = NutritionFacts.query.get(di.ingredient_id)
            if nutrition:
                ratio = di.amount_g / 100.0
                calories += nutrition.energy_kcal * ratio
                protein += nutrition.protein_g * ratio
                fat += nutrition.fat_g * ratio
                carbs += nutrition.carb_g * ratio
        
        dish_pool.append({
            'id': dish.dish_id,
            'name': dish.name,
            'calories': calories,
            'protein': protein,
            'fat': fat,
            'carbs': carbs,
            'canteen_id': dish.canteen_id,
        })
    
    return dish_pool

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@login_required
def index():
    # 获取请求的日期参数，默认为今天
    date_str = request.args.get('date')
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = date.today()
    else:
        target_date = date.today()

    # BMI Calculation
    bmi = 0
    if current_user.height and current_user.weight:
        height_m = current_user.height / 100
        bmi = round(current_user.weight / (height_m * height_m), 1)

    # BMR Calculation (使用用户模型中已计算的BMR)
    bmr = current_user.bmr if current_user.bmr else 0

    # 计算每日所需营养素
    nutrition_needs = calculate_daily_nutrition(
        bmr, current_user.health_goal, current_user.weight, current_user.exercise_frequency)

    # 获取指定日期的记录
    records = DietRecord.query.filter(
        DietRecord.user_id == current_user.id,
        db.func.date(DietRecord.create_time) == target_date
    ).all()

    today_nutrition = {
        'calories': 0,
        'protein': 0,
        'fat': 0,
        'carb': 0
    }

    meals = {1: [], 2: [], 3: []}  # Breakfast, Lunch, Dinner

    for record in records:
        today_nutrition['calories'] += record.total_calorie or 0
        today_nutrition['protein'] += record.total_protein or 0
        today_nutrition['fat'] += record.total_fat or 0
        today_nutrition['carb'] += record.total_carb or 0

        if record.meal_type in meals:
            meals[record.meal_type].append(record)

    # 计算营养缺口 (Rounding to 1 decimal place)
    nutrition_gaps = {
        'calories': round(max(0, nutrition_needs['calories'] - today_nutrition['calories']), 1),
        'protein': round(max(0, nutrition_needs['protein'] - today_nutrition['protein']), 1),
        'fat': round(max(0, nutrition_needs['fat'] - today_nutrition['fat']), 1),
        'carb': round(max(0, nutrition_needs['carb'] - today_nutrition['carb']), 1)
    }

    # Calculate percentages for progress bars
    def safe_percent(actual, target):
        if not target or target <= 0:
            return 0
        return min(100, int((actual / target) * 100))

    nutrition_percents = {
        'protein': safe_percent(today_nutrition['protein'], nutrition_needs['protein']),
        'fat': safe_percent(today_nutrition['fat'], nutrition_needs['fat']),
        'carb': safe_percent(today_nutrition['carb'], nutrition_needs['carb']),
        'calories': safe_percent(today_nutrition['calories'], nutrition_needs['calories']),
    }

    # --- Intelligent Recommendation Integration ---
    recommendations = []
    main_gap_message = "营养摄入均衡"
    
    # Prepare data for recommendation engine
    if nutrition_gaps['protein'] > 0 or nutrition_gaps['fat'] > 0 or nutrition_gaps['carb'] > 0 or nutrition_gaps['calories'] > 0:
        # User Profile
        user_profile = {
            'weight': current_user.weight,
            'height': current_user.height,
            'age': current_user.age,
            'gender': current_user.gender,
            'activity_level': current_user.exercise_frequency, 
            'health_goal': current_user.health_goal
        }
        
        # Current Intake Dummy (as recommend_dishes expects list of dishes)
        current_intake_dummy = [
            {
                'name': 'Today Total', 
                'weight': 1, 
                'calories': today_nutrition['calories'],
                'protein': today_nutrition['protein'],
                'fat': today_nutrition['fat'],
                'carbs': today_nutrition['carb']
            }
        ]
        
        # Dish Pool
        dish_pool = get_all_dishes_with_nutrition(current_user.id)

        # Rating Matrix: 从 DishRating 表构建 -1/0/1 矩阵
        all_ratings = DishRating.query.all()
        if all_ratings:
            rows = []
            for r in all_ratings:
                rows.append({
                    'user': str(r.user_id),
                    'dish_id': r.dish_id,
                    'rating': int(r.rating),
                })
            rating_df = pd.DataFrame(rows)
            rating_matrix = rating_df.pivot(index='user', columns='dish_id', values='rating')
        else:
            rating_matrix = pd.DataFrame()
        
        # Call Recommendation Engine
        try:
            recommendations = recommend_dishes(
                user_profile, 
                current_intake_dummy, 
                dish_pool, 
                rating_matrix, 
                user_id=str(current_user.id),
                top_n=6
            )
        except Exception as e:
            print(f"Recommendation Error: {e}")
            recommendations = []
            
        # Determine Main Gap Message
        if nutrition_gaps['protein'] > 10:
            main_gap_message = "您今日蛋白质摄入明显不足，建议补充高蛋白食物。"
        elif nutrition_gaps['carb'] > 50:
            main_gap_message = "您今日碳水化合物摄入偏低，能量可能不足。"
        elif nutrition_gaps['fat'] > 10:
            main_gap_message = "您今日脂肪摄入不足，建议补充健康油脂。"
        elif nutrition_gaps['calories'] > 200:
            main_gap_message = "总热量摄入未达标，请适当加餐。"
        else:
             main_gap_message = "您的营养摄入基本达标，继续保持！"

    # 获取前后几天的日期用于导航
    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)

    return render_template('dashboard.html',
                           bmi=bmi,
                           bmr=bmr,
                           nutrition_needs=nutrition_needs,
                           nutrition_gaps=nutrition_gaps,
                           today_nutrition=today_nutrition,
                           nutrition_percents=nutrition_percents,
                           meals=meals,
                           target_date=target_date,
                           prev_date=prev_date,
                           next_date=next_date,
                           today_date=target_date.strftime('%Y-%m-%d'),
                           recommendations=recommendations,
                           main_gap_message=main_gap_message)


@dashboard_bp.route('/feedback', methods=['POST'])
@login_required
def submit_feedback():
    """用户在仪表盘提交对菜品/推荐的反馈。"""
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'status': 'error', 'message': '反馈内容不能为空'})

    fb = Feedback(user_id=current_user.id, content=content)
    db.session.add(fb)
    db.session.commit()

    return jsonify({'status': 'success', 'message': '感谢您的反馈，我们会用于优化菜品与推荐算法。'})


@dashboard_bp.route('/rate_dish', methods=['POST'])
@login_required
def rate_dish():
    """用户对菜品打分：-1 不喜欢，0 中性/撤销，1 喜欢。"""
    data = request.get_json() or {}
    dish_id = (data.get('dish_id') or '').strip()
    try:
        rating = int(data.get('rating', 0))
    except (TypeError, ValueError):
        rating = 0

    if rating not in (-1, 0, 1):
        return jsonify({'status': 'error', 'message': '非法评分取值。'}), 400

    if not dish_id:
        return jsonify({'status': 'error', 'message': '缺少菜品编号。'}), 400

    # 确保菜品存在且对当前用户可见
    dish = Dish.query.filter(Dish.visible_to_user(current_user.id)).filter(Dish.dish_id == dish_id).first()
    if not dish:
        return jsonify({'status': 'error', 'message': '菜品不存在或无权评分。'}), 404

    existing = DishRating.query.filter_by(user_id=current_user.id, dish_id=dish_id).first()
    if rating == 0:
        # 0 视为撤销评分：删除记录或设为 0
        if existing:
            db.session.delete(existing)
            db.session.commit()
        return jsonify({'status': 'success', 'message': '已清除对该菜品的评分。'})

    if existing:
        existing.rating = rating
    else:
        db.session.add(DishRating(user_id=current_user.id, dish_id=dish_id, rating=rating))

    db.session.commit()
    return jsonify({'status': 'success', 'message': '评分已保存。'})


@dashboard_bp.route('/ai_recommend', methods=['POST'])
@login_required
def ai_recommend():
    """仪表盘 AI 对话接口：根据菜品库给出搭配建议。"""
    data = request.get_json() or {}
    user_prompt = (data.get('prompt') or '').strip()
    if not user_prompt:
        return jsonify({'status': 'error', 'message': '请输入您的问题或需求。'})

    # 仅使用当前用户可见的菜品库（全局 + 个人）
    dishes = Dish.query.filter(Dish.visible_to_user(current_user.id)).order_by(Dish.name).all()

    # 构造给 LLM 的菜品清单，控制在较简洁的文本形式
    menu_lines = []
    for d in dishes:
        parts = [d.name]
        if d.cooking_method:
            parts.append(f"做法:{d.cooking_method}")
        if d.unit_type == 'piece':
            unit_label = '个'
        elif d.unit_type == 'slice':
            unit_label = '片'
        elif d.unit_type == 'stick':
            unit_label = '根'
        else:
            unit_label = '份'
        parts.append(f"单位:{unit_label}({int(d.unit_weight or 100)}g)")
        menu_lines.append("，".join(parts))

    menu_text = "\n".join(menu_lines[:200])  # 避免极端超长，只取前 200 个

    system_prompt = (
        "你是一个学校食堂的营养搭配助手，需要只基于下面提供的菜品库进行推荐，"
        "不要自己发明菜单中不存在的菜品。\n"
        "目标是：营养均衡，控制油炸、红肉不过量，多考虑蔬菜和优质蛋白，"
        "并且搭配要贴近日常食堂场景（简单、可实际供应）。\n\n"
        "【可用菜品库】（每一行是一个菜品）:\n"
        f"{menu_text}\n\n"
        "回答要求：\n"
        "1. 优先使用以上菜品名称进行搭配，不要出现列表以外的菜名；\n"
        "2. 给出清晰的搭配列表（例如：一荤两素），并简单说明营养理由；\n"
        "3. 尽量用简体中文回答。"
    )

    payload = {
        "model": DOUBAO_MODEL_ID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 512,
    }

    headers = {
        "Authorization": f"Bearer {DOUBAO_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(DOUBAO_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # 豆包接口兼容 OpenAI 格式：choices[0].message.content
        choices = data.get("choices") or []
        if not choices:
            return jsonify({'status': 'error', 'message': 'AI 未返回结果，请稍后重试。'})
        reply = choices[0].get("message", {}).get("content", "").strip()
        if not reply:
            reply = "抱歉，我暂时没有生成有效的建议，请稍后再试。"
        return jsonify({'status': 'success', 'reply': reply})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'调用 AI 接口失败：{e}'}), 500


def calculate_daily_nutrition(bmr, health_goal, weight, exercise_frequency):
    """根据BMR、健康目标、体重和运动频率计算每日所需营养素"""
    # Safety check for missing weight
    if not weight:
        weight = 60 # Default fallback
    
    # 基础热量需求
    calories = bmr

    # 根据健康目标调整热量需求
    if health_goal == '减脂':
        calories = int(bmr * 0.8)  # 减少20%热量摄入
    elif health_goal == '增肌':
        calories = int(bmr * 1.2)  # 增加20%热量摄入
    elif health_goal == '更健康':
        calories = bmr  # 维持当前热量摄入
    elif health_goal == '维持体重':
        calories = bmr  # 维持当前热量摄入

    # 根据体重和运动频率计算蛋白质需求（按体重克数法）
    protein_per_kg = 0.8  # 默认久坐人群

    if exercise_frequency == '久坐不动':
        protein_per_kg = 0.8  # 久坐人群
    elif exercise_frequency == '每周1-2次':
        protein_per_kg = 1.0  # 轻度活动者
    elif exercise_frequency == '每周3-4次':
        protein_per_kg = 1.2  # 中等强度运动者
    elif exercise_frequency == '每周5-6次':
        protein_per_kg = 1.3  # 高强度运动者
    elif exercise_frequency == '每天':
        protein_per_kg = 1.5  # 高强度运动者

    protein = int(weight * protein_per_kg)  # 按体重计算蛋白质需求(克)

    # 计算脂肪需求（占总热量的25%）
    fat_calories = calories * 0.25
    fat = int(fat_calories / 9)  # 每克脂肪9千卡

    # 计算碳水化合物需求（剩余热量）
    protein_calories = protein * 4  # 蛋白质提供热量
    carb_calories = calories - protein_calories - fat_calories
    carb = int(carb_calories / 4)   # 每克碳水化合物4千卡

    # 确保碳水化合物不为负数
    carb = max(0, carb)

    return {
        'calories': calories,
        'protein': protein,
        'fat': fat,
        'carb': carb
    }


@dashboard_bp.route('/update_health_goal', methods=['POST'])
@login_required
def update_health_goal():
    goal = request.form.get('health_goal')
    current_user.health_goal = goal
    db.session.commit()
    flash('健康目标更新成功！', 'success')
    return redirect(url_for('dashboard.index'))
