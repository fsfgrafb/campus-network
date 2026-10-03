# campus-network

苏州工学院 锐捷 ePortal 校园网认证 CLI。

## 命令

```bash
campus-network login [账号] [密码] [运营商编号]
campus-network logout
campus-network relogin
campus-network status
campus-network help
campus-network version
```

配置：

- `/etc/campus-network/config`：公共配置和 `CONFIG_VERSION`
- `/etc/campus-network/account`：账号、密码、运营商
- `/var/lib/campus-network/userindex`：当前登录会话索引

安装/升级 Debian 包需要 root。

