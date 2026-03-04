@echo off
cd /d C:\Users\phili\Documents\GitHub\copybot
git show f877932:bot/data/wallet_performance.db > bot/data/wallet_performance.db
echo Done. DB restored from commit f877932
pause
