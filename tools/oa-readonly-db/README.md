# SQL Server只读连接

需要Windows及PowerShell。初始化时显式填写自己的服务器、数据库和只读账号，密码仅在本地隐藏输入：

    pwsh -NoProfile -File tools/oa-readonly-db/Test-OaDatabase.ps1 -Server db.example.invalid -Port 1433 -Database ecology -UserName oa_reader -SaveCredential

示例域名不会连接到实际数据库，使用时替换为你获准访问的目标。密码不通过命令参数传入。连接成功并完成所列权限检查后，本机DPAPI凭据和连接参数保存到工具.local目录，该目录不进入Git。

默认要求TLS并校验证书。需要信任指定服务器证书时，由部署方明确添加-TrustServerCertificate。

再次验证时重复传入同一目标，防止误用已保存的凭据：

    pwsh -NoProfile -File tools/oa-readonly-db/Test-OaDatabase.ps1 -Server db.example.invalid -Port 1433 -Database ecology -UserName oa_reader -UseSavedCredential

仅检查TCP连通：

    pwsh -NoProfile -File tools/oa-readonly-db/Test-OaDatabase.ps1 -Server db.example.invalid -UserName oa_reader -NetworkOnly

元数据盘点使用已保存的本地连接：

    pwsh -NoProfile -File tools/oa-readonly-db/Get-OaWorkflowSchema.ps1

可用-WorkflowId指定自己授权读取的单条流程定义，不读取业务实例。数据库身份、权限及目标检查结果保存在本地；读取成功不替代DBA对角色、对象及继承权限的审核。不执行写入探测。

DPAPI文件绑定用户和机器，迁移时重新初始化。相同Windows身份下运行的程序仍可解密，因此还需限制账号权限及本地文件访问。
