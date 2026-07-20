# 交易开仓流程记录

一个可自定义字段的交易记录工具，支持截图上传、平仓记录、数据导出导入。

## 快速启动

```bash
pip install -r requirements.txt
python3 server.py
```

打开 http://localhost:5800

## 部署

见文档或 Dockerfile。

## 技术栈

- 后端：Python / Flask / SQLite
- 前端：静态 HTML / CSS / JS
- 存储：SQLite（数据）+ 文件系统（截图）
