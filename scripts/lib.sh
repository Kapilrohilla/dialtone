# Shared helpers. Source from scripts: . "$(dirname "$0")/lib.sh"

# Loads .env as literal KEY=VALUE pairs (like docker compose does) instead of
# `source`, so values with spaces or shell characters are safe.
load_env() {
  local file=${1:-.env} line key value
  [[ -f "$file" ]] || { echo "$file not found; run scripts/init.sh" >&2; exit 1; }
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    key=${line%%=*}
    value=${line#*=}
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    export "$key=$value"
  done < "$file"
}
