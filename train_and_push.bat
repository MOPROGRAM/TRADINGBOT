@echo off
echo =======================================
echo  Starting AI Model Training Script
echo =======================================

echo.
echo [Step 1/3] Running Python training script...
python train_model.py

REM Check if the training script was successful
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Python training script failed. Aborting.
    pause
    exit /b %errorlevel%
)

echo.
echo [Step 2/3] Adding new model to Git...
git add trading_model.pkl model_info.json

echo.
echo [Step 3/3] Committing and pushing to GitHub...
git commit -m "feat: Update trained AI model"
git push

echo.
echo =======================================
echo  Process completed successfully!
echo =======================================
echo.
pause
