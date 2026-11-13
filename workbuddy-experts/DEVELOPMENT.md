# WorkBuddy流程分析专家

源码位于oa-workflow-expert，包含专家元数据、分析指引、头像和离线解析器。

## 验证与打包

在仓库根目录安装requirements-dev.txt后：

    python workbuddy-experts/build_expert.py --check
    python workbuddy-experts/build_expert.py

生成包在workbuddy-experts/dist，采用显式文件检查、固定ZIP时间及SHA-256清单。构建目录不进入Git。打包前保证专家内嵌解析器与tools/oa-workflow-analyzer中的通用源码一致，并更新包清单。

作者使用项目占位身份。自行发布时填写有权公开的维护者信息。不要将真实.wewf、业务报告、证据JSON、数据库连接和日志加入专家包。
