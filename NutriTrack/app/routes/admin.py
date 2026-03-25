from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.record import DetectionRecord, DietRecord, Feedback
from functools import wraps
from datetime import datetime, timedelta, date
from io import BytesIO
import json
import pandas as pd

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.is_admin != 1:
            flash('Access denied. Admin privileges required.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    total_users = User.query.count()
    active_users = User.query.filter_by(status=1).count()
    detection_count = DetectionRecord.query.count()
    admin_count = User.query.filter_by(is_admin=1).count()
    
    return render_template('admin_dashboard.html',
                           total_users=total_users,
                           active_users=active_users,
                           detection_count=detection_count,
                           admin_count=admin_count)

@admin_bp.route('/user_manage')
@login_required
@admin_required
def user_manage():
    page = request.args.get('page', 1, type=int)
    users = User.query.paginate(page=page, per_page=10)
    return render_template('admin_user_manage.html', users=users)

@admin_bp.route('/update_user', methods=['POST'])
@login_required
@admin_required
def update_user():
    user_id = request.form.get('user_id')
    action = request.form.get('action')
    
    user = User.query.get(user_id)
    if user:
        if action == 'toggle_status':
            user.status = 1 if user.status == 0 else 0
        elif action == 'toggle_admin':
            user.is_admin = 1 if user.is_admin == 0 else 0
        elif action == 'delete':
            db.session.delete(user)
            
        db.session.commit()
        flash('User updated successfully', 'success')
    else:
        flash('User not found', 'danger')
        
    return redirect(url_for('admin.user_manage'))

@admin_bp.route('/detection_records')
@login_required
@admin_required
def detection_records():
    page = request.args.get('page', 1, type=int)
    records = DetectionRecord.query.order_by(DetectionRecord.detect_time.desc()).paginate(page=page, per_page=10)
    return render_template('admin_detection_records.html', records=records)

@admin_bp.route('/statistics')
@login_required
@admin_required
def statistics():
    # Last 7 days detection counts
    end_date = datetime.now()
    start_date = end_date - timedelta(days=6)
    
    dates = []
    counts = []
    
    current = start_date
    while current <= end_date:
        d_str = current.strftime('%Y-%m-%d')
        dates.append(d_str)
        
        count = DetectionRecord.query.filter(
            db.func.date(DetectionRecord.detect_time) == current.date()
        ).count()
        counts.append(count)
        
        current += timedelta(days=1)
        
    return jsonify({
        'labels': dates,
        'data': counts
    })


def _parse_period(period_str: str, anchor_date: date | None = None):
    """根据 period(day/week/month/quarter/year) 计算统计的起止日期（含）。"""
    if anchor_date is None:
        anchor_date = date.today()

    if period_str == 'day':
        start = end = anchor_date
    elif period_str == 'week':
        # 一周：从周一到周日
        weekday = anchor_date.weekday()  # Monday=0
        start = anchor_date - timedelta(days=weekday)
        end = start + timedelta(days=6)
    elif period_str == 'month':
        start = anchor_date.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1, day=1)
        else:
            next_month = start.replace(month=start.month + 1, day=1)
        end = next_month - timedelta(days=1)
    elif period_str == 'quarter':
        # 按自然季度
        q = (anchor_date.month - 1) // 3  # 0,1,2,3
        start_month = q * 3 + 1
        start = anchor_date.replace(month=start_month, day=1)
        if start_month == 10:
            next_q_start = start.replace(year=start.year + 1, month=1, day=1)
        else:
            next_q_start = start.replace(month=start_month + 3, day=1)
        end = next_q_start - timedelta(days=1)
    elif period_str == 'year':
        start = anchor_date.replace(month=1, day=1)
        end = anchor_date.replace(month=12, day=31)
    else:
        # 默认按周
        weekday = anchor_date.weekday()
        start = anchor_date - timedelta(days=weekday)
        end = start + timedelta(days=6)

    return start, end


def _normalize_dish_name(raw):
    if not raw:
        return ''
    return str(raw).strip()


def _load_dish_map():
    """按名称（小写去空格）建立 Dish 映射，方便做分类。"""
    from app.models.food import Dish  # 延迟导入避免循环
    from sqlalchemy import func

    dishes = Dish.query.all()
    mapping = {}
    for d in dishes:
        key = (d.name or '').strip().lower()
        if not key:
            continue
        # 如果有多个重名，简单保留第一个
        mapping.setdefault(key, d)
    return mapping


def _classify_cooking(dish_obj, dish_name: str):
    """按烹饪方式粗略分到 蒸/煮/炒/炸/其他。"""
    text = ''
    if dish_obj and dish_obj.cooking_method:
        text = dish_obj.cooking_method
    else:
        text = dish_name or ''

    if '炸' in text:
        return '炸'
    if '炒' in text:
        return '炒'
    if '蒸' in text:
        return '蒸'
    if '煮' in text or '汤' in text:
        return '煮'
    return '其他'


