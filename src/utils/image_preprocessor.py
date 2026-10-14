"""
Image Preprocessing Pipeline.

Provides standardization for product catalog images:
1. Detects foreground content bounding box (trims redundant white margins).
2. Normalizes RGBA / paletted transparency onto a solid background.
3. Rescales and letterboxes content into a square canvas (default 250x250)
   with controlled margin padding, preserving aspect ratio without distortion.
"""

import os
from pathlib import Path
from typing import Tuple, Union, Optional
import numpy as np
from PIL import Image


def preprocess_product_image(
    input_path_or_img: Union[str, Path, Image.Image],
    target_size: Tuple[int, int] = (250, 250),
    padding_pct: float = 0.08,
    bg_threshold: int = 245,
    bg_color: Tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """
    Trims excessive white margins and letterboxes the product into target_size.

    Args:
        input_path_or_img: File path or PIL Image instance.
        target_size: Target (width, height) canvas. Default (250, 250).
        padding_pct: Relative border padding around the product bounding box.
        bg_threshold: RGB threshold above which pixels are considered background.
        bg_color: Background color for canvas and alpha blending.

    Returns:
        Processed PIL Image.
    """
    if isinstance(input_path_or_img, (str, Path)):
        img = Image.open(input_path_or_img)
    else:
        img = input_path_or_img

    # Alpha composition onto solid background if needed
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        canvas = Image.new('RGB', img.size, bg_color)
        canvas.paste(img, mask=img.convert('RGBA').split()[3])
        img_rgb = canvas
    else:
        img_rgb = img.convert('RGB')

    arr = np.array(img_rgb)
    # Detect foreground pixels
    foreground_mask = np.any(arr < bg_threshold, axis=2)

    if not np.any(foreground_mask):
        cropped = img_rgb
    else:
        y_indices, x_indices = np.where(foreground_mask)
        ymin, ymax = y_indices.min(), y_indices.max()
        xmin, xmax = x_indices.min(), x_indices.max()
        cropped = img_rgb.crop((xmin, ymin, xmax + 1, ymax + 1))

    cw, ch = cropped.size
    tw, th = target_size

    # Usable inner bounding box leaving padding
    avail_w = int(tw * (1.0 - 2 * padding_pct))
    avail_h = int(th * (1.0 - 2 * padding_pct))

    scale = min(avail_w / max(1, cw), avail_h / max(1, ch))
    nw = max(1, int(round(cw * scale)))
    nh = max(1, int(round(ch * scale)))

    resized = cropped.resize((nw, nh), resample=Image.Resampling.LANCZOS)

    final_img = Image.new('RGB', target_size, bg_color)
    ox = (tw - nw) // 2
    oy = (th - nh) // 2
    final_img.paste(resized, (ox, oy))

    return final_img


def process_image_file(
    input_file: Union[str, Path],
    output_file: Optional[Union[str, Path]] = None,
    target_size: Tuple[int, int] = (250, 250),
    padding_pct: float = 0.08,
    quality: int = 92
) -> None:
    """Processes and saves an image file to disk."""
    out_path = Path(output_file or input_file)
    processed = preprocess_product_image(
        input_file,
        target_size=target_size,
        padding_pct=padding_pct
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    processed.save(out_path, 'JPEG', quality=quality, optimize=True)

if __name__ == "__main__":
    for image in os.listdir("/home/airis/web-scrapper-vip-commerce/data"):
        process_image_file(os.path.join("/home/airis/web-scrapper-vip-commerce/data", image), os.path.join("/home/airis/web-scrapper-vip-commerce/data", image))