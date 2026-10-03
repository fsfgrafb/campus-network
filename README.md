# campus-network

锐捷 ePortal 校园网认证 CLI。

## 命令

```bash
campus-network login [账号] [密码] [运营商编号]
campus-network logout
campus-network relogin
campus-network status
campus-network help
campus-network version
```

`login` 不带参数时使用上次保存的服务器账号；首次使用或配置版本变化后会交互式获取账号、密码和运营商。部分参数会交互式补齐剩余参数。

服务器共享配置：

- `/etc/campus-network/config`：公共配置和 `CONFIG_VERSION`
- `/etc/campus-network/account`：全服务器共用账号、密码、运营商
- `/var/lib/campus-network/userindex`：当前登录会话索引

所有用户都可以运行命令；安装/升级 Debian 包需要 root。

## 发布

```bash
git tag v1.2.3
git push origin v1.2.3
```

GitHub Actions 会自动构建 `campus-network_1.2.3_all.deb` 并创建 GitHub Release，程序 `version` 输出 `v1.2.3`。
