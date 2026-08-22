@echo off
rem BiliLearn MCP Server 启动器（供 MCP 客户端配置使用）
rem 用法：在 MCP 客户端中配置 command 为本文件路径即可
cd /d "%~dp0"
"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe" -m mcp_server
