from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.models.record import DietRecord
from app.models.food import Dish
from app import db
from datetime import datetime, timedelta
from sqlalchemy import func
import json

statistics_bp = Blueprint('statistics', __name__, url_prefix='/statistics')

def get_date_range(range_type, custom_start=None, custom_end=None):
    today = datetime.now().date()
    end_date = today
    
    if range_type == 'week':
        start_date = today - timedelta(days=6) # 7 days including today
    elif range_type == 'month':
        start_date = today - timedelta(days=29)
    elif range_type == 'quarter':
        start_date = today - timedelta(days=89)
    elif range_type == 'year':
        start_date = today - timedelta(days=364)
    elif range_type == 'custom' and custom_start and custom_end:
        start_date = datetime.strptime(custom_start, '%Y-%m-%d').date()
        end_date = datetime.strptime(custom_end, '%Y-%m-%d').date()
    else:
        start_date = today - timedelta(days=6) # Default to week
        
    return start_date, end_date

@statistics_bp.route('/')
@login_required
def index():
    range_type = request.args.get('range', 'week')
    custom_start = request.args.get('start')
    custom_end = request.args.get('end')
    
    start_date, end_date = get_date_range(range_type, custom_start, custom_end)
    
    # 1. Fetch Records
    records = DietRecord.query.filter(
        DietRecord.user_id == current_user.id,
        func.date(DietRecord.create_time) >= start_date,
        func.date(DietRecord.create_time) <= end_date
    ).order_by(DietRecord.create_time.desc()).all()
    
    # 2. Calculate Overview Stats
    total_calories = sum(r.total_calorie for r in records if r.total_calorie)
    total_protein = sum(r.total_protein for r in records if r.total_protein)
    total_fat = sum(r.total_fat for r in records if r.total_fat)
    total_carbs = sum(r.total_carb for r in records if r.total_carb)
    
    num_days = (end_date - start_date).days + 1
    avg_calories = total_calories / num_days if num_days > 0 else 0
    avg_protein = total_protein / num_days if num_days > 0 else 0
    avg_fat = total_fat / num_days if num_days > 0 else 0
    avg_carbs = total_carbs / num_days if num_days > 0 else 0
    
    # 3. Previous Period Comparison
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=num_days-1)
    
    prev_records = DietRecord.query.filter(
        DietRecord.user_id == current_user.id,
        func.date(DietRecord.create_time) >= prev_start,
        func.date(DietRecord.create_time) <= prev_end
    ).all()
    
    prev_calories = sum(r.total_calorie for r in prev_records if r.total_calorie)
    
    cal_change = 0
    if prev_calories > 0:
        cal_change = ((total_calories - prev_calories) / prev_calories) * 100
        
    # 4. Goals (Simple estimation if not set)
    # BMR calculation (Mifflin-St Jeor) already in auth.py, assuming stored in user
    daily_cal_goal = current_user.bmr * 1.2 if current_user.bmr else 2000 
    # Adjust for exercise if available (simple map)
    if current_user.exercise_frequency:
        freq_map = {
            '久坐不动': 1.2,
            '每周1-2次': 1.375,
            '每周3-4次': 1.55,
            '每周5-6次': 1.725,
            '每天': 1.9
        }
        multiplier = freq_map.get(current_user.exercise_frequency, 1.2)
        daily_cal_goal = (current_user.bmr or 1600) * multiplier
        
    goal_achievement = (avg_calories / daily_cal_goal * 100) if daily_cal_goal > 0 else 0
    
    # Nutrient Goals (Standard ratios: 50% Carb, 30% Fat, 20% Protein)
    goal_protein = (daily_cal_goal * 0.20) / 4
    goal_fat = (daily_cal_goal * 0.30) / 9
    goal_carbs = (daily_cal_goal * 0.50) / 4
    
    # 5. Chart Data Preparation
    
    # Trend Chart
    date_map = {}
    curr = start_date
    while curr <= end_date:
        date_map[curr.strftime('%Y-%m-%d')] = 0
        curr += timedelta(days=1)
        
    for r in records:
        d_str = r.create_time.strftime('%Y-%m-%d')
        if d_str in date_map:
            date_map[d_str] += (r.total_calorie or 0)
            
    trend_labels = list(date_map.keys())
    trend_data = list(date_map.values())
    trend_goal = [daily_cal_goal] * len(trend_labels)
    
    # Meal Distribution
    meal_map = {1: 0, 2: 0, 3: 0, 4: 0} # 1=Breakfast, 2=Lunch, 3=Dinner, 4=Snack (assuming 4 is snack or others)
    for r in records:
        m_type = r.meal_type if r.meal_type in [1, 2, 3] else 4
        meal_map[m_type] += (r.total_calorie or 0)
        
    meal_data = [meal_map[1], meal_map[2], meal_map[3], meal_map[4]]
    
    # Radar Data (Actual vs Recommended)
    # Normalize to 100% of goal
    radar_actual = [
        min((avg_protein / goal_protein * 100) if goal_protein else 0, 150), # Cap at 150% for visualization
        min((avg_carbs / goal_carbs * 100) if goal_carbs else 0, 150),
        min((avg_fat / goal_fat * 100) if goal_fat else 0, 150)
    ]
    radar_labels = ['蛋白质', '碳水化合物', '脂肪']
    
    # 6. Detailed Table Data
    # Flatten records if they contain multiple dishes (though dish_list is JSON list)
    table_data = []
    for r in records:
        try:
            dishes = json.loads(r.dish_list) if r.dish_list else []
            # If dishes list is empty but totals exist, show a summary row
            if not dishes:
                table_data.append({
                    'date': r.create_time.strftime('%Y-%m-%d'),
                    'meal_type': get_meal_name(r.meal_type),
                    'dish_name': '未命名餐食',
                    'weight': '-',
                    'calories': r.total_calorie,
                    'protein': r.total_protein,
                    'fat': r.total_fat,
                    'carbs': r.total_carb,
                    'id': r.id
                })
            else:
                for dish in dishes:
                    # Logic to distribute nutrition or show per dish if available
                    # Assuming dish object in list has nutrition info? 
                    # Previous 'detect_dish' saves: {'dish_name':..., 'weight':..., 'nutrition':...} 
                    # Need to verify what is saved in diet_records.
                    # For now, just listing the dish names or aggregating them might be safer if individual nutrtion isn't saved.
                    # Let's assume the dish list items have 'dish_name' and 'weight'.
                    # We might not have per-dish nutrition in the JSON if it wasn't saved.
                    # If not, we just show the record total in the first row and empty in others, or just list dishes names concatenated.
                    pass
                
                # Simplified: Create one row per record, join dish names
                dish_names = ", ".join([d.get('dish_name', '未知') for d in dishes])
                total_weight = sum([float(d.get('weight', 0)) for d in dishes])
                
                table_data.append({
                    'date': r.create_time.strftime('%Y-%m-%d'),
                    'meal_type': get_meal_name(r.meal_type),
                    'dish_name': dish_names,
                    'weight': total_weight,
                    'calories': r.total_calorie,
                    'protein': r.total_protein,
                    'fat': r.total_fat,
                    'carbs': r.total_carb,
                    'id': r.id
                })
        except:
            continue

    return render_template('statistics.html', 
                           start_date=start_date,
                           end_date=end_date,
                           total_calories=int(total_calories),
                           avg_calories=int(avg_calories),
                           cal_change=round(cal_change, 1),
                           goal_achievement=int(goal_achievement),
                           total_protein=int(total_protein),
                           avg_protein=int(avg_protein),
                           total_fat=int(total_fat),
                           avg_fat=int(avg_fat),
                           total_carbs=int(total_carbs),
                           avg_carbs=int(avg_carbs),
                           trend_labels=trend_labels,
                           trend_data=trend_data,
                           trend_goal=trend_goal,
                           meal_data=meal_data,
                           radar_labels=radar_labels,
                           radar_actual=radar_actual,
                           table_data=table_data,
                           today_date=datetime.now().strftime('%Y-%m-%d'))

def get_meal_name(type_id):
    if type_id == 1: return '早餐'
    if type_id == 2: return '午餐'
    if type_id == 3: return '晚餐'
    return '加餐'
