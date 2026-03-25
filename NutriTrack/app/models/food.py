from sqlalchemy import or_
from app import db


class Canteen(db.Model):
    __tablename__ = 'canteens'
    canteen_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)


class Dish(db.Model):
    __tablename__ = 'dishes'
    dish_id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    canteen_id = db.Column(db.Integer, db.ForeignKey('canteens.canteen_id'))
    cooking_method = db.Column(db.String(100))  # 烹饪方式
    description = db.Column(db.String(200), nullable=False, default='')
    # 计量单位类型: portion(份/克), piece(个), slice(片), stick(根)
    unit_type = db.Column(db.String(20), default='portion')
    unit_weight = db.Column(db.Float, default=100.0)  # 单位重量(克)
    # 直接存储营养信息（每100g）
    calories_per_100g = db.Column(db.Float)  # 卡路里(kcal)
    protein_per_100g = db.Column(db.Float)   # 蛋白质(g)
    fat_per_100g = db.Column(db.Float)       # 脂肪(g)
    carb_per_100g = db.Column(db.Float)      # 碳水化合物(g)
    # 创建者：NULL=全局菜品(仅管理员可添加/编辑)，非NULL=个人菜品(仅该用户可见、可编辑)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    @staticmethod
    def visible_to_user(user_id):
        """当前用户可见的菜品：全局菜品 + 自己创建的个人菜品"""
        return or_(Dish.created_by_user_id.is_(None), Dish.created_by_user_id == user_id)


class Ingredient(db.Model):
    __tablename__ = 'ingredients'
    ingredient_id = db.Column(db.Integer, primary_key=True)
    ingredient_name = db.Column(db.String(100), nullable=False)


class DishIngredient(db.Model):
    __tablename__ = 'dish_ingredients'
    dish_id = db.Column(db.String(50), db.ForeignKey(
        'dishes.dish_id'), primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey(
        'ingredients.ingredient_id'), primary_key=True)
    amount_g = db.Column(db.Float, nullable=False)


class NutritionFacts(db.Model):
    __tablename__ = 'nutrition_facts'
    ingredient_id = db.Column(db.Integer, db.ForeignKey(
        'ingredients.ingredient_id'), primary_key=True)
    energy_kcal = db.Column(db.Float, nullable=False)
    protein_g = db.Column(db.Float, nullable=False)
    fat_g = db.Column(db.Float, nullable=False)
    carb_g = db.Column(db.Float, nullable=False)
