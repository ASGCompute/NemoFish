#!/bin/bash
# NemoFish — Sackmann Data Auto-Refresh
# =======================================
# Pulls latest data from JeffSackmann GitHub repos.
# Schedule with: crontab -e → 0 6 * * * /path/to/refresh_sackmann.sh
#
# Repos updated:
#   - tennis_atp (matches + rankings)
#   - tennis_wta (matches + rankings)

set -e

DATA_DIR="$(cd "$(dirname "$0")/../data/tennis" && pwd)"

echo "🎾 NemoFish Sackmann Data Refresh"
echo "   $(date)"
echo "   Data dir: $DATA_DIR"
echo ""

REPOS=(
    "tennis_atp"
    "tennis_wta"
)

for repo in "${REPOS[@]}"; do
    REPO_DIR="$DATA_DIR/$repo"
    if [ -d "$REPO_DIR/.git" ]; then
        echo "📥 Updating $repo..."
        cd "$REPO_DIR"
        git pull --ff-only origin master 2>/dev/null || \
        git pull --ff-only origin main 2>/dev/null || \
        echo "   ⚠️  Pull failed for $repo (try manually)"
        echo "   ✅ $repo updated"
    else
        echo "📦 Cloning $repo..."
        git clone "https://github.com/JeffSackmann/$repo.git" "$REPO_DIR" 2>/dev/null || \
        echo "   ⚠️  Clone failed for $repo"
        echo "   ✅ $repo cloned"
    fi
    echo ""
done

# Check data freshness
echo "📊 Data freshness check:"
for repo in "${REPOS[@]}"; do
    LATEST=$(ls -1 "$DATA_DIR/$repo/"*_matches_202*.csv 2>/dev/null | sort | tail -1)
    if [ -n "$LATEST" ]; then
        MOD=$(stat -f "%Sm" -t "%Y-%m-%d" "$LATEST" 2>/dev/null || stat -c "%y" "$LATEST" 2>/dev/null | cut -d' ' -f1)
        echo "   $repo: latest file modified $MOD ($(basename $LATEST))"
    fi
done

echo ""
echo "✅ Refresh complete!"
