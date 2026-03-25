from flask import Blueprint, render_template, request, jsonify, current_app, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from datetime import datetime
from sqlalchemy import func
import json
import os
from ultralytics import YOLO
from app.models.record import Plate, DetectionRecord, DietRecord
from app.models.food import NutritionFacts, Dish, DishIngredient, Ingredient, Canteen
from app import db
from PIL import Image
import numpy as np

# 创建蓝图
meal_track_bp = Blueprint('meal_track', __name__, url_prefix='/meal')

# ====================== 用餐追踪首页 ======================


@meal_track_bp.route('/')
@meal_track_bp.route('/index')
@login_required
def index():
    """用餐追踪页面"""
    return render_template('meal_track.html')


# ====================== 菜品库页面 ======================
@meal_track_bp.route('/dish_library')
@login_required
def dish_library():
    """菜品库页面"""
    # 获取参数
    page = request.args.get('page', 1, type=int)
    per_page = 6
    cooking_method = request.args.get('cooking_method', '')
    search_query = request.args.get('q', '')

    # 构建查询：仅显示全局菜品 + 当前用户创建的个人菜品
    query = Dish.query.filter(Dish.visible_to_user(current_user.id))

    # 筛选：烹饪方式
    if cooking_method:
        query = query.filter(Dish.cooking_method == cooking_method)

    # 搜索：名称
    if search_query:
        query = query.filter(Dish.name.ilike(f'%{search_query}%'))

    # 排序并分页
    pagination = query.order_by(Dish.name).paginate(
        page=page, per_page=per_page, error_out=False)
    dishes = pagination.items

    # 获取所有唯一的烹饪方式用于筛选下拉框（仅可见菜品）
    cooking_methods = db.session.query(Dish.cooking_method).filter(
        Dish.visible_to_user(current_user.id),
        Dish.cooking_method.isnot(None), Dish.cooking_method != '').distinct().all()
    cooking_methods = [m[0] for m in cooking_methods]

    # 为每个菜品计算营养信息
    dish_info = []
    for dish in dishes:
        # 获取菜品的配料
        recipe_items = DishIngredient.query.filter_by(
            dish_id=dish.dish_id).all()

        # 计算每100g的营养成分
        nutrition_per_100g = {
            'calories': 0.0,
            'protein': 0.0,
            'fat': 0.0,
            'carb': 0.0
        }

        # 优先使用直接存储的营养信息
        if dish.calories_per_100g is not None or dish.protein_per_100g is not None or \
           dish.fat_per_100g is not None or dish.carb_per_100g is not None:
            # 使用直接存储的营养信息
            nutrition_per_100g['calories'] = dish.calories_per_100g or 0.0
            nutrition_per_100g['protein'] = dish.protein_per_100g or 0.0
            nutrition_per_100g['fat'] = dish.fat_per_100g or 0.0
            nutrition_per_100g['carb'] = dish.carb_per_100g or 0.0
        elif recipe_items:
            # 如果没有直接营养信息，使用食材配比计算
            # 计算配方总重量
            recipe_total_weight = sum(item.amount_g for item in recipe_items)

            if recipe_total_weight > 0:
                # 计算每100g的营养成分
                for item in recipe_items:
                    ingredient = Ingredient.query.get(item.ingredient_id)
                    nutrition = NutritionFacts.query.get(item.ingredient_id)

                    if ingredient and nutrition:
                        # 计算该配料在100g菜品中的重量
                        weight_in_100g = (
                            item.amount_g / recipe_total_weight) * 100

                        # 计算营养成分（按100g计）
                        nutrition_per_100g['calories'] += (
                            nutrition.energy_kcal / 100) * weight_in_100g
                        nutrition_per_100g['protein'] += (
                            nutrition.protein_g / 100) * weight_in_100g
                        nutrition_per_100g['fat'] += (
                            nutrition.fat_g / 100) * weight_in_100g
                        nutrition_per_100g['carb'] += (
                            nutrition.carb_g / 100) * weight_in_100g

                # 四舍五入保留1位小数
                nutrition_per_100g['calories'] = round(
                    nutrition_per_100g['calories'], 1)
                nutrition_per_100g['protein'] = round(
                    nutrition_per_100g['protein'], 1)
                nutrition_per_100g['fat'] = round(nutrition_per_100g['fat'], 1)
                nutrition_per_100g['carb'] = round(
                    nutrition_per_100g['carb'], 1)
        # 如果既没有直接营养信息也没有食材配比，保持默认值为0

        is_global = dish.created_by_user_id is None
        can_edit = (is_global and getattr(current_user, 'is_admin', 0) == 1) or (
            dish.created_by_user_id == current_user.id)
        dish_info.append({
            'dish': dish,
            'nutrition': nutrition_per_100g,
            'is_global': is_global,
            'can_edit': can_edit
        })

    return render_template('dish_library.html',
                           dishes=dish_info,
                           pagination=pagination,
                           cooking_methods=cooking_methods,
                           current_method=cooking_method,
                           search_query=search_query,
                           is_admin=(getattr(current_user, 'is_admin', 0) == 1))


