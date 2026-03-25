import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from typing import List, Dict, Optional

def calculate_bmr(weight: float, height: float, age: int, gender: str) -> float:
    """
    Calculate BMR using Mifflin-St Jeor equation.
    weight: kg
    height: cm
    age: years
    gender: 'male' or 'female'
    """
    if gender.lower() in ['male', '男']:
        return (10 * weight) + (6.25 * height) - (5 * age) + 5
    else:
        return (10 * weight) + (6.25 * height) - (5 * age) - 161

def get_activity_multiplier(level: str) -> float:
    """
    Map activity level to TDEE multiplier.
    """
    levels = {
        'sedentary': 1.2, '久坐': 1.2, '久坐不动': 1.2,
        'light': 1.375, '轻度活动': 1.375,
        'moderate': 1.55, '中度活动': 1.55,
        'active': 1.725, '高度活动': 1.725,
        'very_active': 1.9, '极度活动': 1.9
    }
    # Default to sedentary if unknown
    for key, val in levels.items():
        if key in str(level).lower():
            return val
    return 1.2

def recommend_dishes(
    user_profile: Dict, 
    selected_dishes: List[Dict], 
    dish_pool: List[Dict], 
    rating_matrix: pd.DataFrame, 
    user_id: str, 
    k: int = 5, 
    top_n: int = 5
) -> List[Dict]:
    """
    Hybrid Intelligent Recommendation Module for Cafeteria.
    
    Args:
        user_profile: Dict with keys 'weight'(kg), 'height'(cm), 'age', 'gender', 'activity_level', 'health_goal'.
        selected_dishes: List of dicts with nutrient info and 'weight' (grams). 
                         Nutrients ('calories', 'protein', 'fat', 'carbs') should be per 100g or total. 
                         Assumption: Input nutrients are TOTAL for the selected weight.
        dish_pool: List of candidate dishes. Each dict must have 'id', 'name', 'calories', 'protein', 'fat', 'carbs'.
                   Assumption: Nutrients are per standard serving.
        rating_matrix: pd.DataFrame where index is user_id, columns are dish_ids, values are -1, 0, 1.
        user_id: ID of the target user.
        k: Number of neighbors for KNN.
        top_n: Number of recommendations to return.
        
    Returns:
        List of recommended dish dicts with 'recommendation_reason'.
    """
    
    # --- Strategy 1: Nutrient Gap-based Recommendation ---
    
    # 1.a Calculate BMR and TDEE
    weight = float(user_profile.get('weight', 60))
    height = float(user_profile.get('height', 170))
    age = int(user_profile.get('age', 25))
    gender = user_profile.get('gender', 'male')
    activity_level = user_profile.get('activity_level', 'sedentary')
    
    bmr = calculate_bmr(weight, height, age, gender)
    tdee = bmr * get_activity_multiplier(activity_level)
    
    # 1.b Adjust Goal
    goal = user_profile.get('health_goal', 'maintain')
    target_calories = tdee
    if 'fat_loss' in str(goal) or 'lose_weight' in str(goal) or '减脂' in str(goal):
        target_calories -= 500
    elif 'muscle' in str(goal) or 'gain' in str(goal) or '增肌' in str(goal):
        target_calories += 300
    
    # Set macro targets (Simplified approximation: 50% Carbs, 20% Protein, 30% Fat)
    # 1g Protein = 4kcal, 1g Carb = 4kcal, 1g Fat = 9kcal
    target_protein = (target_calories * 0.20) / 4
    target_fat = (target_calories * 0.30) / 9
    target_carbs = (target_calories * 0.50) / 4
    
    targets = {
        'calories': target_calories,
        'protein': target_protein,
        'fat': target_fat,
        'carbs': target_carbs
    }
    
    # 1.c Calculate Current Intake
    current_intake = {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0}
    for dish in selected_dishes:
        # Assuming dish nutrients are already calculated for the specific weight
        current_intake['calories'] += dish.get('calories', 0)
        current_intake['protein'] += dish.get('protein', 0)
        current_intake['fat'] += dish.get('fat', 0)
        current_intake['carbs'] += dish.get('carbs', 0)
        
    # 1.d Calculate Nutrient Gap
    gaps = {key: targets[key] - current_intake[key] for key in targets}
    
    # Identify main gap (ignoring calories for specific nutrient focus, but keeping it for overall limit)
    # We look for the largest relative gap in macros
    macro_gaps = {k: gaps[k] for k in ['protein', 'fat', 'carbs']}
    main_gap_nutrient = max(macro_gaps, key=macro_gaps.get) if any(v > 0 for v in macro_gaps.values()) else 'calories'
    
    # 1.e Filter Dish Pool
    nutrient_candidates = []
    for dish in dish_pool:
        # Check if dish helps fill the gap without excessive overflow
        # Logic: 
        # 1. Must contribute positive amount to main gap
        # 2. Must not cause other nutrients to exceed remaining allowance significantly (e.g. > 120% of gap)
        # Note: If gap is negative (already exceeded), we should avoid that nutrient.
        
        score = 0
        is_viable = True
        
        # Check limits
        for nutrient in ['calories', 'protein', 'fat', 'carbs']:
            dish_val = dish.get(nutrient, 0)
            gap_val = gaps[nutrient]
            
            # If we already exceeded this nutrient (gap < 0), adding more is bad
            if gap_val < 0 and dish_val > 5: # Tolerance of 5 units
                is_viable = False
                break
            
            # If adding this dish exceeds the gap by too much (e.g. +50% overage)
            if gap_val > 0 and dish_val > (gap_val * 1.5): 
                # Strictness can be adjusted. 
                pass 
        
        if not is_viable:
            continue
            
        # Calculate suitability score
        # Reward filling the main gap
        if gaps[main_gap_nutrient] > 0:
            score += (dish.get(main_gap_nutrient, 0) / gaps[main_gap_nutrient]) * 10
        
        # Penalize high density of nutrients that are nearly full
        for nutrient, gap_val in gaps.items():
            if gap_val <= 0:
                score -= dish.get(nutrient, 0) * 0.5
                
        if score > 0:
            dish['nutrient_score'] = score
            nutrient_candidates.append(dish)
    
    nutrient_candidates.sort(key=lambda x: x['nutrient_score'], reverse=True)
    nutrient_candidate_ids = {d['id'] for d in nutrient_candidates}
    
    # --- Strategy 2: Collaborative Filtering from Feedback ---
    
    cf_candidates = []
    
    # Ensure user is in matrix, if not, we can't do CF (cold start)
    if user_id in rating_matrix.index:
        # 2.a Cosine Similarity
        # Fill NaNs with 0 for sparse matrix calculation
        user_ratings = rating_matrix.loc[user_id].fillna(0).values.reshape(1, -1)
        other_users = rating_matrix.drop(index=user_id).fillna(0)
        
        if not other_users.empty:
            similarities = cosine_similarity(user_ratings, other_users.values)[0]
            
            # 2.b KNN
            # Get indices of top k similar users
            similar_user_indices = similarities.argsort()[::-1][:k]
            similar_users_scores = similarities[similar_user_indices]
            similar_users_ids = other_users.index[similar_user_indices]
            
            # 2.c Predict Ratings
            # We only care about dishes the user hasn't rated (or we want to recommend from the pool)
            # Prompt says "For each candidate dish NOT TRIED".
            # We assume 'not tried' means NaN in the rating matrix.
            
            pool_ids = [d['id'] for d in dish_pool]
            
            predictions = []
            for dish_id in pool_ids:
                # If user already rated this dish (and it's not NaN), skip it
                if dish_id in rating_matrix.columns:
                    user_rating = rating_matrix.loc[user_id, dish_id]
                    if not pd.isna(user_rating):
                        continue
                
                # If dish not in matrix columns, we can't do CF prediction based on neighbors (unless we treat as neutral)
                # But usually CF needs data. If it's a new dish, no one rated it.
                if dish_id not in rating_matrix.columns:
                    continue
                    
                # Get ratings for this dish from similar users
                neighbor_ratings = rating_matrix.loc[similar_users_ids, dish_id]
                
                # Weighted average
                weighted_sum = 0
                similarity_sum = 0
                
                for i, other_id in enumerate(similar_users_ids):
                    rating = neighbor_ratings.loc[other_id]
                    if not pd.isna(rating):
                        sim = similar_users_scores[i]
                        weighted_sum += sim * rating
                        similarity_sum += abs(sim)
                
                predicted_score = 0
                if similarity_sum > 0:
                    predicted_score = weighted_sum / similarity_sum
                
                # 2.d Filter >= 0
                if predicted_score >= 0:
                    predictions.append({
                        'id': dish_id,
                        'pred_score': predicted_score
                    })
            
            cf_candidates = sorted(predictions, key=lambda x: x['pred_score'], reverse=True)
    
    cf_candidate_ids = {d['id'] for d in cf_candidates}
    cf_score_map = {d['id']: d['pred_score'] for d in cf_candidates}
    
    # --- Strategy 3: Hybrid Strategy & Output ---
    
    # Intersection
    intersection_ids = nutrient_candidate_ids.intersection(cf_candidate_ids)
    
    final_recommendations = []
    
    # Helper to find dish object by ID
    dish_map = {d['id']: d for d in dish_pool}
    
    # Translate nutrient name to Chinese for display
    nutrient_map = {
        'calories': '热量',
        'protein': '蛋白质',
        'fat': '脂肪',
        'carbs': '碳水'
    }
    display_nutrient = nutrient_map.get(main_gap_nutrient, main_gap_nutrient)

    if intersection_ids:
        for did in intersection_ids:
            dish = dish_map[did]
            # Weighted Score: Normalize scores roughly to 0-1 range or just sum them
            # Nutrient score might be ~1-10, Pred score ~0-1
            # Let's weight them
            n_score = dish.get('nutrient_score', 0)
            p_score = cf_score_map.get(did, 0)
            
            final_score = (n_score * 0.7) + (p_score * 3.0) # Boost pred score weight
            
            final_recommendations.append({
                **dish,
                'final_score': final_score,
                'recommendation_reason': f"既符合{display_nutrient}补充需求，又基于相似口味推荐"
            })
    else:
        # Fallback: Nutrient first, then CF
        for dish in nutrient_candidates:
            if dish['id'] not in [r['id'] for r in final_recommendations]:
                dish['final_score'] = dish.get('nutrient_score', 0)
                dish['recommendation_reason'] = f"补充您的{display_nutrient}缺口"
                final_recommendations.append(dish)
        
        # Append CF high scores if we still need more
        for cand in cf_candidates:
            if cand['id'] not in [r['id'] for r in final_recommendations]:
                dish = dish_map.get(cand['id'])
                if dish:
                    dish_copy = dish.copy()
                    dish_copy['final_score'] = cand['pred_score']
                    dish_copy['recommendation_reason'] = "相似用户好评推荐"
                    final_recommendations.append(dish_copy)
    
    # Sort by final score
    final_recommendations.sort(key=lambda x: x.get('final_score', 0), reverse=True)
    
    # --- Strategy 4: Fallback (If no recommendations found) ---
    if not final_recommendations:
        # Fallback: Pick top N dishes with highest protein/calorie ratio (healthy high protein)
        # or simply low calorie balanced dishes.
        # Let's pick dishes with high protein density.
        fallback_candidates = []
        for dish in dish_pool:
            cal = dish.get('calories', 0)
            prot = dish.get('protein', 0)
            if cal > 50 and prot > 5: # Minimum threshold to be a "meal"
                ratio = prot / cal
                dish_copy = dish.copy()
                dish_copy['recommendation_reason'] = "健康高蛋白精选"
                dish_copy['ratio'] = ratio
                fallback_candidates.append(dish_copy)
        
        fallback_candidates.sort(key=lambda x: x['ratio'], reverse=True)
        final_recommendations = fallback_candidates[:top_n]
        
        # If still empty (e.g. no dishes meet criteria), just take random valid dishes
        if not final_recommendations:
             for dish in dish_pool[:top_n]:
                dish_copy = dish.copy()
                dish_copy['recommendation_reason'] = "今日菜品推荐"
                final_recommendations.append(dish_copy)

    # Return Top N
    return final_recommendations[:top_n]
