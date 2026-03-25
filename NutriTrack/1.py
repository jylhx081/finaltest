import os
from ultralytics import YOLO
import cv2

# ===================== 配置项（根据你的实际路径修改） =====================
MODEL_PATH = r"E:\deeplearning\pythonProject\NutriTrack\app\static\best.pt"  # best.pt的绝对路径
TEST_IMAGE_PATH = r"D:\Desktop\微信图片_20251204173414.jpg"  # 测试菜品图片路径
CONF_THRESHOLD = 0.3  # 置信度阈值（调低更容易看到结果）


# =========================================================================

def test_yolo_model():
    # 1. 检查模型文件是否存在
    if not os.path.exists(MODEL_PATH):
        print(f"❌ 模型文件不存在！路径：{MODEL_PATH}")
        return

    # 2. 加载模型
    try:
        model = YOLO(MODEL_PATH)
        print("✅ 模型加载成功！")
    except Exception as e:
        print(f"❌ 模型加载失败：{str(e)}")
        return

    # 3. 检查测试图片是否存在
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"❌ 测试图片不存在！路径：{TEST_IMAGE_PATH}")
        return

    # 4. 执行识别
    try:
        # 读取图片
        img = cv2.imread(TEST_IMAGE_PATH)
        # 确保图像数组是可写的，避免OpenCV只读错误
        if not img.flags.writeable:
            img = img.copy()
        # 模型预测
        results = model(img, conf=CONF_THRESHOLD)  # conf指定置信度阈值
        print(f"\n✅ 识别完成！共检测到 {len(results[0].boxes)} 个目标")

        # 5. 解析并打印识别结果
        if len(results[0].boxes) > 0:
            print("\n📌 识别结果：")
            for i, box in enumerate(results[0].boxes):
                cls_id = int(box.cls[0])  # 类别ID
                conf = round(float(box.conf[0]), 2)  # 置信度
                class_name = model.names[cls_id]  # 类别名称
                bbox = box.xyxy[0].tolist()  # 检测框坐标 [x1,y1,x2,y2]

                print(f"  目标{i + 1}：")
                print(f"    类别：{class_name}（ID：{cls_id}）")
                print(f"    置信度：{conf}")
                print(f"    检测框：{[round(x, 1) for x in bbox]}")
        else:
            print("\n⚠️  未识别到任何目标（可尝试调低置信度阈值）")

        # 6. 可视化结果（可选：弹出图片窗口显示检测框）
        results[0].save("test_result.jpg")  # 保存识别后的图片到当前目录
        print("\n✅ 识别结果已保存为：test_result.jpg（可打开查看检测框）")

    except Exception as e:
        print(f"❌ 识别过程出错：{str(e)}")


if __name__ == "__main__":
    print("===== 开始测试YOLO模型 =====")
    test_yolo_model()
    print("\n===== 测试结束 =====")