# ====================== 菜品管理 (CRUD) ======================
@meal_track_bp.route('/dish/add', methods=['GET', 'POST'])
@login_required
def add_dish():
    """添加菜品"""
    if request.method == 'POST':
        name = request.form.get('name')
        cooking_method = request.form.get('cooking_method')
        description = request.form.get('description')
        canteen_id = request.form.get('canteen_id')
        unit_type = request.form.get('unit_type', 'portion')
        try:
            unit_weight = float(request.form.get('unit_weight', 100))
        except ValueError:
            unit_weight = 100.0

        # 获取直接输入的营养信息
        try:
            calories_per_100g = float(request.form.get(
                'calories_per_100g')) if request.form.get('calories_per_100g') else None
        except (ValueError, TypeError):
            calories_per_100g = None

        try:
            protein_per_100g = float(request.form.get(
                'protein_per_100g')) if request.form.get('protein_per_100g') else None
        except (ValueError, TypeError):
            protein_per_100g = None

        try:
            fat_per_100g = float(request.form.get('fat_per_100g')) if request.form.get(
                'fat_per_100g') else None
        except (ValueError, TypeError):
            fat_per_100g = None

        try:
            carb_per_100g = float(request.form.get('carb_per_100g')) if request.form.get(
                'carb_per_100g') else None
        except (ValueError, TypeError):
            carb_per_100g = None

        if not name:
            flash('菜品名称不能为空', 'danger')
            return redirect(url_for('meal_track.add_dish'))

        # Generate new Dish ID
        last_dish = Dish.query.order_by(Dish.dish_id.desc()).first()
        if last_dish and last_dish.dish_id and last_dish.dish_id.startswith('D'):
            try:
                last_num = int(last_dish.dish_id[1:])
                new_id = f'D{last_num + 1:06d}'
            except ValueError:
                new_id = f'D{int(datetime.now().timestamp())}'
        else:
            new_id = 'D000001'

        # 管理员添加为全局菜品(created_by_user_id=None)，普通用户添加为个人菜品(仅自己可见)
        created_by = None if (getattr(current_user, 'is_admin', 0) == 1) else current_user.id
        new_dish = Dish(
            dish_id=new_id,
            name=name,
            cooking_method=cooking_method,
            description=description,
            canteen_id=canteen_id if canteen_id else None,
            unit_type=unit_type,
            unit_weight=unit_weight,
            calories_per_100g=calories_per_100g,
            protein_per_100g=protein_per_100g,
            fat_per_100g=fat_per_100g,
            carb_per_100g=carb_per_100g,
            created_by_user_id=created_by
        )
        db.session.add(new_dish)
        db.session.commit()
        flash('菜品添加成功', 'success')
        return redirect(url_for('meal_track.dish_library'))

    canteens = Canteen.query.all()
    return render_template('dish_form.html', title='添加菜品', canteens=canteens)


def _can_edit_dish(dish):
    """仅管理员可编辑全局菜品，仅创建者可编辑个人菜品"""
    if dish.created_by_user_id is None:
        return getattr(current_user, 'is_admin', 0) == 1
    return dish.created_by_user_id == current_user.id


