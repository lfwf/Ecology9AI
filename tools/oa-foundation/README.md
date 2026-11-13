# OA基础数据体系

维护配置目录、稳定读取方法、字段及关系、不可覆盖批次、变化比较、人工审核与证据。分类覆盖B01—B09，详见[架构说明](../../docs/architecture.md)。

所有真实连接、快照、人员目录、企业配置、审核结果和生成目录留在.local。示例和测试使用合成数据。

## 使用

在仓库根目录初始化[只读连接](../oa-readonly-db/README.md)，然后执行：

    python tools/oa-foundation/run.py --environment oa-local method
    python tools/oa-foundation/run.py --environment oa-local status
    python tools/oa-foundation/run.py --environment oa-local refresh --connection-directory tools/oa-readonly-db/.local
    python tools/oa-foundation/run.py --environment oa-local show --unreviewed

选择其他分类时使用全局参数：

    python tools/oa-foundation/run.py --environment oa-local --category B02 method
    python tools/oa-foundation/run.py --environment oa-local --category B02 refresh --connection-directory tools/oa-readonly-db/.local

按依赖顺序读取。各分类的registry/B0N.json登记固定查询、字段、限额和依赖，readers目录实现受控读取。每次适配新版本先核对实际schema；没有权限或对象不可见时保留缺口。

B08明确源码目录和B09明确代码参考分别按config中的example模板配置到本地连接目录。填写部署方有权读取的路径及文件，示例不含任何已部署环境信息。

    python tools/oa-foundation/overview.py --environment oa-local

overview离线核对已保存批次、依赖及哈希，输出基础数据总目录。show默认选择已审核接受批次，首次待审需显式指定--unreviewed；程序不会替代人工确认。

## 状态

成功采集、含义确认、人工审核分别管理。空结果、权限不足、读取失败和来源变更分别保存。失败不替换上次成功，原始证据不直接修改。

数据库只执行登记的固定读取；配置中的SQL、脚本、URL、接口及外部源保持为待分析文本。B09默认读取运行数据的结构，不读取实例及日志正文。

## 验证

    python -m unittest discover -s tools/oa-foundation/tests -q

测试不访问真实数据库；PowerShell读取器以合成记录验证参数、分页和边界。Windows符号链接权限不足时，相应测试会明确跳过。
