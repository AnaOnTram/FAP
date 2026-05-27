#!/usr/bin/env python3
"""
E-Paper Display Server
Serves web GUI for image upload and REST API for ESP32 polling.
"""

from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect, url_for
from PIL import Image, ImageDraw, ImageFont, ImageOps
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
import io

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass  # pillow-heif not installed; HEIC uploads will fail gracefully
import os
import hashlib
import time
import json
import sqlite3
import secrets
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'))

DATA_DIR = os.path.join(BASE_DIR, 'data')
IMAGE_PATH = os.path.join(DATA_DIR, 'current.bin')
META_PATH = os.path.join(DATA_DIR, 'meta.json')
PREVIEW_PATH = os.path.join(DATA_DIR, 'preview.png')
DB_PATH = os.path.join(DATA_DIR, 'users.sqlite3')
SECRET_PATH = os.path.join(DATA_DIR, 'secret.key')

EPD_WIDTH = 400
EPD_HEIGHT = 300
IMAGE_BUFFER_SIZE = EPD_WIDTH * EPD_HEIGHT // 8  # 15000 bytes
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB after browser-side compression
USERNAME_MIN = 3
USERNAME_MAX = 32
PASSWORD_MIN = 8
DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD = 'admin'
REGISTRATION_PENDING = 'pending'
REGISTRATION_APPROVED = 'approved'


def load_secret_key():
    if os.environ.get('EPAPER_SECRET_KEY'):
        return os.environ['EPAPER_SECRET_KEY']
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(SECRET_PATH, 'w') as f:
        f.write(key)
    try:
        os.chmod(SECRET_PATH, 0o600)
    except OSError:
        pass
    return key


app.secret_key = load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('EPAPER_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes'),
)


@app.before_request
def gate_static_portal():
    user = current_user()
    if request.path == '/static/index.html' and not user:
        return redirect(url_for('login_page'))
    if request.path == '/static/index.html' and user and user['must_reset_password']:
        return redirect(url_for('reset_password_page'))
    if request.path in ('/static/admin.html', '/static/reset-password.html'):
        return redirect(url_for('index'))


def load_meta():
    if os.path.exists(META_PATH):
        with open(META_PATH) as f:
            return json.load(f)
    return {
        'version': 'none',
        'timestamp': 0,
        'width': EPD_WIDTH,
        'height': EPD_HEIGHT,
        'size': 0,
        'rendered_by': None,
        'source_bytes': 0,
        'compressed_bytes': 0,
    }


def save_meta(meta):
    with open(META_PATH, 'w') as f:
        json.dump(meta, f, indent=2)


