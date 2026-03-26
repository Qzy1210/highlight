import cv2
import numpy as np


def debug_hoop_detection(image_path, output_path="hoop_debug.png"):
    """
    带可视化调试的篮框检测：显示每一步处理结果，支持手动框选篮框区域
    """
    # 1. 读取图像
    img = cv2.imread(image_path)
    if img is None:
        print("❌ 无法读取图像！")
        return []
    result_img = img.copy()
    h, w = img.shape[:2]
    print(f"图像尺寸：{w}x{h}")

    # --------------------------
    # 步骤1：可视化预处理过程（帮你定位问题）
    # --------------------------
    # 灰度化
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 增强对比度（关键：提升篮框边缘的可见性）
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray_enhanced = clahe.apply(gray)
    # 降噪+边缘检测
    blurred = cv2.GaussianBlur(gray_enhanced, (3, 3), 0)
    edges = cv2.Canny(blurred, 10, 50)  # 极度宽松的边缘阈值

    # 显示预处理步骤（方便调试）
    cv2.namedWindow("1-原始图", cv2.WINDOW_NORMAL)
    cv2.namedWindow("2-增强对比度", cv2.WINDOW_NORMAL)
    cv2.namedWindow("3-边缘检测结果", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("1-原始图", 600, 400)
    cv2.resizeWindow("2-增强对比度", 600, 400)
    cv2.resizeWindow("3-边缘检测结果", 600, 400)
    cv2.imshow("1-原始图", img)
    cv2.imshow("2-增强对比度", gray_enhanced)
    cv2.imshow("3-边缘检测结果", edges)
    print("\n📌 请先查看边缘检测窗口：确认篮框位置有连续的边缘线")
    print("   按任意键继续检测...")
    cv2.waitKey(0)

    # --------------------------
    # 步骤2：手动框选篮框区域（核心：缩小检测范围）
    # --------------------------
    print("\n📌 请在原始图上拖动鼠标框选篮框所在的大致区域，按Enter确认")
    # 让用户手动框选区域
    roi = cv2.selectROI("1-原始图", img, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("1-原始图")
    cv2.destroyWindow("2-增强对比度")
    cv2.destroyWindow("3-边缘检测结果")

    # 提取手动框选的区域
    x1, y1, roi_w, roi_h = roi
    x2 = x1 + roi_w
    y2 = y1 + roi_h
    # 确保区域在图像范围内
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    roi_edges = edges[y1:y2, x1:x2]  # 只在框选区域内检测

    # --------------------------
    # 步骤3：在手动ROI内做霍夫圆检测（极度宽松）
    # --------------------------
    # 半径范围：根据框选区域大小动态计算
    roi_center_w = (x1 + x2) // 2
    roi_center_h = (y1 + y2) // 2
    min_r = max(5, int(roi_w * 0.1))
    max_r = int(roi_w * 0.5)
    print(f"\n📌 框选区域内的检测参数：半径范围 {min_r}-{max_r}px")

    circles = cv2.HoughCircles(
        roi_edges,
        cv2.HOUGH_GRADIENT,
        dp=1.0,
        minDist=min_r * 2,
        param1=30,
        param2=8,  # 最低阈值，保证检出
        minRadius=min_r,
        maxRadius=max_r
    )

    # --------------------------
    # 步骤4：绘制结果
    # --------------------------
    detected_hoops = []
    if circles is not None:
        circles = np.uint16(np.around(circles))
        for (cx, cy, r) in circles[0, :]:
            # 转换为原图坐标
            original_x = x1 + cx
            original_y = y1 + cy
            detected_hoops.append((original_x, original_y, r))

            # 绘制标注
            cv2.rectangle(result_img, (x1, y1), (x2, y2), (255, 0, 0), 2)  # 手动框选区域
            cv2.circle(result_img, (original_x, original_y), r, (0, 255, 0), 5)  # 篮框圆
            cv2.circle(result_img, (original_x, original_y), 6, (0, 0, 255), -1)  # 圆心
            cv2.putText(result_img, f"篮框 R={r}", (original_x - r, original_y - r - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    else:
        # 仍未检测到：直接在框选区域中心绘制参考圆
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        ref_r = (x2 - x1) // 4
        cv2.rectangle(result_img, (x1, y1), (x2, y2), (255, 0, 0), 2)
        cv2.circle(result_img, (center_x, center_y), ref_r, (0, 0, 255), 3)
        cv2.putText(result_img, "参考篮框位置", (center_x - ref_r, center_y - ref_r - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        print("\n❌ 框选区域内未检测到圆，已绘制参考位置")

    # 保存并显示最终结果
    cv2.imwrite(output_path, result_img, [cv2.IMWRITE_JPEG_QUALITY, 98])
    cv2.namedWindow("最终检测结果", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("最终检测结果", 1200, 800)
    cv2.imshow("最终检测结果", result_img)

    # 输出结果
    print(f"\n📸 结果图已保存：{output_path}")
    if detected_hoops:
        print(f"✅ 检测到 {len(detected_hoops)} 个篮框：")
        for i, (x, y, r) in enumerate(detected_hoops):
            print(f"  篮框{i + 1}：({x}, {y}) 半径{r}px")
    else:
        print("\n💡 最后方案：如果仍检测不到，说明篮框边缘太模糊，可直接用手动框选的中心坐标作为篮框位置")

    cv2.waitKey(0)
    cv2.destroyAllWindows()
    return detected_hoops


# 测试：替换为你的图片路径
if __name__ == "__main__":
    IMAGE_PATH = "/Users/quzhengyang/www/360.cn/Python/highLight/debug_fusion/validation_regions.jpg"  # 替换成你的图片路径
    debug_hoop_detection(IMAGE_PATH)