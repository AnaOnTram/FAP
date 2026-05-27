#!/bin/bash
# E-Paper Display Server — Debian deploy script
# Run as root: sudo bash deploy.sh
set -e

APP_DIR="/opt/epaper-server"
SERVICE="epaper-server"
PORT=5000
NGINX_SITE="epaper"

echo "=== E-Paper Display Server Deployment ==="

# Install system packages
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv nginx

# Copy app files to /opt
mkdir -p "$APP_DIR"
cp -r "$(dirname "$0")"/{app.py,requirements.txt,static} "$APP_DIR/"
mkdir -p "$APP_DIR/data"
chown -R www-data:www-data "$APP_DIR/data"

# Python virtualenv + dependencies
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

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
systemctl restart "$SERVICE"
echo "Service started: $SERVICE"

# Nginx reverse proxy
cat > "/etc/nginx/sites-available/$NGINX_SITE" <<'EOF'
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
EOF

ln -sf "/etc/nginx/sites-available/$NGINX_SITE" "/etc/nginx/sites-enabled/$NGINX_SITE"
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "Nginx configured"

echo ""
echo "=== Deployment complete ==="
IP=$(hostname -I | awk '{print $1}')
echo "Web GUI:  http://$IP/"
echo "API:      http://$IP/api/status"
echo ""
echo "Optional: add HTTPS with  certbot --nginx -d yourdomain.com"
echo "Service logs:  journalctl -u $SERVICE -f"
