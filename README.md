# campus-network

苏州工学院锐捷 ePortal 校园网持续联网服务。Python 3 标准库管理状态，curl 执行校园网认证，systemd 负责开机启动、崩溃重启和卡死恢复。没有 pip 依赖。

## 安装：只下载一个包

从 [Releases](https://github.com/fsfgrafb/campus-network/releases/latest) 下载唯一的安装包 **`campus-network_2.2.1_linux.tar.gz`**。无需选择 deb / rpm，也无需提前判断 Debian 版本或 CPU 架构。另一个 `SHA256SUMS` 文件仅用于手动校验。

假设目标服务器已经有 **Python ≥ 3.9 和 systemd**。将安装包传到任意目录，执行一行：

```bash
tar -xzf campus-network_2.2.1_linux.tar.gz && sudo sh campus-network-2.2.1/install.sh
```

安装器自动识别系统版本与 CPU，在 Debian 12 / 13 的 amd64 / arm64 上，从包内对应的本地仓库补齐 curl、CA 根证书及所需依赖，全程无需外网。系统已有且满足要求的依赖会保留，不安装其他系统或架构的依赖，也不捆绑、替换 Python。

安装包会同时携带四种环境的依赖，因此下载体积大一些。安装只使用当前机器对应的部分，APT 按实际需要安装，重复执行也可以。安装和升级需要管理员权限；日常命令全部无需 sudo。

其他使用 systemd 的 Linux 可以使用同一包，但需要预装 curl 和有效的系统 CA 证书。安装器选择原生 deb / rpm 或通用安装方式；不支持 Windows、macOS、OpenWrt 或没有 systemd 的系统。

安装后默认**离线**，不会主动占用校园网账号。首次执行：

```bash
campus-network config   # 输入账号、密码、运营商
campus-network on       # 启用保持在线模式
```

按提示输入账号、密码、运营商，之后自动复用。升级保留配置和联网意愿。密码不会回显，不需要写入命令行或 shell 历史。

## 四条命令

```bash
campus-network config   # 设置或更换唯一的校园网账号
campus-network on       # 保持在线，断开后自动重连
campus-network off      # 保持离线，停用自动认证并注销会话
campus-network status   # 查看运行模式、连接状态、说明和时间
```

所有能登录服务器的本机用户都可以使用这四条命令，无需加入用户组，也无需 sudo。它们通过 Unix socket 控制唯一的服务进程；账号文件仍仅 root 可读。这个权限模型适用于本机用户均为可信内部人员的服务器。

```bash
watch -c -n 1 campus-network status # 实时查看；直接运行 status 时终端状态带颜色
campus-network status --json      # 便于脚本读取；成功退出码不代表外网在线，应检查 state
campus-network --version
campus-network --help
```

`NO_COLOR=1 campus-network status` 关闭颜色；重定向输出时自动关闭颜色。


## 状态与恢复

运行模式与实际连接状态独立显示。例如主动离线后：

```text
模式：保持离线    状态：离线
说明：自动认证已停用，无待注销会话
账号：your-account @ 移动
最近在线：2026-10-15 22:45:49
状态更新：2026-10-15 22:45:54
```

“保持在线”表示持续检查并恢复连接；“保持离线”表示停用自动认证并注销已有会话。注销未确认时会单独显示，不会误报注销完成。JSON 字段和状态标识保持兼容。


- **on**：重启后继续保持在线。拔插网线、网络地址变化、认证失效时持续检测并尝试恢复。
- **off**：重启后仍禁止发起任何新登录。已发送的认证若随后成功，会立即安排注销；无网时保留待注销会话，恢复后继续注销。

`off` 返回表示“不再登录”的意愿已经保存，不代表认证服务器已经确认会话注销。状态中的“等待注销确认”会一直保留到明确注销成功或确认会话失效。断电、拔网线期间无法向服务器发送注销请求，服务器注销确认时间也受校园网会话超时影响。

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
| `idle` | 离线，没有待注销会话 |
| `config-error` | 配置缺失或不正确 |

服务每秒检查本地网络变化，在线时约每 3 秒检查外网；任一有效外网探测通过即可判定在线。只有确认进入认证门户才登录，不会因为某个站点暂时不可达就先注销。网卡、DHCP 和路由仍由 Debian 原有网络管理器负责。

认证失败使用有上限的指数退避：第 n 次失败（从 0 计数）的上限为 `min(2 × 2ⁿ, 120)` 秒，从该上限的 1/2 到上限之间随机选择等待时间。持续故障时每轮等待 60–120 秒，等待期间仍响应命令并检查本地链路。链路、地址或路由变化后加 0–3 秒随机扰动重新检测；健康探测间隔也有随机扰动，避免大量设备同时请求认证服务器。反复执行 `on` 不会绕过已有失败退避。

所有 HTTP 请求都有超时；恢复速度取决于交换机、DHCP 和认证服务器。systemd 在进程退出后约 1 秒重启；主循环 30 秒没有 watchdog 心跳时会重启服务。服务启动、升级和进程重启不主动注销，避免破坏可用会话。

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

设置和更换账号都执行 `campus-network config`，无需 sudo。当前只保存一份全局账号，没有多账号或用户配置档案。输入并校验新信息后，命令先持久化关闭自动登录、等待旧会话注销，再替换账号；配置成功后保持 off，执行 `campus-network on` 才开始联网。若旧会话暂时无法注销，会保留原账号并给出提示，稍后再次执行 config 即可。输入期间取消不会修改原配置。密码不回显，状态和日志不返回密码。

### 从 1.x 升级

安装包会修复旧版目录 / 账号文件的宽松权限，并迁移旧 `/etc/campus-network/account` 中的账号及 `/var/lib/campus-network/userindex` 会话；新 JSON 尚未自定义时，也会迁移旧门户和探测地址。旧版没有持久模式，首次迁移默认为 **off**，并尝试注销遗留会话；请确认后执行 `campus-network on`。已经由 2.x 保存的模式、账号和会话在升级时保留。

旧的 `login/logout/relogin/keep` 命令由新命令替代；自动重连已内置在 `on`。旧配置文件暂保留供核对。

## 运维

```bash
campus-network status
sudo systemctl status campus-network
sudo journalctl -u campus-network -n 100 --no-pager
sudo journalctl -u campus-network -f
```

日志记录状态变化和经过限频的失败原因，不记录密码。服务不可用时 CLI 显示“连接状态未知”，不会把旧状态当作在线。

正常使用 `off` 注销会话；`systemctl stop` 是管理员维护动作，不会替代持久的 `off`。卸载前也先执行 `off` 并确认会话已注销。Debian 卸载使用 `sudo apt-get remove campus-network`，保留账号和状态供以后恢复。

## 构建与验证

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

CI 内部仍构建 deb、rpm 和各平台依赖仓库，用于测试与组装；**Release 仅发布一个统一安装包及其校验和**。不再把内部中间产物作为下载选项。

本地准备原生包需 Python 3、`dpkg-deb`、`rpmbuild`：

```bash
python3 tools/build.py
```

在对应 Debian 12 / 13、amd64 / arm64 容器中运行 `sh tools/offline-bundle.sh` 准备 curl / CA 依赖仓库，不下载 Python 或 systemd。收集四个仓库到 `dist/` 后执行：

```bash
python3 tools/universal.py       # release/ 下生成统一安装包和 SHA256SUMS
```

GitHub Actions 验证 Python 3.9 / 3.11 / 3.13、amd64 / arm64、真实 systemd 普通用户控制、崩溃与 watchdog 恢复、Debian / Fedora 原生包安装。统一安装包还在四种 Debian 环境中以 `--network none` 实际运行，验证自动选择依赖、HTTPS CA 证书、重复安装和服务启用。全部通过后才发布。
