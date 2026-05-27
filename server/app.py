#!/usr/bin/env python3
"""
E-Paper Display Server
Serves web GUI for image upload and REST API for ESP32 polling.
"""

from flask import Flask, request, jsonify, send_from_directory, send_file
from PIL import Image, ImageOps
import io
import os
import hashlib
import time
import json
import numpy as np

app = Flask(__name__, static_folder='static')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
IMAGE_PATH = os.path.join(DATA_DIR, 'current.bin')
META_PATH = os.path.join(DATA_DIR, 'meta.json')
PREVIEW_PATH = os.path.join(DATA_DIR, 'preview.png')

EPD_WIDTH = 400
EPD_HEIGHT = 300
IMAGE_BUFFER_SIZE = EPD_WIDTH * EPD_HEIGHT // 8  # 15000 bytes
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def load_meta():
    if os.path.exists(META_PATH):
        with open(META_PATH) as f:
            return json.load(f)
    return {'version': 'none', 'timestamp': 0, 'width': EPD_WIDTH, 'height': EPD_HEIGHT, 'size': 0}


def save_meta(meta):
    with open(META_PATH, 'w') as f:
        json.dump(meta, f, indent=2)


def apply_brightness_contrast(arr, brightness=0, contrast=0):
    """Matching the JS implementation exactly."""
    arr = arr.astype(float)
    arr += brightness * 2.55
    if contrast != 0:
        factor = (259 * (contrast + 255)) / (255 * (259 - contrast))
        arr = factor * (arr - 128) + 128
    return np.clip(arr, 0, 255).astype(np.uint8)


def process_image(image_data, crop=None, brightness=0, contrast=0):
    """Crop → resize → grayscale → brightness/contrast → dither → pack 1-bit."""
    img = Image.open(io.BytesIO(image_data))
    img = ImageOps.exif_transpose(img)
    img = img.convert('RGB')

    if crop and crop.get('w', 0) > 1 and crop.get('h', 0) > 1:
        x = max(0, int(crop['x']))
        y = max(0, int(crop['y']))
        w = int(crop['w'])
        h = int(crop['h'])
        img = img.crop((x, y, x + w, y + h))

    img = img.resize((EPD_WIDTH, EPD_HEIGHT), Image.LANCZOS)
    img = img.convert('L')

    arr = np.array(img, dtype=np.uint8)
    if brightness != 0 or contrast != 0:
        arr = apply_brightness_contrast(arr, brightness, contrast)

    # Floyd-Steinberg dithering via PIL
    dithered_img = Image.fromarray(arr, mode='L').convert('1')

    # Pack to 1-bit: MSB first, white=1 — matches ESP32 expectations
    bits = np.array(dithered_img, dtype=bool).reshape(EPD_HEIGHT, EPD_WIDTH)
    packed = np.packbits(bits, axis=1)  # shape (300, 50), MSB first
    packed_bytes = bytes(packed.tobytes())

    # 8-bit preview for display in the web UI
    preview_arr = (bits * 255).astype(np.uint8)
    preview_img = Image.fromarray(preview_arr, mode='L')

    return packed_bytes, preview_img


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/api/status')
def api_status():
    meta = load_meta()
    return jsonify({
        'status': 'online',
        'display': {'width': EPD_WIDTH, 'height': EPD_HEIGHT},
        'content': meta,
        'server_time': int(time.time()),
    })


@app.route('/api/content/version')
def api_content_version():
    meta = load_meta()
    return jsonify({'version': meta['version'], 'timestamp': meta['timestamp']})


@app.route('/api/content/image')
def api_content_image():
    if not os.path.exists(IMAGE_PATH):
        return jsonify({'error': 'No image available'}), 404
    return send_file(IMAGE_PATH, mimetype='application/octet-stream')


@app.route('/api/content/preview')
def api_content_preview():
    if not os.path.exists(PREVIEW_PATH):
        return jsonify({'error': 'No preview available'}), 404
    return send_file(PREVIEW_PATH, mimetype='image/png')


@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    image_data = file.read()
    if len(image_data) > MAX_FILE_SIZE:
        return jsonify({'error': 'File too large (max 10 MB)'}), 400

    crop = None
    try:
        cw = float(request.form.get('crop_w', 0))
        ch = float(request.form.get('crop_h', 0))
        if cw > 1 and ch > 1:
            crop = {
                'x': float(request.form.get('crop_x', 0)),
                'y': float(request.form.get('crop_y', 0)),
                'w': cw,
                'h': ch,
            }
    except (ValueError, TypeError):
        pass

    brightness = float(request.form.get('brightness', 0))
    contrast = float(request.form.get('contrast', 0))

    try:
        packed, preview_img = process_image(image_data, crop, brightness, contrast)
    except Exception as e:
        return jsonify({'error': f'Image processing failed: {e}'}), 500

    if len(packed) != IMAGE_BUFFER_SIZE:
        return jsonify({'error': f'Unexpected buffer size: {len(packed)}'}), 500

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(IMAGE_PATH, 'wb') as f:
        f.write(packed)
    preview_img.save(PREVIEW_PATH, 'PNG')

    version = hashlib.md5(packed).hexdigest()[:8]
    meta = {
        'version': version,
        'timestamp': int(time.time()),
        'width': EPD_WIDTH,
        'height': EPD_HEIGHT,
        'size': len(packed),
    }
    save_meta(meta)

    return jsonify({
        'status': 'success',
        'version': version,
        'size': len(packed),
        'message': 'Image uploaded. Display will refresh on next poll.',
    })


@app.route('/api/clear', methods=['POST'])
def api_clear():
    packed = bytes([0xFF] * IMAGE_BUFFER_SIZE)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(IMAGE_PATH, 'wb') as f:
        f.write(packed)

    for p in (PREVIEW_PATH,):
        if os.path.exists(p):
            os.remove(p)

    version = hashlib.md5(packed).hexdigest()[:8]
    meta = {
        'version': version,
        'timestamp': int(time.time()),
        'width': EPD_WIDTH,
        'height': EPD_HEIGHT,
        'size': len(packed),
    }
    save_meta(meta)

    return jsonify({'status': 'success', 'version': version, 'message': 'Display will clear on next poll.'})


if __name__ == '__main__':
    os.makedirs(DATA_DIR, exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=False)
