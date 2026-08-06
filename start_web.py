# -*- coding: utf-8 -*-
"""启动Web服务（带热更新）"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.web.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 代码修改后自动重启
        reload_dirs=["src"]
    )
