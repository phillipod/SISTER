import cv2
import numpy as np

from skimage.metrics import structural_similarity as ssim

from ..utils.image import apply_mask, show_image


def multi_scale_match(
    name,
    region_color,
    template_color,
    scales=np.linspace(0.6, 0.7, 11),
    steps=None,
    threshold=0.7,
):
    best_val = -np.inf
    best_match = None
    best_loc = None
    best_scale = 1.0

    # print(f"Region shape: {region_color.shape}, template shape: {template_color.shape}, scales: {scales}, threshold: {threshold}")
    region_color = apply_mask(cv2.GaussianBlur(region_color, (3, 3), 0))
    template_color = apply_mask(cv2.GaussianBlur(template_color, (3, 3), 0))

    for scale in scales:
        resized_template = cv2.resize(
            template_color, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR
        )
        th, tw = resized_template.shape[:2]
        if th > region_color.shape[0] or tw > region_color.shape[1]:
            continue

        found_by_predicted_stepping = False

        if steps:
            x = steps[0]
            y = steps[1]

            roi = region_color[y : y + th, x : x + tw]

            # if name == "Nukara_Tribble.png":
            #     print(f"Pre-stepped match: {name} scale: {scale} Stepping: x: {x} y: {y} Dimensions: w: {tw} h: {th}")
            #     show_image([region_color, roi, resized_template])

            try:
                s = ssim(roi, resized_template, channel_axis=-1)
            except ValueError:
                continue

            # if name == "Nukara_Tribble.png":
            #     print(f"Score: {s}")

            if s > best_val:
                best_val = s
                best_loc = (x, y)
                best_match = (tw, th)
                best_scale = scale
                found_by_predicted_stepping = True
                # print("found by predicted stepping")

        if not found_by_predicted_stepping:
            step_limit = 3
            step_count_y = 0
            for y in range(0, region_color.shape[0] - th, 1):
                step_count_y += 1
                # if step_count_y > step_limit:
                #     break

                step_count_x = 0
                for x in range(0, region_color.shape[1] - tw, 1):
                    if steps and x == steps[0] and y == steps[1]:
                        continue
                    # step_count_y += 1
                    # if step_count_y > step_limit:
                    #     break

                    roi = region_color[y : y + th, x : x + tw]
                    try:
                        s = ssim(roi, resized_template, channel_axis=-1)
                    except ValueError:
                        continue

                    # if s > threshold:
                    #   if name == "Nukara_Tribble.png":
                    #       print(f"Stepped match: {name} scale: {scale} Stepping: x: {x} y: {y} Dimensions: w: {tw} h: {th} score: {s}")
                    #       show_image([region_color, roi, resized_template])
                    if s > best_val:
                        best_val = s
                        best_loc = (x, y)
                        best_match = (tw, th)
                        best_scale = scale
    if best_val >= threshold:
        return (
            best_loc,
            best_match,
            best_val,
            best_scale,
            "no-stepping" if found_by_predicted_stepping else "stepping",
        )
    else:
        return None
