# campus-network

苏州工学院 Ruijie ePortal 校园网客户端，支持多账号、多源 IP 认证、主出口优先和账号避让。

## 安装

从 [Releases](https://github.com/fsfgrafb/campus-network/releases/latest) 下载安装包，上传到服务器后执行：

```bash
tar -xzf campus-network_3.0.1_linux.tar.gz && sudo sh campus-network-3.0.1/install.sh
```

需要 Python ≥ 3.9、systemd、curl、CA 证书和 iproute2（RPM 系统为 iproute）。Debian 12/13 的 amd64/arm64 通用离线包可补齐网络依赖。

## 使用

以下命令无需 sudo：

```bash
campus-network config   # 方向键管理 IP 池、账号池和主条目
campus-network on       # 保持在线，自动分配可用账号
campus-network off      # 保持离线，注销会话
campus-network status   # 查看状态
```

首次使用先 `config`，再 `on`。默认只有一个自动检测地址的主 IP；添加第一个账号后即可按单出口方式使用。只增加备用账号、无需增加 IP，就能在主账号冷却时接替主 IP。模式、分配、账号冷却跨重启保留。

菜单中 ↑↓ 选择，← 禁用，→ 启用，Enter 查看条目操作或新建，Esc 返回。新建项在各池列表底部。进入菜单不会断网。编辑已有条目前，先禁用并等待其会话释放；其他条目继续运行。支持 UTF-8 终端和 Linux Python 自带的 curses。

主 IP 优先使用主账号；不可用时使用其他账号。副 IP 优先使用其他账号，最后才使用空闲的主账号。没有空闲账号时，主 IP 可以收回副 IP 上已确认的本地会话。主账号冷却到期不会打断主 IP 上健康的备用会话。

禁用会立即停止该条目参与新分配、取消尚未提交的认证，并异步注销已知本地会话。已经提交的认证完成后也会被注销。注销暂不可达时仍保留占用并显示待释放；不会删除系统 IP、无线连接或路由。主 IP 收回已知本地账号时，先尝试注销，再在主 IP 登录同账号，利用认证系统的单点登录规则完成迁移。

## 冷却和掉线判定

默认避让 12 小时：仅在本程序持有会话且曾验证外网在线后，连续两次探测均出现认证页、同时 HTTPS 验证失败，且间隔至少 5 秒，才判断为“疑似被其他设备占用”。随后停止使用这个账号，清除本地旧会话标识，**不会通过重新登录或旧 token 注销来验证**，以免挤掉使用者。只配置一个账号时会等待冷却结束；有备用账号则自动接替。

HTTPS/DNS 失败、网线断开、缺少源地址或路由只触发等待或指数退避，不触发账号冷却。多个已知出口一起出现认证页时，暂停轮换，直到有其他出口再次证实外网正常；单出口仍按连续确认规则处理。这是保守判断，无法可靠区分所有校园网侧的会话超时与人工登录。

明确的密码、账号或运营商限制错误也会让该账号冷却；认证服务忙等普通错误按 2–120 秒指数退避重试。认证成功后必须通过外网探测才视为在线。登录请求超时或成功却缺少会话标识时，保留“结果未知”的账号占用，不自动抢登。需要管理员核查认证系统实际状态；`off/on` 和禁用再启用不会消除未知状态或冷却。

`/etc/campus-network/config.json` 可调整 `cooldown`（默认 43200 秒）和 `displacement_confirm`（默认 5 秒），修改后重启服务生效。冷却使用持久的绝对时间，请保持主机时钟正确。

3.0.1 将默认 QQ 探测替换为华为的 HTTPS 204 连通性地址，保留百度内容校验；任一 HTTPS 探测通过即可判定在线。升级启动时，仍使用旧版默认百度/QQ 组合的配置会自动迁移，并备份为 `/etc/campus-network/config.json.pre-3.0.1`；其他自定义探测组合保持不变。

## 多 IP 与无线出口

IP 条目填写**系统中已经存在**的源 IPv4、可选接口名、可选网络命名空间名。主 IP 可以留空沿用默认路由自动检测，副 IP 必须指定地址。认证与探测绑定源地址；显式 IP 必须属于指定接口，且源地址到公网检查地址 `1.1.1.1` 的路由必须从该接口发出，避免借主出口假装在线。认证页的 `wlanuserip` 为明文 IPv4 时会检查是否与实际出口一致；校园网返回不透明编码参数时，原样传给认证服务器，不把编码值误当成 IP。每个 IP 的网络请求独立执行，单个出口故障不会阻塞其他出口的认证和日常控制命令。

系统管理员负责配置无线关联、DHCP/静态地址、独立 MAC 或网络命名空间、源策略路由，以及下游流量的连接分流、SNAT、防火墙和 DNS。本程序 **3.x 提供多出口的账号认证与调度，不自动安装或修改这些网络配置，也不自动聚合带宽**。无线网卡支持多少个 STA、校园网允许哪些 IP/MAC 组合仍需现场验证。多个账号认证不等于普通单连接带宽叠加；配置连接分流后，多连接才可能受益。

特定服务器的 ARP 宣告、Docker 转发规则、透明 DNS、代理和限速配置属于部署环境，不写入通用客户端。换上无线网卡后，再按实际驱动能力和校园网地址分配配置出口。

## 状态与自动化

`campus-network status --json` 返回各 IP 的状态、预留账号 ID、启用状态及各账号的剩余冷却时间；不返回密码和会话 token。`ownership: verified` 表示本程序取得会话且已验证外网；已能上网但缺少所属会话时显示 `online-unowned` / `unconfirmed`，不会自动冒认或注销外部会话。池最多支持 16 个 IP、64 个账号；同一用户名不可重复录入。

`campus-network pool --json` 从标准输入读取一行 JSON，适合脚本调用；避免把真实密码写入命令参数或 shell 历史。示例中的数据均为虚构：

```json
{"command":"pool-add","kind":"ips","value":{"address":"192.0.2.10","interface":"wlan0","namespace":"campus2"}}
```

其他操作为 `pool-enable`（`kind`、`id`、布尔 `enabled`）、`pool-primary`（`kind`、`id`）、`pool-edit`（`kind`、`id`、`value`）。`kind` 为 `ips` 或 `accounts`；新增账号的 `value` 包含 `username`、`password`、`service`。账号密码修改保留原条目的冷却期限。

沿用旧版的本机共享控制模型：所有本机用户可控制模式、修改账号池；配置密码和会话仅由 root 保存。请只在信任本机用户的设备上使用。

## 更新与卸载

更新：下载新版，重复安装。首次启动自动把旧 `account.json`、在线/离线模式和待释放会话迁移到 `/var/lib/campus-network/pool.json` 及 `slots/`；不自动开启原本关闭的联网模式。旧文件保留，但迁移后以池文件为准，编辑旧 `account.json` 不会更新账号池。

持久文件使用原子替换、fsync 和 root 私有权限；账号先预留，再提交认证，释放完成后才解除预留。升级或回退前，停止服务并备份 `/etc/campus-network`、`/var/lib/campus-network`。3.x 状态不能直接交给 2.x 使用；回退前应执行 `off` 并确认释放，恢复升级前备份。

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
