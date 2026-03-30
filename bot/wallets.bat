@echo off
echo.
echo  COPYBOT - Wallet Tools
echo ========================
echo  [1] import_wallets    - JSON in DB importieren
echo  [2] show_wallets      - Wallets anzeigen
echo  [3] find_wallets      - Neue Wallets suchen (Vorschau)
echo  [4] find_wallets apply - Neue Wallets hinzufuegen
echo  [5] wallet_analysis   - Observer / Analysis Mode starten
echo  [6] evaluate_wallets  - Candidates vs Actives vergleichen
echo  [q] Beenden
echo.
set /p choice="Wahl: "

if "%choice%"=="1" python import_wallets.py
if "%choice%"=="2" python main.py show_wallets
if "%choice%"=="3" python find_wallets.py
if "%choice%"=="4" python find_wallets.py --apply
if "%choice%"=="5" python main.py wallet_analysis
if "%choice%"=="6" python main.py evaluate_wallets
if "%choice%"=="q" exit
