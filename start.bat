@echo off
chcp 65001 >nul
echo ================================
echo    智能体平台启动脚本
echo ================================
echo.

echo [步骤1] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] Python未安装，请先安装Python 3.8+
    pause
    exit /b 1
)
echo Python已安装

echo.
echo [步骤2] 检查Ollama服务...
curl -s http://localhost:11434/api/version >nul 2>&1
if errorlevel 1 (
    echo [警告] Ollama服务未启动
    echo 请先安装并启动Ollama: https://ollama.ai
    echo.
    echo 安装后运行: ollama pull deepseek-r1:7b
    pause
    exit /b 1
)
echo Ollama服务正常

echo.
echo [步骤3] 安装Python依赖...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo 依赖安装完成

echo.
echo [步骤4] 安装Playwright浏览器...
playwright install chromium
if errorlevel 1 (
    echo [警告] Playwright浏览器安装失败，可能已安装
)
echo Playwright安装完成

echo.
echo ================================
echo 启动智能体平台...
echo ================================
echo.
echo Web界面地址: http://127.0.0.1:8000
echo 按 Ctrl+C 停止服务器
echo.

python main.py

pause