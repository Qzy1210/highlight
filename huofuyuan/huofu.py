import cv2
import numpy as np


def detect_basketball_hoop(image_path, output_path="hoop_detection_result.png"):
    """
    使用霍夫圆检测识别图像中的篮球框，并生成带详细标注的结果图
    :param image_path: 输入图像文件路径
    :param output_path: 输出结果图像保存路径
    :return: 检测到的圆的列表 [(x, y, r), ...]
    """
    # 1. 读取图像
    img = cv2.imread(image_path)
    if img is None:
        print("错误：无法读取图像，请检查文件路径")
        return []

    # 创建结果图的副本，用于绘制标注（不修改原图）
    result_img = img.copy()
    img_height, img_width = result_img.shape[:2]

    # 2. 预处理：提升检测准确率
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 高斯模糊 + 中值滤波，双重降噪（针对篮框图像优化）
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)
    blurred = cv2.medianBlur(blurred, 5)

    # 3. 霍夫圆检测（针对篮框优化参数）
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=max(img_width, img_height) // 8,  # 根据图像尺寸自适应最小圆心距离
        param1=50,
        param2=30,
        minRadius=20,
        maxRadius=100
    )

    detected_circles = []
    # 4. 绘制醒目的检测标注
    if circles is not None:
        circles = np.uint16(np.around(circles))

        for idx, circle in enumerate(circles[0, :]):
            x, y, r = circle[0], circle[1], circle[2]
            detected_circles.append((x, y, r))

            # 绘制圆周：红色粗线，醒目
            cv2.circle(result_img, (x, y), r, (0, 0, 255), 4)
            # 绘制圆心：绿色实心点，突出中心
            cv2.circle(result_img, (x, y), 5, (0, 255, 0), -1)

            # 绘制半径线：蓝色虚线，直观显示半径
            cv2.line(result_img, (x, y), (x + r, y), (255, 0, 0), 2, cv2.LINE_AA)

            # 添加文字标注：显示序号、坐标、半径（白色字体带黑色描边，保证清晰）
            text = f"篮框{idx + 1}: ({x},{y}) 半径{r}"
            # 黑色描边
            cv2.putText(result_img, text, (x - r, y - r - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
            # 白色字体
            cv2.putText(result_img, text, (x - r, y - r - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    else:
        # 未检测到篮框时，在图像上添加提示文字
        cv2.putText(result_img, "未检测到篮框", (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

    # 5. 保存并显示结果图
    # 调整窗口大小（适配不同尺寸图像）
    cv2.namedWindow('Basketball Hoop Detection', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Basketball Hoop Detection', 800, 600)
    cv2.imshow('Basketball Hoop Detection', result_img)
    # 保存高分辨率结果图
    cv2.imwrite(output_path, result_img, [cv2.IMWRITE_JPEG_QUALITY, 95])

    print(f"\n结果图已保存至：{output_path}")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    return detected_circles


# ------------------- 测试代码 -------------------
if __name__ == "__main__":
    # 替换为你的篮框图像路径
    image_path = "/Users/quzhengyang/www/360.cn/Python/highLight/debug_fusion/validation_regions.jpg"
    # 自定义输出结果图路径（可选）
    output_path = "basketball_hoop_detection.png"

    print("开始检测篮框...")
    results = detect_basketball_hoop(image_path, output_path)

    # 控制台输出详细检测结果
    if results:
        print(f"\n✅ 检测到 {len(results)} 个疑似篮框：")
        for i, (x, y, r) in enumerate(results):
            print(f"  篮框{i + 1}: 圆心坐标({x}, {y})，半径{r} 像素")
    else:
        print("\n❌ 未检测到篮框，建议：")
        print("  1. 调整 minRadius/maxRadius 参数匹配实际篮框大小")
        print("  2. 降低 param2 参数（增加检测灵敏度）")
        print("  3. 确保图像中篮框为清晰的圆形，无严重遮挡")