@meal_track_bp.route('/dish/edit/<string:dish_id>', methods=['GET', 'POST'])
@login_required
def edit_dish(dish_id):
    """编辑菜品"""
    dish = Dish.query.filter(Dish.visible_to_user(current_user.id)).filter(Dish.dish_id == dish_id).first()
    if not dish:
        abort(404)
    if not _can_edit_dish(dish):
        flash('没有权限修改该菜品。全局菜品仅管理员可编辑。', 'danger')
        return redirect(url_for('meal_track.dish_library'))
    if request.method == 'POST':
        dish.name = request.form.get('name')
        dish.cooking_method = request.form.get('cooking_method')
        dish.description = request.form.get('description')
        canteen_id = request.form.get('canteen_id')
        dish.canteen_id = canteen_id if canteen_id else None

        dish.unit_type = request.form.get('unit_type', 'portion')
        try:
            dish.unit_weight = float(request.form.get('unit_weight', 100))
        except ValueError:
            dish.unit_weight = 100.0

        # 更新直接输入的营养信息
        try:
            dish.calories_per_100g = float(request.form.get(
                'calories_per_100g')) if request.form.get('calories_per_100g') else None
        except (ValueError, TypeError):
            dish.calories_per_100g = None

        try:
            dish.protein_per_100g = float(request.form.get(
                'protein_per_100g')) if request.form.get('protein_per_100g') else None
        except (ValueError, TypeError):
            dish.protein_per_100g = None

        try:
            dish.fat_per_100g = float(request.form.get(
                'fat_per_100g')) if request.form.get('fat_per_100g') else None
        except (ValueError, TypeError):
            dish.fat_per_100g = None

        try:
            dish.carb_per_100g = float(request.form.get(
                'carb_per_100g')) if request.form.get('carb_per_100g') else None
        except (ValueError, TypeError):
            dish.carb_per_100g = None

        db.session.commit()
        flash('菜品更新成功', 'success')
        return redirect(url_for('meal_track.dish_library'))

    canteens = Canteen.query.all()
    return render_template('dish_form.html', title='编辑菜品', dish=dish, canteens=canteens)


@meal_track_bp.route('/dish/delete/<string:dish_id>', methods=['POST'])
@login_required
def delete_dish(dish_id):
    """删除菜品"""
    dish = Dish.query.filter(Dish.visible_to_user(current_user.id)).filter(Dish.dish_id == dish_id).first()
    if not dish:
        abort(404)
    if not _can_edit_dish(dish):
        flash('没有权限删除该菜品。全局菜品仅管理员可删除。', 'danger')
        return redirect(url_for('meal_track.dish_library'))

    # 删除相关的配料关联
    DishIngredient.query.filter_by(dish_id=dish_id).delete()

    db.session.delete(dish)
    db.session.commit()
    flash('菜品已删除', 'success')
    return redirect(url_for('meal_track.dish_library'))


