#!/bin/bash
# ==============================================
# NemoFish — JeffSackmann Data Setup
# ==============================================
# Clones all 7 JeffSackmann tennis repos into 
# terminal/data/tennis/ for use by the trading 
# pipeline swarm.
#
# Total size: ~1.4 GB
# ==============================================

set -e

TENNIS_DIR="$(dirname "$0")/terminal/data/tennis"
mkdir -p "$TENNIS_DIR"

echo "🎾 NemoFish — Installing JeffSackmann Tennis Data"
echo "================================================="
echo ""

REPOS=(
    "tennis_atp"
    "tennis_wta"
    "tennis_slam_pointbypoint"
    "tennis_pointbypoint"
    "tennis_MatchChartingProject"
    "tennis_misc"
    "tennis_viz"
)

for repo in "${REPOS[@]}"; do
    if [ -d "$TENNIS_DIR/$repo" ]; then
        echo "✅ $repo (already exists)"
    else
        echo "📥 Cloning $repo..."
        git clone --depth 1 "https://github.com/JeffSackmann/$repo.git" "$TENNIS_DIR/$repo"
        echo "✅ $repo"
    fi
done

echo ""
echo "📊 Data Summary:"
du -sh "$TENNIS_DIR"/*
echo ""
echo "Total:"
du -sh "$TENNIS_DIR"
echo ""
echo "✅ All JeffSackmann data installed!"
echo "   Run: python3 terminal/feeds/sackmann_loader.py"