def _classify_ingredient_type(dish_name: str):
    """按菜名关键字粗略分为 红肉/白肉/蔬菜/碳水/其他。"""
    name = dish_name or ''
    # 红肉
    if any(k in name for k in ['牛', '猪', '羊', '培根', '腊肉']):
        return '红肉'
    # 白肉（家禽+水产）
    if any(k in name for k in ['鸡', '鸭', '鹅', '鱼', '虾', '蟹']):
        return '白肉'
    # 碳水
    if any(k in name for k in ['饭', '米', '面', '粉', '饼', '馒头', '米线']):
        return '碳水'
    # 蔬菜
    if any(k in name for k in ['菜', '青', '生菜', '菠菜', '西兰花', '白菜', '芹菜', '豆角']):
        return '蔬菜'
    return '其他'


def _compute_dish_curve_series(dish_name: str, days: int = 30):
    """按天 & 早餐/午餐/晚餐统计某个菜品最近 N 天的销量次数。"""
    dish_name = _normalize_dish_name(dish_name)
    if not dish_name:
        return [], {1: [], 2: [], 3: []}

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    records = DietRecord.query.filter(
        db.func.date(DietRecord.create_time) >= start_date,
        db.func.date(DietRecord.create_time) <= end_date
    ).all()

    # 初始化时间轴
    dates = []
    cur = start_date
    while cur <= end_date:
        dates.append(cur.strftime('%Y-%m-%d'))
        cur += timedelta(days=1)

    series = {
        1: [0] * len(dates),  # 早餐
        2: [0] * len(dates),  # 午餐
        3: [0] * len(dates),  # 晚餐
    }

    index_map = {d: i for i, d in enumerate(dates)}

    for rec in records:
        day_str = rec.create_time.date().strftime('%Y-%m-%d')
        idx = index_map.get(day_str)
        if idx is None:
            continue
        try:
            dishes = json.loads(rec.dish_list or '[]')
        except Exception:
            dishes = []

        for d in dishes:
            if isinstance(d, dict):
                raw_name = d.get('dish_name') or d.get('name')
            else:
                raw_name = str(d)
            name = _normalize_dish_name(raw_name)
            if name == dish_name:
                series.setdefault(rec.meal_type, [0] * len(dates))
                series[rec.meal_type][idx] += 1

    return dates, series


@admin_bp.route('/dish_analytics')
@login_required
@admin_required
def dish_analytics():
    """菜品销量排行 + 分类占比 + 回头客 & 搭配分析。"""
    period = request.args.get('period', 'week')
    date_str = request.args.get('date', '')
    try:
        anchor = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except ValueError:
        anchor = date.today()

    start_date, end_date = _parse_period(period, anchor)

    # 查询此时间段内所有用餐记录
    records = DietRecord.query.filter(
        db.func.date(DietRecord.create_time) >= start_date,
        db.func.date(DietRecord.create_time) <= end_date
    ).all()

    dish_stats = {}  # name -> stats
    user_counts = {}  # name -> {user_id: count}
    pair_counts = {}  # (name1,name2) -> count

    dish_map = _load_dish_map()

    for rec in records:
        try:
            dishes = json.loads(rec.dish_list or '[]')
        except Exception:
            dishes = []

        # 用于搭配分析：一条记录里的去重菜品集合
        record_dish_names = set()

        for d in dishes:
            # d 可能是 dict，也可能是简单结构，尽量兼容
            if isinstance(d, dict):
                raw_name = d.get('dish_name') or d.get('name')
                weight = float(d.get('weight', 0) or 0)
            else:
                raw_name = str(d)
                weight = 0.0

            name = _normalize_dish_name(raw_name)
            if not name:
                continue

            key = name
            if key not in dish_stats:
                dish_stats[key] = {
                    'name': name,
                    'orders': 0,
                    'total_weight': 0.0,
                    'user_ids': set(),
                }
            dish_stats[key]['orders'] += 1
            dish_stats[key]['total_weight'] += weight
            dish_stats[key]['user_ids'].add(rec.user_id)

            # 回头客统计
            user_counts.setdefault(key, {})
            user_counts[key][rec.user_id] = user_counts[key].get(rec.user_id, 0) + 1

            record_dish_names.add(key)

        # 搭配分析：一条记录中的两两组合
        record_dish_names = sorted(record_dish_names)
        for i in range(len(record_dish_names)):
            for j in range(i + 1, len(record_dish_names)):
                pair = (record_dish_names[i], record_dish_names[j])
                pair_counts[pair] = pair_counts.get(pair, 0) + 1

    # 计算回头客数
    repeat_info = {}
    for name, per_user in user_counts.items():
        repeat_users = sum(1 for cnt in per_user.values() if cnt >= 3)
        repeat_info[name] = repeat_users

    # 将 set 转成人数
    for st in dish_stats.values():
        st['user_count'] = len(st['user_ids'])
        st.pop('user_ids', None)
        st['repeat_users'] = repeat_info.get(st['name'], 0)

    # 菜品销量排行
    ranked_dishes = sorted(
        dish_stats.values(),
        key=lambda x: x['orders'],
        reverse=True
    )

    # 经常一起被选择的菜品组合（Top 20）
    top_pairs = sorted(
        [{'dish1': a, 'dish2': b, 'count': c} for (a, b), c in pair_counts.items()],
        key=lambda x: x['count'],
        reverse=True
    )[:20]

    # Excel 导出
    if request.args.get('export') == '1':
        df = pd.DataFrame([
            {
                '菜品名称': d['name'],
                '销量次数': d['orders'],
                '总重量(g)': round(d['total_weight'], 1),
                '消费人数': d['user_count'],
                '回头客人数(>=3次)': d['repeat_users'],
            }
            for d in ranked_dishes
        ])
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='DishSales')
        output.seek(0)
        filename = f"dish_sales_{period}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx"
        return send_file(output, as_attachment=True, download_name=filename)

    return render_template(
        'admin_dish_analytics.html',
        period=period,
        start_date=start_date,
        end_date=end_date,
        ranked_dishes=ranked_dishes,
        top_pairs=top_pairs,
    )