# ====================== 删除用餐记录 ======================
@meal_track_bp.route('/delete_record/<int:record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    """删除用餐记录"""
    try:
        # 查找记录并验证用户权限
        record = DietRecord.query.filter_by(
            id=record_id, user_id=current_user.id).first()

        if not record:
            return jsonify({'status': 'error', 'message': '记录不存在或无权限删除'})

        # 删除记录
        db.session.delete(record)
        db.session.commit()

        return jsonify({'status': 'success', 'message': '记录删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'删除失败：{str(e)}'})


# ====================== 菜品识别接口 ======================
@meal_track_bp.route('/detect_dish', methods=['POST'])
@login_required
def detect_dish():
    if 'image' not in request.files:
        return jsonify({'status': 'error', 'message': '未上传图片'})

    file = request.files['image']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': '未选择文件'})

    upload_dir = os.path.join(current_app.static_folder, 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename.replace(' ', '_')}"
    save_path = os.path.join(upload_dir, filename)

    try:
        from PIL import Image
        img = Image.open(file)
        img = img.convert('RGB')
        img.save(save_path, format='JPEG')
    except Exception:
        file.save(save_path)

    image_url = f"/static/uploads/{filename}"

    model_path = os.path.join(current_app.static_folder, 'best.pt')
    if not os.path.exists(model_path):
        return jsonify({
            'status': 'error',
            'message': f'模型文件不存在：{model_path}',
            'image_url': image_url
        })

    try:
        model = YOLO(model_path)
        results = model(save_path, conf=0.3)

        # 生成带标注的图片
        res_plotted = results[0].plot()
        # 将BGR转换为RGB (ultralytics plot() 返回BGR numpy数组)
        res_plotted = res_plotted[..., ::-1]

        img_labeled = Image.fromarray(res_plotted)
        filename_labeled = f"labeled_{filename}"
        save_path_labeled = os.path.join(upload_dir, filename_labeled)
        img_labeled.save(save_path_labeled)
        labeled_image_url = f"/static/uploads/{filename_labeled}"

        detected_items = []

        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            conf = round(float(box.conf[0]), 2)
            class_name = model.names[cls_id]

            target_name = class_name.strip().lower()
            dish = Dish.query.filter(Dish.visible_to_user(current_user.id)).filter(
                func.lower(func.trim(Dish.name)) == target_name
            ).first()

            # Calculate nutrition per 100g if dish exists
            nutrition_per_100g = {
                'calories': 0.0,
                'protein': 0.0,
                'fat': 0.0,
                'carb': 0.0
            }

            if dish:
                # 优先使用直接存储的营养信息
                if dish.calories_per_100g is not None or dish.protein_per_100g is not None or \
                   dish.fat_per_100g is not None or dish.carb_per_100g is not None:
                    # 使用直接存储的营养信息
                    nutrition_per_100g['calories'] = dish.calories_per_100g or 0.0
                    nutrition_per_100g['protein'] = dish.protein_per_100g or 0.0
                    nutrition_per_100g['fat'] = dish.fat_per_100g or 0.0
                    nutrition_per_100g['carb'] = dish.carb_per_100g or 0.0
                else:
                    # 如果没有直接营养信息，使用食材配比计算
                    recipe_items = DishIngredient.query.filter_by(
                        dish_id=dish.dish_id).all()
                    recipe_total_weight = sum(
                        item.amount_g for item in recipe_items)

                    if recipe_total_weight > 0:
                        for item in recipe_items:
                            nutrition = NutritionFacts.query.get(
                                item.ingredient_id)
                            if nutrition:
                                weight_in_100g = (
                                    item.amount_g / recipe_total_weight) * 100
                                nutrition_per_100g['calories'] += (
                                    nutrition.energy_kcal / 100) * weight_in_100g
                                nutrition_per_100g['protein'] += (
                                    nutrition.protein_g / 100) * weight_in_100g
                                nutrition_per_100g['fat'] += (
                                    nutrition.fat_g / 100) * weight_in_100g
                                nutrition_per_100g['carb'] += (
                                    nutrition.carb_g / 100) * weight_in_100g

                        # Round values
                        for k in nutrition_per_100g:
                            nutrition_per_100g[k] = round(
                                nutrition_per_100g[k], 1)

            unit_type = dish.unit_type if dish else 'portion'
            unit_weight = dish.unit_weight if dish else 100.0

            # Determine default weight
            default_weight = unit_weight if unit_weight > 0 else 100.0

            # Determine unit label for display
            if unit_type == 'piece':
                unit_label = '个'
            elif unit_type == 'slice':
                unit_label = '片'
            elif unit_type == 'stick':
                unit_label = '根'
            else:
                unit_label = '克'

            detected_items.append({
                'dish_name': class_name,  # 恢复使用原始识别名称
                'confidence': conf,
                'weight': default_weight,
                'unit_type': unit_type,
                'unit_weight': unit_weight,
                'has_db_data': True if dish else False,
                'nutrition': nutrition_per_100g
            })

        # 按个/片/根计数的菜品：同一菜品识别出多个时合并为一项，数量累加
        piece_unit_types = ('piece', 'slice', 'stick')
        merged = {}  # key: (dish_name, unit_type), value: list of indices in detected_items
        for i, item in enumerate(detected_items):
            key = (item['dish_name'], item['unit_type'])
            if key not in merged:
                merged[key] = []
            merged[key].append(i)

        merged_items = []
        for (dish_name, unit_type), indices in merged.items():
            group = [detected_items[i] for i in indices]
            first = group[0]
            if unit_type in piece_unit_types:
                # 按个/片/根：数量 = 识别次数，重量 = unit_weight * 数量
                count = len(group)
                merged_items.append({
                    'dish_name': first['dish_name'],
                    'confidence': max(g['confidence'] for g in group),
                    'weight': first['unit_weight'] * count,
                    'unit_type': first['unit_type'],
                    'unit_weight': first['unit_weight'],
                    'has_db_data': first['has_db_data'],
                    'nutrition': first['nutrition']
                })
            else:
                # 按克/份：同一菜品重量累加
                total_weight = sum(g['weight'] for g in group)
                merged_items.append({
                    'dish_name': first['dish_name'],
                    'confidence': max(g['confidence'] for g in group),
                    'weight': total_weight,
                    'unit_type': first['unit_type'],
                    'unit_weight': first['unit_weight'],
                    'has_db_data': first['has_db_data'],
                    'nutrition': first['nutrition']
                })
        detected_items = merged_items

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'识别失败：{str(e)}',
            'image_url': image_url
        })

    new_record = DetectionRecord(
        user_id=current_user.id,
        detected_objects=json.dumps(detected_items),
        detect_time=datetime.now()
    )
    db.session.add(new_record)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'results': detected_items,
        'image_url': image_url,
        'labeled_image_url': labeled_image_url
    })