def db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                must_reset_password INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cols = {row['name'] for row in conn.execute('PRAGMA table_info(users)').fetchall()}
        if 'role' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if 'status' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if 'must_reset_password' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN must_reset_password INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('registration_policy', ?)",
            (REGISTRATION_PENDING,),
        )
        admin = conn.execute(
            'SELECT id FROM users WHERE username = ? COLLATE NOCASE',
            (DEFAULT_ADMIN_USERNAME,),
        ).fetchone()
        if not admin:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at, role, status, must_reset_password)
                VALUES (?, ?, ?, 'admin', 'active', 1)
                """,
                (
                    DEFAULT_ADMIN_USERNAME,
                    generate_password_hash(DEFAULT_ADMIN_PASSWORD),
                    int(time.time()),
                ),
            )


def clean_username(value):
    username = (value or '').strip()
    if not (USERNAME_MIN <= len(username) <= USERNAME_MAX):
        raise ValueError(f'Username must be {USERNAME_MIN}-{USERNAME_MAX} characters.')
    if not all(ch.isalnum() or ch in ('_', '-', '.') for ch in username):
        raise ValueError('Username can only use letters, numbers, dots, hyphens, and underscores.')
    return username


def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    with db() as conn:
        row = conn.execute(
            'SELECT id, username, created_at, role, status, must_reset_password FROM users WHERE id = ?',
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_setting(key, default=None):
    with db() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


def set_setting(key, value):
    with db() as conn:
        conn.execute(
            'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (key, value),
        )


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({'error': 'Login required'}), 401
        if user['status'] != 'active':
            return jsonify({'error': 'Account is not active'}), 403
        if user['must_reset_password']:
            return jsonify({'error': 'Password reset required', 'must_reset_password': True}), 403
        return fn(*args, **kwargs)
    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({'error': 'Login required'}), 401
        if user['status'] != 'active':
            return jsonify({'error': 'Account is not active'}), 403
        if user['must_reset_password']:
            return jsonify({'error': 'Password reset required', 'must_reset_password': True}), 403
        if user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    return wrapper


def default_font(size=24):
    candidates = [
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/System/Library/Fonts/Supplemental/Songti.ttc',
        '/System/Library/Fonts/CJKSymbolsFallback.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf',
        '/usr/share/fonts/opentype/noto/NotoSansCJKtc-Regular.otf',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/arphic/uming.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width):
    lines = []
    for raw_line in (text or '').splitlines() or ['']:
        tokens = raw_line.split(' ')
        if not raw_line:
            lines.append('')
            continue

        line = ''
        for i, token in enumerate(tokens):
            if token == '' and i < len(tokens) - 1:
                token = ' '
            separator = ' ' if line and token != ' ' else ''
            trial = f'{line}{separator}{token}'
            if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
                line = trial
            elif draw.textbbox((0, 0), token, font=font)[2] > max_width:
                if line:
                    lines.append(line)
                    line = ''
                for char in token:
                    trial = f'{line}{char}'
                    if line and draw.textbbox((0, 0), trial, font=font)[2] > max_width:
                        lines.append(line)
                        line = char
                    else:
                        line = trial
            else:
                if line:
                    lines.append(line)
                line = token
        lines.append(line)
    return lines


def draw_centered_label(draw, text, y, font, fill=0, margin=10):
    bbox = draw.textbbox((0, 0), text, font=font)
    x = max(margin, (EPD_WIDTH - (bbox[2] - bbox[0])) // 2)
    draw.text((x, y), text, font=font, fill=fill)


def add_attribution(img, username):
    if not username:
        return img
    canvas = img.convert('RGB')
    draw = ImageDraw.Draw(canvas)
    label = f'Rendered by {username}'
    font = default_font(14)
    bbox = draw.textbbox((0, 0), label, font=font)
    pad_x, pad_y = 8, 5
    box_w = bbox[2] - bbox[0] + pad_x * 2
    box_h = bbox[3] - bbox[1] + pad_y * 2
    x = EPD_WIDTH - box_w - 8
    y = EPD_HEIGHT - box_h - 8
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=6, fill=(255, 255, 255), outline=(0, 0, 0), width=1)
    draw.text((x + pad_x, y + pad_y - bbox[1]), label, font=font, fill=(0, 0, 0))
    return canvas


def apply_brightness_contrast(arr, brightness=0, contrast=0):
    """Matching the JS implementation exactly."""
    arr = arr.astype(float)
    arr += brightness * 2.55
    if contrast != 0:
        factor = (259 * (contrast + 255)) / (255 * (259 - contrast))
        arr = factor * (arr - 128) + 128
    return np.clip(arr, 0, 255).astype(np.uint8)


def decode_image(image_data):
    try:
        img = Image.open(io.BytesIO(image_data))
        img.load()  # force decode so format errors surface here
    except Exception as e:
        magic = image_data[:12].hex() if image_data else 'empty'
        raise ValueError(
            f"Pillow cannot read image ({len(image_data)} bytes, magic: {magic}). "
            f"Supported formats: JPEG, PNG, WebP, BMP, GIF, HEIC. "
            f"Detail: {e}"
        )
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass  # exif_transpose is best-effort
    return img.convert('RGB')


def process_pil_image(img, crop=None, brightness=0, contrast=0, username=None):
    """Crop → resize → attribution → grayscale → brightness/contrast → dither → pack 1-bit."""
    if crop and crop.get('w', 0) > 1 and crop.get('h', 0) > 1:
        x = max(0, int(crop['x']))
        y = max(0, int(crop['y']))
        w = int(crop['w'])
        h = int(crop['h'])
        img = img.crop((x, y, x + w, y + h))

    img = img.resize((EPD_WIDTH, EPD_HEIGHT), Image.LANCZOS)
    img = add_attribution(img, username)
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


def process_image(image_data, crop=None, brightness=0, contrast=0, username=None):
    img = decode_image(image_data)
    return process_pil_image(img, crop, brightness, contrast, username=username)


def make_text_image(text, username, align='center', font_size=34):
    text = (text or '').strip()
    if not text:
        raise ValueError('Text cannot be empty.')
    if len(text) > 600:
        raise ValueError('Text is too long; keep it under 600 characters.')

    font_size = max(16, min(72, int(font_size or 34)))
    canvas = Image.new('RGB', (EPD_WIDTH, EPD_HEIGHT), 'white')
    draw = ImageDraw.Draw(canvas)
    font = default_font(font_size)
    small = default_font(13)
    margin = 26
    lines = wrap_text(draw, text, font, EPD_WIDTH - margin * 2)
    line_height = int(font_size * 1.22)
    total_h = line_height * len(lines)
    y = max(24, (EPD_HEIGHT - total_h) // 2)

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        if align == 'left':
            x = margin
        elif align == 'right':
            x = EPD_WIDTH - margin - line_w
        else:
            x = (EPD_WIDTH - line_w) // 2
        draw.text((x, y - bbox[1]), line, font=font, fill='black')
        y += line_height

    draw_centered_label(draw, f'Rendered by {username}', EPD_HEIGHT - 24, small, fill=0)
    return canvas


@app.route('/')
def index():
    user = current_user()
    if not user:
        return redirect(url_for('login_page'))
    if user['must_reset_password']:
        return redirect(url_for('reset_password_page'))
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/login')
def login_page():
    user = current_user()
    if user and user['must_reset_password']:
        return redirect(url_for('reset_password_page'))
    if user:
        return redirect(url_for('index'))
    return send_from_directory(app.static_folder, 'login.html')


@app.route('/reset-password')
def reset_password_page():
    user = current_user()
    if not user:
        return redirect(url_for('login_page'))
    if not user['must_reset_password']:
        return redirect(url_for('index'))
    return send_from_directory(app.static_folder, 'reset-password.html')


@app.route('/admin')
def admin_page():
    user = current_user()
    if not user:
        return redirect(url_for('login_page'))
    if user['must_reset_password']:
        return redirect(url_for('reset_password_page'))
    if user['role'] != 'admin':
        return redirect(url_for('index'))
    return send_from_directory(app.static_folder, 'admin.html')


@app.route('/api/status')
def api_status():
    meta = load_meta()
    return jsonify({
        'status': 'online',
        'display': {'width': EPD_WIDTH, 'height': EPD_HEIGHT},
        'content': meta,
        'user': current_user(),
        'server_time': int(time.time()),
    })


@app.route('/api/auth/register', methods=['POST'])
def api_register():
    payload = request.get_json(silent=True) or {}
    try:
        username = clean_username(payload.get('username'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    password = payload.get('password') or ''
    if len(password) < PASSWORD_MIN:
        return jsonify({'error': f'Password must be at least {PASSWORD_MIN} characters.'}), 400

    policy = get_setting('registration_policy', REGISTRATION_PENDING)
    status = 'active' if policy == REGISTRATION_APPROVED else 'pending'

    try:
        with db() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at, role, status, must_reset_password)
                VALUES (?, ?, ?, 'user', ?, 0)
                """,
                (username, generate_password_hash(password), int(time.time()), status),
            )
            if status == 'active':
                session['user_id'] = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({'error': 'That username is already registered.'}), 409

    if status == 'pending':
        return jsonify({
            'status': 'pending',
            'message': 'Registration submitted and awaiting admin approval.',
            'user': None,
        }), 202

    return jsonify({'status': 'success', 'user': current_user()})


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    with db() as conn:
        row = conn.execute(
            'SELECT id, username, password_hash, created_at, role, status, must_reset_password FROM users WHERE username = ? COLLATE NOCASE',
            (username,),
        ).fetchone()

    if not row or not check_password_hash(row['password_hash'], password):
        return jsonify({'error': 'Invalid username or password.'}), 401
    if row['status'] == 'pending':
        return jsonify({'error': 'Account is pending admin approval.'}), 403
    if row['status'] == 'rejected':
        return jsonify({'error': 'Account registration was rejected.'}), 403
    if row['status'] != 'active':
        return jsonify({'error': 'Account is not active.'}), 403

    session['user_id'] = row['id']
    return jsonify({'status': 'success', 'user': current_user()})


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'status': 'success'})


