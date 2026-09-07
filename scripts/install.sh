#!/usr/bin/env bash
# Bootstrap Control Center on a Debian/Ubuntu host.
# Installs Docker if needed, writes .env, starts Compose. Does not seed cards
# or touch unrelated containers.
set -euo pipefail

REPO_URL="${CC_REPO:-https://github.com/Maddad-FZE/control-center.git}"
DEFAULT_DIR="${CC_INSTALL_DIR:-/opt/control-center}"
COMPOSE_PROJECT="control-center"

die() {
  echo "install: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

if [[ "$(uname -s)" != "Linux" ]]; then
  die "Linux only (Debian or Ubuntu)."
fi

if [[ "$(id -u)" -ne 0 ]]; then
  die "Run as root (sudo ./scripts/install.sh, or curl … | sudo bash)."
fi

if [[ ! -f /etc/os-release ]]; then
  die "Missing /etc/os-release."
fi
# shellcheck source=/dev/null
. /etc/os-release
case "${ID:-}" in
  ubuntu | debian | raspbian) ;;
  *)
    die "Unsupported distro '${ID:-unknown}'. Use Debian or Ubuntu."
    ;;
esac

export DEBIAN_FRONTEND=noninteractive

apt_install() {
  apt-get update -y
  apt-get install -y --no-install-recommends "$@"
}

ensure_packages() {
  local missing=()
  local pkg
  for pkg in "$@"; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
      missing+=("$pkg")
    fi
  done
  if ((${#missing[@]})); then
    apt_install "${missing[@]}"
  fi
}

ensure_packages ca-certificates curl gnupg git openssl

lan_ip() {
  local ip=""
  ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{
    for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }
  }')"
  if [[ -z "$ip" ]]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  [[ -n "$ip" ]] || die "Could not detect a LAN IP. Set SERVICES_HOST and re-run."
  echo "$ip"
}

docker_ok() {
  need_cmd docker && docker info >/dev/null 2>&1
}

install_docker() {
  echo "install: installing Docker Engine…"
  ensure_packages apt-transport-https
  install -m 0755 -d /etc/apt/keyrings
  local docker_distro="$ID"
  if [[ "$ID" == "raspbian" ]]; then
    docker_distro="debian"
  fi
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL "https://download.docker.com/linux/${docker_distro}/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi
  local codename="${VERSION_CODENAME:-}"
  cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${docker_distro} ${codename} stable
EOF
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif need_cmd docker-compose; then
    docker-compose "$@"
  else
    die "Docker Compose is not available."
  fi
}

if ! docker_ok; then
  install_docker
  docker_ok || die "Docker installed but 'docker info' failed."
fi

if ! docker compose version >/dev/null 2>&1 && ! need_cmd docker-compose; then
  apt_install docker-compose-plugin
fi

HAVE_TREE=0
INSTALL_DIR="$DEFAULT_DIR"
SRC="${BASH_SOURCE[0]:-}"
if [[ -n "$SRC" && -f "$SRC" ]]; then
  SRC_DIR="$(cd "$(dirname "$SRC")" 2>/dev/null && pwd || true)"
  if [[ -n "$SRC_DIR" && -f "$SRC_DIR/../docker-compose.yml" && -f "$SRC_DIR/../manage.py" ]]; then
    INSTALL_DIR="$(cd "$SRC_DIR/.." && pwd)"
    HAVE_TREE=1
  fi
fi

if [[ "$HAVE_TREE" -eq 0 ]]; then
  if [[ -d "$INSTALL_DIR" ]]; then
    if [[ ! -f "$INSTALL_DIR/docker-compose.yml" || ! -f "$INSTALL_DIR/manage.py" ]]; then
      die "$INSTALL_DIR exists and is not a Control Center tree. Set CC_INSTALL_DIR or remove it."
    fi
  else
    echo "install: cloning $REPO_URL → $INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi
fi

cd "$INSTALL_DIR"

if [[ ! -f docker-compose.yml || ! -f .env.example ]]; then
  die "Control Center files missing in $INSTALL_DIR."
fi

mkdir -p data media

HOST_IP="$(lan_ip)"
CSRF_ORIGIN="http://${HOST_IP}"
if [[ ! -f .env ]]; then
  echo "install: writing .env for $HOST_IP"
  KEY="$(openssl rand -base64 48 | tr -d '\n/=+' | head -c 50)"
  cat >.env <<EOF
DJANGO_SETTINGS_MODULE=config.settings.prod
SECRET_KEY=${KEY}
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,${HOST_IP}
CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1,${CSRF_ORIGIN}
SESSION_COOKIE_DOMAIN=
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
HEALTH_CHECK_ENABLED=true
DOCKER_HOST=unix:///var/run/docker.sock
NTFY_URL=
NTFY_TOPIC=homelab-alerts
NTFY_USER=
NTFY_PASSWORD=
SITE_TITLE=Home Server Command Center
GITHUB_REPO=Maddad-FZE/control-center
UPDATE_CHECK_INTERVAL_HOURS=12
UPDATES_ALLOW_INSTALL=true
SERVICES_HOST=${HOST_IP}
EOF
  chmod 600 .env
else
  echo "install: keeping existing .env"
  if grep -q '^CSRF_TRUSTED_ORIGINS=' .env && ! grep -q "$CSRF_ORIGIN" .env; then
    sed -i "s|^CSRF_TRUSTED_ORIGINS=\\(.*\\)|CSRF_TRUSTED_ORIGINS=\\1,${CSRF_ORIGIN}|" .env
  fi
fi

echo "install: starting Control Center (this may take a few minutes)…"
compose -p "$COMPOSE_PROJECT" up -d --build

echo
echo "Control Center is starting."
echo "Open  http://${HOST_IP}/  and finish first-time setup."
echo "Files: ${INSTALL_DIR}"
echo "This installer does not seed dashboard cards or change other Docker apps."
