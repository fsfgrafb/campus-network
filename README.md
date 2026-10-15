# campus-network

苏州工学院锐捷 ePortal 校园网持续联网服务。Python 3 标准库管理状态，curl 执行校园网认证，systemd 负责开机启动、崩溃重启和卡死恢复。没有 pip 依赖。

## 安装：Debian 离线服务器

先在服务器确认系统版本和架构：

```bash
. /etc/os-release; echo "Debian $VERSION_ID"; dpkg --print-architecture
```

从 [Releases](https://github.com/fsfgrafb/campus-network/releases/latest) 下载匹配的完整离线包。例如 Debian 12、amd64 对应 `campus-network_2.0.1_debian12_amd64_offline.tar.gz`。提供 Debian 12 / 13 × amd64 / arm64 四种组合，内含 Python、curl、systemd、HTTPS 所需的 CA 根证书及其发行版依赖。

将压缩包传到服务器任意目录，在该目录执行一行：

```bash
tar -xzf campus-network_2.0.1_debian12_amd64_offline.tar.gz && sudo sh campus-network_2.0.1_debian12_amd64_offline/install.sh
```

安装器校验系统版本、CPU 架构和包校验和，建立临时本地 APT 仓库，再使用 `--no-download` 安装；整个过程无需外网。已满足要求的系统依赖会保留。仅安装需要 root；日常命令均无需 sudo。没有 sudo 的服务器可切换为 root 执行同一安装命令。

安装后默认**不联网**，不会主动占用校园网账号。首次启用：

```bash
campus-network on
```

按提示输入账号、密码、运营商，之后只需执行 `on`。密码不会回显，不需要写进命令行或 shell 历史。

### 其他安装包

| 文件 | 用途 |
| --- | --- |
| `campus-network_2.0.1_all.deb` | 已有依赖的 Debian / Ubuntu；不区分 CPU 架构 |
| `campus-network-2.0.1-1.noarch.rpm` | 已有依赖的 RPM 系 Linux；不区分 CPU 架构 |
| `campus-network_2.0.1_linux-any.tar.gz` | 其他使用 systemd 的 Linux；内含通用安装脚本 |
| `*_debian12_*_offline.tar.gz` / `*_debian13_*_offline.tar.gz` | 指定发行版和 CPU 的完整离线依赖包 |
| `SHA256SUMS` | 所有发布文件的 SHA-256 校验和 |

轻量包仅依赖 **Python ≥ 3.9、curl、systemd、ca-certificates**。它们是解释执行程序，没有必要为每种 CPU 重复打包；amd64、arm64 及发行版提供上述依赖的其他架构使用同一份程序。不支持 Windows、macOS、OpenWrt 或没有 systemd 的容器运行环境。

依赖已安装时，Debian 一行离线安装：

```bash
sudo dpkg -i ./campus-network_2.0.1_all.deb
```

RPM：`sudo rpm -Uvh ./campus-network-2.0.1-1.noarch.rpm`。通用包：解压后执行 `sudo sh ./install.sh`。HTTPS 外网探测必须有有效的 CA 根证书。通用安装器会检查依赖和证书，不会自动联网下载，也不会覆盖已有配置；已由 dpkg / RPM 管理的安装请继续使用对应包升级。

## 三条命令

```bash
campus-network on       # 持久化开启持续联网，首次使用时交互配置账号
campus-network off      # 先持久化禁止登录，再尝试释放已有会话
campus-network status   # 查看目标模式、实际状态、原因、时间和下次尝试
```

所有能登录服务器的本机用户都可以使用这三条命令，无需加入用户组，也无需 sudo。它们通过 Unix socket 控制唯一的服务进程；账号文件仍仅 root 可读。这个权限模型适用于本机用户均为可信内部人员的服务器。

```bash
watch -c -n 1 campus-network status # 实时查看；直接运行 status 时终端状态带颜色
campus-network status --json      # 便于脚本读取；成功退出码不代表外网在线，应检查 state
campus-network --version
campus-network --help
```

`NO_COLOR=1 campus-network status` 关闭颜色；重定向输出时自动关闭颜色。


## 状态与恢复

目标模式和实际联网状态独立显示：

- **on**：重启后继续保持联网。拔插网线、网络地址变化、认证失效时持续检测并尝试恢复。
- **off**：重启后仍禁止发起任何新登录。已发送的认证若随后成功，会立即安排下线；无网时保留待释放会话，恢复后继续下线。

`off` 返回表示“不再登录”的意愿已经保存，不代表认证服务器已经确认账号释放。状态中的“会话待释放”会一直保留到明确下线成功或确认会话失效。断电、拔网线期间无法向服务器发送下线请求，远端释放时间也受校园网会话超时影响。

| 实际状态 | 含义 |
| --- | --- |
| `online` | 外网探测通过 |
| `waiting-link` | 等待网卡 / 网线恢复 |
| `waiting-network` | 等待地址、路由或校园网门户恢复 |
| `checking` | 正在检查外网和门户 |
| `authenticating` | 正在认证 |
| `retrying` | 本轮失败，退避后继续尝试 |
| `releasing` | 禁止新登录，正在释放已有会话 |
| `release-unconfirmed` | 认证响应丢失且没有会话索引；已禁止新登录，但无法确认远端释放 |
| `idle` | 不联网，没有待释放会话 |
| `config-error` | 配置缺失或不正确 |

服务每秒检查本地网络变化，在线时约每 3 秒检查外网；任一有效外网探测通过即可判定在线。只有确认进入认证门户才登录，不会因为某个站点暂时不可达就先下线。网卡、DHCP 和路由仍由 Debian 原有网络管理器负责。

认证失败使用有上限的指数退避：第 n 次失败（从 0 计数）的上限为 `min(2 × 2ⁿ, 120)` 秒，从该上限的 1/2 到上限之间随机选择等待时间。持续故障时每轮等待 60–120 秒，等待期间仍响应命令并检查本地链路。链路、地址或路由变化后加 0–3 秒随机扰动重新检测；健康探测间隔也有随机扰动，避免大量设备同时请求认证服务器。反复执行 `on` 不会绕过已有失败退避。

所有 HTTP 请求都有超时；恢复速度取决于交换机、DHCP 和认证服务器。systemd 在进程退出后约 1 秒重启；主循环 30 秒没有 watchdog 心跳时会重启服务。服务启动、升级和进程重启不主动下线，避免破坏可用会话。

## 配置与数据

| 路径 | 内容 |
| --- | --- |
| `/etc/campus-network/config.json` | 门户、网卡、探测和重试参数 |
| `/etc/campus-network/account.json` | 账号、密码、运营商；权限 0600 |
| `/var/lib/campus-network/state.json` | 跨重启保存的模式和待处理会话；目录 0700 |
| `/run/campus-network/control.sock` | 本机控制接口；socket 0666，目录由 root 持有 |

如使用自定义 CA，通用安装器可通过 `CURL_CA_BUNDLE` 或 `SSL_CERT_FILE` 检查证书；还需由管理员在 systemd 服务中设置相同环境变量，并将证书放在服务可读的系统目录（例如 `/etc/ssl`）。默认安装直接使用 `ca-certificates` 提供的系统证书。

默认配置见 [config/config.json](config/config.json)。单网卡可保持 `interface` 为空；多网卡、VPN 或多条默认路由时，建议明确填入校园网网卡，例如 `"interface": "enp1s0"`，避免通过其他出口误判在线。外网探测使用 HTTPS 并校验状态码 / 内容。

管理员修改配置后执行：

```bash
sudo systemctl restart campus-network
```

更换账号：先执行 `campus-network off` 并等到会话释放，再由管理员删除 `/etc/campus-network/account.json`，执行 `campus-network on` 重新配置。普通用户可以控制联网，但不能读取保存的密码。

### 从 1.x 升级

安装包会修复旧版目录 / 账号文件的宽松权限，并迁移旧 `/etc/campus-network/account` 中的账号及 `/var/lib/campus-network/userindex` 会话；新 JSON 尚未自定义时，也会迁移旧门户和探测地址。旧版没有持久模式，首次迁移默认为 **off**，并尝试释放遗留会话；请确认后执行 `campus-network on`。已经由 2.x 保存的模式、账号和会话在升级时保留。

旧的 `login/logout/relogin/keep` 命令由三条新命令替代；自动重连已内置在 `on`。旧配置文件暂保留供核对。

## 运维

```bash
campus-network status
sudo systemctl status campus-network
sudo journalctl -u campus-network -n 100 --no-pager
sudo journalctl -u campus-network -f
```

日志记录状态变化和经过限频的失败原因，不记录密码。服务不可用时 CLI 显示“联网状态未知”，不会把旧状态当作在线。

正常使用 `off` 释放账号；`systemctl stop` 是管理员维护动作，不会替代持久的 `off`。卸载前也先执行 `off` 并确认会话已释放。Debian 卸载使用 `sudo apt-get remove campus-network`，保留账号和状态供以后恢复。

## 构建与验证

Linux 构建依赖为 Python 3、`dpkg-deb`、`rpmbuild`；不是运行时依赖：

```bash
python3 -m unittest discover -s tests -v
python3 tools/build.py                     # dist/ 下生成 deb、rpm、通用 tar 和校验和
python3 tools/build.py --format deb        # 也支持 rpm / tar
```

制作与当前 Debian 容器发行版 / 架构匹配的完整离线包：

```bash
docker run --rm -v "$PWD:/work" -w /work debian:12-slim sh tools/offline-bundle.sh
```

脚本从官方 APT 源下载完整依赖闭包并生成本地索引；构建时需要联网，目标服务器安装时不需要。其他架构可在对应 Debian 原生机器 / 容器中运行相同脚本。

GitHub Actions 在 Python 3.9 / 3.11 / 3.13、amd64 / arm64 上运行测试，验证真实 systemd 服务启动、普通用户 / nobody 控制、模式跨重启保存、崩溃与 watchdog 恢复、Debian 12 / 13 包安装和 Fedora RPM 安装。发布标签必须与 `VERSION` 和程序版本一致；只有全部验证通过，才上传安装包。完整离线包在 `docker --network none` 的干净 Debian 镜像里实际安装，验证未预装 Python / curl 时也能离线使用。