# ====================== 营养计算接口（核心修复） ======================
@meal_track_bp.route('/calculate_nutrition', methods=['POST'])
@login_required
def calculate_nutrition():
    data = request.get_json()
    dishes = data.get('dishes', [])

    total_nutrition = {
        'calories': 0.0,
        'protein': 0.0,
        'fat': 0.0,
        'carb': 0.0
    }
    dish_details = []

    for dish_input in dishes:
        dish_name = dish_input.get('dish_name', '')
        actual_weight = float(dish_input.get('weight', 0))

        single_dish = {
            'dish_name': dish_name,
            'calories': 0.0,
            'protein': 0.0,
            'fat': 0.0,
            'carb': 0.0,
            'weight': actual_weight
        }

        target_name = dish_name.strip().lower()
        dish = Dish.query.filter(Dish.visible_to_user(current_user.id)).filter(
            func.lower(func.trim(Dish.name)) == target_name
        ).first()

        if not dish:
            dish_details.append(single_dish)
            continue

        # 优先使用直接存储的营养信息
        if dish.calories_per_100g is not None or dish.protein_per_100g is not None or \
           dish.fat_per_100g is not None or dish.carb_per_100g is not None:
            # 使用直接存储的营养信息进行计算
            single_dish['calories'] = (
                dish.calories_per_100g or 0.0) * actual_weight / 100
            single_dish['protein'] = (
                dish.protein_per_100g or 0.0) * actual_weight / 100
            single_dish['fat'] = (
                dish.fat_per_100g or 0.0) * actual_weight / 100
            single_dish['carb'] = (
                dish.carb_per_100g or 0.0) * actual_weight / 100
        else:
            # 如果没有直接营养信息，使用食材配比计算
            recipe_items = DishIngredient.query.filter_by(
                dish_id=dish.dish_id).all()
            if not recipe_items:
                dish_details.append(single_dish)
                continue

            recipe_total_weight = sum(item.amount_g for item in recipe_items)
            if recipe_total_weight <= 0:
                dish_details.append(single_dish)
                continue

            scale_ratio = actual_weight / recipe_total_weight

            for item in recipe_items:
                ingredient = Ingredient.query.get(item.ingredient_id)
                nutrition = NutritionFacts.query.get(item.ingredient_id)

                if not ingredient or not nutrition:
                    continue

                actual_ing_weight = item.amount_g * scale_ratio
                factor = actual_ing_weight / 100

                single_dish['calories'] += nutrition.energy_kcal * factor
                single_dish['protein'] += nutrition.protein_g * factor
                single_dish['fat'] += nutrition.fat_g * factor
                single_dish['carb'] += nutrition.carb_g * factor

        # 四舍五入保留1位小数
        single_dish['calories'] = round(single_dish['calories'], 1)
        single_dish['protein'] = round(single_dish['protein'], 1)
        single_dish['fat'] = round(single_dish['fat'], 1)
        single_dish['carb'] = round(single_dish['carb'], 1)

        total_nutrition['calories'] += single_dish['calories']
        total_nutrition['protein'] += single_dish['protein']
        total_nutrition['fat'] += single_dish['fat']
        total_nutrition['carb'] += single_dish['carb']

        dish_details.append(single_dish)

    total_nutrition['calories'] = round(total_nutrition['calories'], 1)
    total_nutrition['protein'] = round(total_nutrition['protein'], 1)
    total_nutrition['fat'] = round(total_nutrition['fat'], 1)
    total_nutrition['carb'] = round(total_nutrition['carb'], 1)

    return jsonify({
        'status': 'success',
        'total': total_nutrition,
        'details': dish_details
    })


