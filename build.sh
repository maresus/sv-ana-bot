#!/bin/bash
# Build script - zgradi knowledge base če ne obstaja
set -e

echo "[BUILD] Gradim knowledge base iz sv-ana.si..."

if [ ! -f "knowledge.jsonl" ] || [ ! -s "knowledge.jsonl" ]; then
    echo "[BUILD] knowledge.jsonl ne obstaja, scrapiram sv-ana.si..."
    pip install requests beautifulsoup4 -q
    python3 scrape_sv_ana.py
    echo "[BUILD] Knowledge base zgrajen."
else
    echo "[BUILD] knowledge.jsonl že obstaja ($(wc -l < knowledge.jsonl) zapisov), preskačem scraping."
fi
