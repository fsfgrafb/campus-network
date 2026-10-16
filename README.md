# campus-network

苏州工学院校园网客户端，支持自动认证、断线重连和开机恢复。

## 安装

从 [Releases](https://github.com/fsfgrafb/campus-network/releases/latest) 下载安装包，上传到服务器后执行：

```bash
tar -xzf campus-network_2.2.1_linux.tar.gz && sudo sh campus-network-2.2.1/install.sh
```

需要 Python ≥ 3.9 和 systemd。Debian 12/13 的 amd64/arm64 可离线自动补齐依赖；其他 Linux 需已有 curl 和 CA 证书。

## 使用

以下命令无需 sudo：

```bash
campus-network config   # 设置或更换账号
campus-network on       # 保持在线，断线自动重连
campus-network off      # 保持离线，注销会话
campus-network status   # 查看状态
```

首次使用先 `config`，再 `on`。账号只需配置一次，在线/离线模式重启后保留。

更换账号会先注销旧会话，配置后需重新执行 `on`。若显示“注销未确认”，请等待或稍后重试。

## 更新与卸载

更新：下载新版，重复安装，账号和配置保留。

卸载：先执行 `off`，确认状态为“离线”，再执行对应命令：

```bash
sudo apt remove campus-network   # Debian / Ubuntu
sudo rpm -e campus-network       # RPM 系统
```

通用脚本安装暂不提供一键卸载。

查看日志：

```bash
sudo journalctl -u campus-network -n 50 --no-pager
```