# ====================== 保存用餐记录接口 ======================
@meal_track_bp.route('/save_meal_record', methods=['POST'])
@login_required
def save_meal_record():
    data = request.get_json()
    meal_type = data.get('meal_type')
    dish_list = data.get('dish_list', [])
    totals = data.get('totals', {})
    date_str = data.get('date')

    create_time = datetime.now()
    if date_str:
        try:
            # Parse the date string (YYYY-MM-DD)
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            # Combine with current time to keep time precision
            create_time = datetime.combine(selected_date, datetime.now().time())
        except ValueError:
            pass  # Fallback to current time if format is invalid

    new_record = DietRecord(
        user_id=current_user.id,
        meal_type=meal_type,
        dish_list=json.dumps(dish_list),
        total_calorie=totals.get('calories', 0),
        total_protein=totals.get('protein', 0),
        total_fat=totals.get('fat', 0),
        total_carb=totals.get('carb', 0),
        create_time=create_time
    )

    db.session.add(new_record)
    db.session.commit()

    return jsonify({'status': 'success', 'message': '记录保存成功'})


# ====================== 菜品搜索接口 ======================
@meal_track_bp.route('/search_dishes', methods=['GET'])
@login_required
def search_dishes():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'status': 'success', 'results': []})

    # 仅搜索当前用户可见的菜品（全局 + 个人）
    dishes = Dish.query.filter(Dish.visible_to_user(current_user.id)).filter(
        Dish.name.ilike(f'%{query}%')).limit(20).all()

    results = []
    for dish in dishes:
        # Calculate nutrition per 100g
        nutrition_per_100g = {
            'calories': 0.0,
            'protein': 0.0,
            'fat': 0.0,
            'carb': 0.0
        }

        # 优先使用直接存储的营养信息
        if dish.calories_per_100g is not None or dish.protein_per_100g is not None or \
           dish.fat_per_100g is not None or dish.carb_per_100g is not None:
            # 使用直接存储的营养信息
            nutrition_per_100g['calories'] = dish.calories_per_100g or 0.0
            nutrition_per_100g['protein'] = dish.protein_per_100g or 0.0
            nutrition_per_100g['fat'] = dish.fat_per_100g or 0.0
            nutrition_per_100g['carb'] = dish.carb_per_100g or 0.0
        else:
            # 如果没有直接营养信息，使用食材配比计算
            recipe_items = DishIngredient.query.filter_by(
                dish_id=dish.dish_id).all()
            recipe_total_weight = sum(item.amount_g for item in recipe_items)

            if recipe_total_weight > 0:
                for item in recipe_items:
                    nutrition = NutritionFacts.query.get(item.ingredient_id)
                    if nutrition:
                        weight_in_100g = (
                            item.amount_g / recipe_total_weight) * 100
                        nutrition_per_100g['calories'] += (
                            nutrition.energy_kcal / 100) * weight_in_100g
                        nutrition_per_100g['protein'] += (
                            nutrition.protein_g / 100) * weight_in_100g
                        nutrition_per_100g['fat'] += (nutrition.fat_g /
                                                      100) * weight_in_100g
                        nutrition_per_100g['carb'] += (
                            nutrition.carb_g / 100) * weight_in_100g

            # Round values
            for k in nutrition_per_100g:
                nutrition_per_100g[k] = round(nutrition_per_100g[k], 1)

        results.append({
            'dish_id': dish.dish_id,
            'name': dish.name,
            'canteen_id': dish.canteen_id,
            'description': dish.description,
            'unit_type': dish.unit_type,
            'unit_weight': dish.unit_weight,
            'nutrition': nutrition_per_100g
        })

    return jsonify({'status': 'success', 'results': results})