@admin_bp.route('/dish_curve')
@login_required
@admin_required
def dish_curve():
    """兼容旧链接：重定向到新的菜品结构分析页面，并在该页面展示销量曲线。"""
    dish_name = _normalize_dish_name(request.args.get('dish', ''))
    days = request.args.get('days', 30, type=int)
    if not dish_name:
        flash('请选择要查看的菜品', 'warning')
        return redirect(url_for('admin.dish_structure'))
    return redirect(url_for('admin.dish_structure', dish=dish_name, days=days))


@admin_bp.route('/dish_structure')
@login_required
@admin_required
def dish_structure():
    """菜品结构占比（基于菜品库） + 单个菜品近30天销量曲线。"""
    from app.models.food import Dish

    # 1）基于菜品库的结构占比
    dishes = Dish.query.order_by(Dish.name).all()
    cooking_dist = {}   # 蒸/煮/炒/炸/其他 -> 菜品数量
    ing_type_dist = {}  # 红肉/白肉/蔬菜/碳水/其他 -> 菜品数量
    dish_names = []

    for d in dishes:
        name = (d.name or '').strip()
        if not name:
            continue
        dish_names.append(name)
        cook_cat = _classify_cooking(d, name)
        ing_cat = _classify_ingredient_type(name)
        cooking_dist[cook_cat] = cooking_dist.get(cook_cat, 0) + 1
        ing_type_dist[ing_cat] = ing_type_dist.get(ing_cat, 0) + 1

    cooking_labels = list(cooking_dist.keys())
    cooking_values = [cooking_dist[k] for k in cooking_labels]
    ing_labels = list(ing_type_dist.keys())
    ing_values = [ing_type_dist[k] for k in ing_labels]

    # 2）单个菜品销量曲线
    selected_dish = _normalize_dish_name(request.args.get('dish', ''))
    days = request.args.get('days', 30, type=int)
    if selected_dish:
        dates, series = _compute_dish_curve_series(selected_dish, days)
    else:
        dates, series = [], {1: [], 2: [], 3: []}

    return render_template(
        'admin_dish_structure.html',
        cooking_labels=cooking_labels,
        cooking_values=cooking_values,
        ing_labels=ing_labels,
        ing_values=ing_values,
        dish_names=dish_names,
        selected_dish=selected_dish,
        days=days,
        dates=dates,
        breakfast=series.get(1, [0] * len(dates)),
        lunch=series.get(2, [0] * len(dates)),
        dinner=series.get(3, [0] * len(dates)),
    )


@admin_bp.route('/feedback')
@login_required
@admin_required
def feedback():
    """用户反馈列表 + 投诉热点“词云”分析。"""
    feedbacks = Feedback.query.order_by(Feedback.created_at.desc()).all()

    # 简单基于领域关键字的“热点”统计（避免引入分词依赖）
    keywords = [
        '太咸', '太淡', '太油', '太辣', '太甜',
        '不新鲜', '变质', '凉了',
        '分量少', '分量大',
        '排队', '拥挤',
        '卫生', '环境', '服务',
        '难吃', '一般', '好吃',
        '选择少', '选择多',
        '价格贵', '性价比低',
    ]
    kw_counts = {k: 0 for k in keywords}
    for fb in feedbacks:
        text = fb.content or ''
        for k in keywords:
            if k in text:
                kw_counts[k] += 1

    # 只保留出现过的词
    used = [(k, c) for k, c in kw_counts.items() if c > 0]
    used.sort(key=lambda x: x[1], reverse=True)

    if used:
        max_c = used[0][1]
    else:
        max_c = 1

    word_cloud_data = [
        {
            'word': k,
            'count': c,
            # 简单映射到 14px ~ 32px 字号
            'font_size': 14 + int(18 * (c / max_c))
        }
        for k, c in used
    ]

    return render_template(
        'admin_feedback.html',
        feedbacks=feedbacks,
        word_cloud=word_cloud_data,
    )