@app.route('/api/auth/me')
def api_me():
    return jsonify({'user': current_user()})


@app.route('/api/auth/reset-password', methods=['POST'])
def api_reset_password():
    user = current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401
    if user['status'] != 'active':
        return jsonify({'error': 'Account is not active'}), 403
    payload = request.get_json(silent=True) or {}
    password = payload.get('password') or ''
    if len(password) < PASSWORD_MIN:
        return jsonify({'error': f'Password must be at least {PASSWORD_MIN} characters.'}), 400
    if user['username'].lower() == DEFAULT_ADMIN_USERNAME and password == DEFAULT_ADMIN_PASSWORD:
        return jsonify({'error': 'Choose a password other than the default admin password.'}), 400
    with db() as conn:
        conn.execute(
            'UPDATE users SET password_hash = ?, must_reset_password = 0 WHERE id = ?',
            (generate_password_hash(password), user['id']),
        )
    return jsonify({'status': 'success', 'user': current_user()})


@app.route('/api/admin/overview')
@require_admin
def api_admin_overview():
    with db() as conn:
        rows = conn.execute(
            'SELECT id, username, created_at, role, status, must_reset_password FROM users ORDER BY role DESC, created_at ASC'
        ).fetchall()
    return jsonify({
        'users': [dict(row) for row in rows],
        'settings': {
            'registration_policy': get_setting('registration_policy', REGISTRATION_PENDING),
        },
        'current_user': current_user(),
    })


