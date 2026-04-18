#!/bin/bash
# MOLOCH VPS Hardening Script
# Run as root on a fresh Ubuntu 22.04/24.04 VPS
# Sets up: nginx, SSL, UFW, fail2ban, reverse proxy for Ollama

set -e

echo ""
echo "  ███╗   ███╗ ██████╗ ██╗      ██████╗  ██████╗██╗  ██╗"
echo "  ████╗ ████║██╔═══██╗██║     ██╔═══██╗██╔════╝██║  ██║"
echo "  ██╔████╔██║██║   ██║██║     ██║   ██║██║     ███████║"
echo "  ██║╚██╔╝██║██║   ██║██║     ██║   ██║██║     ██╔══██║"
echo "  ██║ ╚═╝ ██║╚██████╔╝███████╗╚██████╔╝╚██████╗██║  ██║"
echo "  ╚═╝     ╚═╝ ╚═════╝ ╚══════╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝"
echo ""
echo "  VPS Hardening + nginx Setup"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Require domain argument ───────────────────────────────────
if [ -z "$1" ]; then
  echo "  Usage: ./vps-harden.sh your.domain.com [email@example.com]"
  echo ""
  echo "  Example: ./vps-harden.sh moloch.example.com admin@example.com"
  exit 1
fi

DOMAIN="$1"
EMAIL="${2:-admin@$DOMAIN}"
WEB_ROOT="/var/www/moloch"

echo "[1/7] Installing packages..."
apt update -qq
apt install -y nginx certbot python3-certbot-nginx ufw fail2ban curl

# ── 2. UFW ────────────────────────────────────────────────────
echo "[2/7] Configuring firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
echo "      UFW enabled"

# ── 3. fail2ban ───────────────────────────────────────────────
echo "[3/7] Configuring fail2ban..."
cat > /etc/fail2ban/jail.local << EOF
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
EOF

systemctl enable fail2ban
systemctl restart fail2ban
echo "      fail2ban configured"

# ── 4. Web root ───────────────────────────────────────────────
echo "[4/7] Creating web root..."
mkdir -p "$WEB_ROOT"

# Drop a placeholder if moloch.html isn't there yet
if [ ! -f "$WEB_ROOT/moloch.html" ]; then
  echo "<html><body><p>Deploy moloch.html here.</p></body></html>" > "$WEB_ROOT/index.html"
fi

# ── 5. nginx config ───────────────────────────────────────────
echo "[5/7] Writing nginx config..."
cat > /etc/nginx/sites-available/moloch << EOF
server {
    listen 80;
    server_name $DOMAIN;

    # Serve MOLOCH UI
    location / {
        root $WEB_ROOT;
        index moloch.html index.html;
        try_files \$uri \$uri/ /moloch.html;
    }

    # Proxy Ollama API — tunneled from local machine
    location /api/ {
        proxy_pass http://127.0.0.1:11434/api/;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_set_header Host \$host;
        chunked_transfer_encoding on;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
EOF

# Remove default site if present
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/moloch /etc/nginx/sites-enabled/moloch
nginx -t
systemctl reload nginx
echo "      nginx configured for $DOMAIN"

# ── 6. SSL ────────────────────────────────────────────────────
echo "[6/7] Obtaining SSL certificate..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
echo "      SSL certificate installed"

# ── 7. SSH hardening ──────────────────────────────────────────
echo "[7/7] Hardening SSH..."
sed -i 's/#PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload sshd
echo "      SSH: root login key-only, password auth disabled"

# ── Done ──────────────────────────────────────────────────────
echo ""
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  DONE"
echo ""
echo "  Domain:   https://$DOMAIN"
echo "  Web root: $WEB_ROOT"
echo ""
echo "  Next steps:"
echo "    1. Copy moloch.html to $WEB_ROOT/moloch.html"
echo "    2. Set up SSH reverse tunnel from your local machine"
echo "       (see README.md — Multi-Device Setup)"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status nginx"
echo "    sudo systemctl status fail2ban"
echo "    sudo fail2ban-client status sshd"
echo "    sudo ufw status verbose"
echo "    sudo nginx -t && sudo systemctl reload nginx"
echo ""
