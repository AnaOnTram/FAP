#!/bin/bash
# E-Paper Display Server — deploy & update script
# First install : sudo bash deploy.sh
# After git pull: sudo bash deploy.sh   (auto-detects update mode)
set -e

APP_DIR="/opt/epaper-server"
SERVICE="epaper-server"
NGINX_SITE="epaper"
SRC="$(cd "$(dirname "$0")" && pwd)"

# ── Detect mode ────────────────────────────────────────────────────
if [ -d "$APP_DIR/venv" ]; then
    MODE="update"
else
    MODE="install"
fi

echo "=== E-Paper Display Server — ${MODE} ==="

# ── Sync app files (both modes) ────────────────────────────────────
sync_files() {
    cp "$SRC/app.py"          "$APP_DIR/"
    cp "$SRC/requirements.txt" "$APP_DIR/"
    rm -rf "$APP_DIR/static"
    cp -r  "$SRC/static"      "$APP_DIR/"
    echo "[files] app.py, requirements.txt, static/ synced"
}

# ── Install Python dependencies (both modes) ───────────────────────
install_deps() {
    "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
    echo "[pip] dependencies up to date"
}

# ══════════════════════════════════════════════════════════════════════
if [ "$MODE" = "install" ]; then
# ══════════════════════════════════════════════════════════════════════

    # System packages
    apt-get update -qq
    apt-get install -y python3 python3-pip python3-venv nginx

    # App directory
    mkdir -p "$APP_DIR"
    sync_files
    mkdir -p "$APP_DIR/data"
    chown -R www-data:www-data "$APP_DIR/data"

    # Virtual environment
    python3 -m venv "$APP_DIR/venv"
    install_deps

    # Systemd service
    cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=E-Paper Display Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$SERVICE"
    echo "[systemd] service installed and enabled"

    # Nginx
    cat > "/etc/nginx/sites-available/$NGINX_SITE" <<'NGINX'
server {
    listen 80;
    server_name _;
    client_max_body_size 20M;
    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
NGINX
    ln -sf "/etc/nginx/sites-available/$NGINX_SITE" "/etc/nginx/sites-enabled/$NGINX_SITE"
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx
    echo "[nginx] configured"

# ══════════════════════════════════════════════════════════════════════
else  # update
# ══════════════════════════════════════════════════════════════════════

    sync_files
    install_deps

fi
# ══════════════════════════════════════════════════════════════════════

# Restart service (both modes)
systemctl restart "$SERVICE"
echo "[systemd] $SERVICE restarted"

echo ""
echo "=== ${MODE} complete ==="
if [ "$MODE" = "install" ]; then
    IP=$(hostname -I | awk '{print $1}')
    echo "Web GUI:  http://$IP/"
    echo "API:      http://$IP/api/status"
    echo ""
    echo "Tip: add HTTPS with  certbot --nginx -d yourdomain.com"
fi
echo "Logs: journalctl -u $SERVICE -f"