@app.route('/api/admin/users', methods=['POST'])
@require_admin
def api_admin_create_user():
    payload = request.get_json(silent=True) or {}
    try:
        username = clean_username(payload.get('username'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    password = payload.get('password') or ''
    role = payload.get('role') or 'user'
    if role not in ('user', 'admin'):
        return jsonify({'error': 'Role must be user or admin.'}), 400
    if len(password) < PASSWORD_MIN:
        return jsonify({'error': f'Password must be at least {PASSWORD_MIN} characters.'}), 400
    try:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at, role, status, must_reset_password)
                VALUES (?, ?, ?, ?, 'active', ?)
                """,
                (username, generate_password_hash(password), int(time.time()), role, 0),
            )
    except sqlite3.IntegrityError:
        return jsonify({'error': 'That username already exists.'}), 409
    return jsonify({'status': 'success'})


@app.route('/api/admin/users/<int:user_id>/status', methods=['POST'])
@require_admin
def api_admin_set_user_status(user_id):
    payload = request.get_json(silent=True) or {}
    status = payload.get('status')
    if status not in ('active', 'pending', 'rejected'):
        return jsonify({'error': 'Invalid status.'}), 400
    if user_id == current_user()['id'] and status != 'active':
        return jsonify({'error': 'You cannot deactivate your own admin account.'}), 400
    with db() as conn:
        row = conn.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
        if not row:
            return jsonify({'error': 'User not found.'}), 404
        conn.execute('UPDATE users SET status = ? WHERE id = ?', (status, user_id))
    return jsonify({'status': 'success'})


@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@require_admin
def api_admin_delete_user(user_id):
    if user_id == current_user()['id']:
        return jsonify({'error': 'You cannot delete your own admin account.'}), 400
    with db() as conn:
        row = conn.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
        if not row:
            return jsonify({'error': 'User not found.'}), 404
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    return jsonify({'status': 'success'})


@app.route('/api/admin/settings', methods=['POST'])
@require_admin
def api_admin_settings():
    payload = request.get_json(silent=True) or {}
    policy = payload.get('registration_policy')
    if policy not in (REGISTRATION_APPROVED, REGISTRATION_PENDING):
        return jsonify({'error': 'Registration policy must be approved or pending.'}), 400
    set_setting('registration_policy', policy)
    return jsonify({'status': 'success', 'settings': {'registration_policy': policy}})


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
@require_login
def api_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    file.stream.seek(0)
    image_data = file.read()
    source_bytes = int(request.form.get('source_bytes', len(image_data)) or len(image_data))
    if len(image_data) == 0:
        return jsonify({'error': 'Received empty file — upload may have failed'}), 400
    if len(image_data) > MAX_FILE_SIZE:
        return jsonify({'error': 'File too large after compression (max 2 MB)'}), 400

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
    user = current_user()

    try:
        packed, preview_img = process_image(image_data, crop, brightness, contrast, username=user['username'])
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
        'rendered_by': user['username'],
        'source_bytes': source_bytes,
        'compressed_bytes': len(image_data),
        'mode': 'image',
    }
    save_meta(meta)

    return jsonify({
        'status': 'success',
        'version': version,
        'size': len(packed),
        'rendered_by': user['username'],
        'source_bytes': source_bytes,
        'compressed_bytes': len(image_data),
        'message': 'Image uploaded. Display will refresh on next poll.',
    })


@app.route('/api/render-text', methods=['POST'])
@require_login
def api_render_text():
    payload = request.get_json(silent=True) or {}
    user = current_user()
    try:
        img = make_text_image(
            payload.get('text'),
            user['username'],
            align=payload.get('align', 'center'),
            font_size=payload.get('font_size', 34),
        )
        brightness = float(payload.get('brightness', 0))
        contrast = float(payload.get('contrast', 0))
        packed, preview_img = process_pil_image(img, brightness=brightness, contrast=contrast)
    except Exception as e:
        return jsonify({'error': f'Text rendering failed: {e}'}), 400

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
        'rendered_by': user['username'],
        'source_bytes': len((payload.get('text') or '').encode('utf-8')),
        'compressed_bytes': len((payload.get('text') or '').encode('utf-8')),
        'mode': 'text',
    }
    save_meta(meta)

    return jsonify({
        'status': 'success',
        'version': version,
        'size': len(packed),
        'rendered_by': user['username'],
        'message': 'Text rendered. Display will refresh on next poll.',
    })


@app.route('/api/clear', methods=['POST'])
@require_login
def api_clear():
    packed = bytes([0xFF] * IMAGE_BUFFER_SIZE)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(IMAGE_PATH, 'wb') as f:
        f.write(packed)

    for p in (PREVIEW_PATH,):
        if os.path.exists(p):
            os.remove(p)

    version = hashlib.md5(packed).hexdigest()[:8]
    user = current_user()
    meta = {
        'version': version,
        'timestamp': int(time.time()),
        'width': EPD_WIDTH,
        'height': EPD_HEIGHT,
        'size': len(packed),
        'rendered_by': user['username'],
        'source_bytes': 0,
        'compressed_bytes': 0,
        'mode': 'clear',
    }
    save_meta(meta)

    return jsonify({'status': 'success', 'version': version, 'message': 'Display will clear on next poll.'})


init_db()


if __name__ == '__main__':
    os.makedirs(DATA_DIR, exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=False)
