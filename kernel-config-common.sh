#!/usr/bin/env bash
#
# 云内核公共配置（CentOS / Debian 两条流水线共用的唯一权威来源）
#
# 用法（cwd 必须是内核源码目录）：
#   bash kernel-config-common.sh apply           # 套用公共配置
#   bash kernel-config-common.sh verify centos   # olddefconfig 之后校验
#   bash kernel-config-common.sh verify debian
#
# 仓库放置路径：仓库根目录 kernel-config-common.sh
# 两个 workflow 通过 $GITHUB_WORKSPACE/kernel-config-common.sh 调用。
#
# ★ 为什么要有这个文件：
#   CentOS 与 Debian 两份 workflow 的内核配置约 95% 相同，历史上已经发生过漂移
#   （Debian 有 FTP 连接跟踪 / SYN_COOKIES / iptables LOG+REJECT target，CentOS 没有；
#     CentOS 有 XFS 配额，Debian 没有 —— 这些都与发行版无关，纯属一边加了另一边忘了）。
#   公共项集中在这里之后，物理上不可能再漂移。
#   真正与发行版相关的只有 LSM 安全链（SELinux vs AppArmor），留在各自 workflow 里。

set -euo pipefail

apply_common_config() {
    echo "==> 套用公共内核配置"

    # ==========================================
    # 模块一：云服务器底层驱动与系统熵池 (通配各类云主机)
    # ==========================================
    # 1. 基础文件系统与在线扩容支持 (兼顾云盘在线升级)
    scripts/config --enable CONFIG_EXT4_FS
    scripts/config --enable CONFIG_XFS_FS
    scripts/config --enable CONFIG_BTRFS_FS
    scripts/config --enable CONFIG_BLK_DEV_LOOP
    scripts/config --enable CONFIG_XFS_ONLINE_REPAIR
    scripts/config --enable CONFIG_XFS_ONLINE_SCRUB

    # 2. 核心云架构、磁盘控制器与多云环境网卡
    scripts/config --enable CONFIG_VIRTIO_BLK
    scripts/config --enable CONFIG_SCSI_VIRTIO
    scripts/config --enable CONFIG_VIRTIO_PCI
    scripts/config --enable CONFIG_NVME_CORE            # AWS Nitro
    scripts/config --enable CONFIG_BLK_DEV_NVME
    # ★ Hyper-V(Azure)父级开关：不开它，下面所有 HYPERV_* 驱动都会被 olddefconfig
    #   静默丢弃 —— 实测某次成功 config 里 "# CONFIG_HYPERV is not set"，导致 Azure
    #   上找不到磁盘/网卡驱动、直接开不了机。必须先开这个 VMBus 核心。
    scripts/config --enable CONFIG_HYPERV
    scripts/config --enable CONFIG_HYPERV_STORAGE
    scripts/config --enable CONFIG_VMWARE_PVSCSI
    scripts/config --enable CONFIG_XEN
    scripts/config --enable CONFIG_XEN_PVH
    scripts/config --enable CONFIG_XEN_PVHVM
    scripts/config --enable CONFIG_XEN_BLKDEV_FRONTEND
    scripts/config --enable CONFIG_VIRTIO_NET
    scripts/config --enable CONFIG_VMXNET3
    scripts/config --enable CONFIG_HYPERV_NET
    scripts/config --enable CONFIG_XEN_NETDEV_FRONTEND
    scripts/config --enable CONFIG_ENA_ETHERNET         # AWS ENA 驱动
    scripts/config --enable CONFIG_GVE                  # GCP 谷歌云网卡
    scripts/config --enable CONFIG_HYPERV_UTILS         # Azure 微软云底层心跳
    scripts/config --enable CONFIG_HYPERV_BALLOON       # Azure 内存气球
    scripts/config --enable CONFIG_NET_VENDOR_MELLANOX  # 高防/特种机房物理网卡
    scripts/config --enable CONFIG_MLX4_CORE
    scripts/config --enable CONFIG_MLX4_EN              # Mellanox CX-3 以太网(光它 CORE 不够，要 EN 才通网)
    scripts/config --enable CONFIG_MLX5_CORE            # Mellanox CX-4/5/6(云加速网络/特种机房主力)
    scripts/config --enable CONFIG_MLX5_CORE_EN
    # SR-IOV 虚拟网卡(VF)：云 VPS 常拿到的是 VF 而非物理 PF，缺了会网卡不认、开不了机
    scripts/config --enable CONFIG_IGBVF
    scripts/config --enable CONFIG_IXGBEVF
    scripts/config --enable CONFIG_IAVF                 # Intel i40e/ice 系列 VF(原 i40evf)
    # ★ 通用 KVM/QEMU 内存气球：绝大多数廉价 VPS 是 KVM，服务商常用 virtio-balloon
    #   动态回收/超售内存，缺了它宿主无法回收本机空闲内存(defconfig 默认没开)。
    scripts/config --enable CONFIG_VIRTIO_BALLOON

    # 3. 硬件随机数生成器 (解决云 VPS 开机及 HTTPS 握手严重阻塞卡死)
    scripts/config --enable CONFIG_HW_RANDOM_VIRTIO
    scripts/config --enable CONFIG_CRYPTO_DEV_VIRTIO

    # 4. 云控制台与串口
    scripts/config --enable CONFIG_HVC_XEN
    scripts/config --enable CONFIG_VIRTIO_CONSOLE
    scripts/config --enable CONFIG_SERIAL_8250
    scripts/config --enable CONFIG_SERIAL_8250_CONSOLE

    # ==========================================
    # 模块二：VNC 控制台防花屏与虚拟显卡
    # ==========================================
    scripts/config --enable CONFIG_VGA_CONSOLE
    scripts/config --enable CONFIG_DUMMY_CONSOLE
    scripts/config --enable CONFIG_FRAMEBUFFER_CONSOLE
    scripts/config --enable CONFIG_FB
    scripts/config --enable CONFIG_DRM
    scripts/config --enable CONFIG_DRM_BOCHS
    scripts/config --enable CONFIG_DRM_QXL
    scripts/config --enable CONFIG_DRM_VIRTIO_GPU
    # 彻底禁用庞大的物理显卡驱动以瘦身
    scripts/config --disable CONFIG_DRM_AMDGPU
    scripts/config --disable CONFIG_DRM_NOUVEAU
    scripts/config --disable CONFIG_DRM_I915

    # ==========================================
    # 模块三：物理主机扩展 (软路由/独立服务器/NAS)
    # ==========================================
    scripts/config --enable CONFIG_ATA
    scripts/config --enable CONFIG_SATA_AHCI
    scripts/config --enable CONFIG_MEGARAID_SAS         # LSI 阵列卡
    scripts/config --enable CONFIG_SCSI_MPT3SAS         # LSI HBA 直通卡
    scripts/config --enable CONFIG_SCSI_HPSA            # HP 阵列卡
    scripts/config --enable CONFIG_USB
    scripts/config --enable CONFIG_USB_XHCI_HCD
    scripts/config --enable CONFIG_USB_EHCI_HCD
    scripts/config --enable CONFIG_USB_STORAGE
    scripts/config --enable CONFIG_USB_UAS
    scripts/config --enable CONFIG_INPUT_KEYBOARD
    scripts/config --enable CONFIG_KEYBOARD_ATKBD
    scripts/config --enable CONFIG_USB_HID
    scripts/config --enable CONFIG_SYSFB_SIMPLEFB
    scripts/config --enable CONFIG_FB_EFI
    scripts/config --enable CONFIG_E1000E
    scripts/config --enable CONFIG_IGB
    scripts/config --enable CONFIG_IGC                  # i225/i226 2.5G
    scripts/config --enable CONFIG_IXGBE                # 万兆光口
    scripts/config --enable CONFIG_R8169                # Realtek 家用

    # ==========================================
    # 模块四：核心网络优化与精准时钟 (防数据库崩溃)
    # ==========================================
    # 1. BBR 与 QoS 队列 (极限测速与流量整形)
    scripts/config --enable CONFIG_TCP_CONG_BBR
    # ★ CONFIG_DEFAULT_TCP_CONG 是由 choice 派生的【只读字符串】，直接 --set-str 会被
    #   olddefconfig 按 choice 的实际选择重算覆盖(退回 cubic)。正确做法是启用 choice
    #   成员 DEFAULT_BBR(依赖 TCP_CONG_BBR=y)，字符串才会派生成 "bbr"。
    #   同时禁掉 defconfig 默认的 CUBIC，避免 choice 出现双选导致回退。
    scripts/config --disable CONFIG_DEFAULT_CUBIC
    scripts/config --enable CONFIG_DEFAULT_BBR
    scripts/config --enable CONFIG_NET_SCH_FQ
    # 默认 qdisc 走 choice 成员 DEFAULT_FQ。★ 关键：这个 choice 被父开关
    #   CONFIG_NET_SCH_DEFAULT gate 住(某次成功 config 里是 "# CONFIG_NET_SCH_DEFAULT is not set")，
    #   不先开父开关，DEFAULT_FQ 永远设不上、DEFAULT_NET_SCH 也不会生成。
    scripts/config --enable CONFIG_NET_SCH_DEFAULT
    scripts/config --disable CONFIG_DEFAULT_PFIFO_FAST
    scripts/config --enable CONFIG_DEFAULT_FQ
    scripts/config --enable CONFIG_NET_SCH_FQ_CODEL
    scripts/config --enable CONFIG_NET_SCH_FQ_PIE
    scripts/config --enable CONFIG_NET_SCH_CAKE
    scripts/config --enable CONFIG_NET_SCH_PIE

    # 2. 虚拟隧道 (代理与异地组网)
    scripts/config --enable CONFIG_TUN
    scripts/config --module CONFIG_DUMMY                # 外挂模块 (=m) AWS问题
    scripts/config --enable CONFIG_WIREGUARD

    # 3. 策略路由
    scripts/config --enable CONFIG_IP_ADVANCED_ROUTER
    scripts/config --enable CONFIG_IP_MULTIPLE_TABLES
    scripts/config --enable CONFIG_IPV6_MULTIPLE_TABLES
    scripts/config --enable CONFIG_IPV6_SUBTREES

    # 4. KVM / Hyper-V 精准时钟同步 (防高负载时钟漂移导致 MariaDB/MySQL 事务损坏)
    scripts/config --enable CONFIG_PTP_1588_CLOCK_KVM
    scripts/config --enable CONFIG_HYPERV_TIMER

    # ==========================================
    # 补充：Docker 网络端口映射 (DNAT/MASQUERADE) 刚需
    # ==========================================
    # 1. 基础 IPv4 iptables 框架与 NAT 表
    scripts/config --enable CONFIG_IP_NF_IPTABLES
    scripts/config --enable CONFIG_IP_NF_FILTER
    scripts/config --enable CONFIG_IP_NF_NAT
    scripts/config --enable CONFIG_IP_NF_MANGLE

    # 2. 核心 NAT 动作扩展 (彻底解决 DNAT 和 MASQUERADE 报错)
    scripts/config --enable CONFIG_NETFILTER_XT_NAT
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_MASQUERADE
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_REDIRECT
    scripts/config --enable CONFIG_IP_NF_TARGET_MASQUERADE
    scripts/config --enable CONFIG_IP_NF_TARGET_REDIRECT

    # 3. 基础 IPv6 iptables 框架 (防止 Docker IPv6 桥接网络报错)
    scripts/config --enable CONFIG_IP6_NF_IPTABLES
    scripts/config --enable CONFIG_IP6_NF_FILTER
    scripts/config --enable CONFIG_IP6_NF_MANGLE
    scripts/config --enable CONFIG_IP6_NF_NAT
    scripts/config --enable CONFIG_IP6_NF_TARGET_MASQUERADE

    # ==========================================
    # 模块五：防火墙体系 (firewalld / UFW / fail2ban 通用)
    # ==========================================
    # 1. 防护动作与日志依赖
    #    ★ 以下 5 项原先只在 Debian 那份里有，与发行版无关，属于漏加，现统一到公共层
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_LOG      # 解决 UFW 报错 LOG target not found
    scripts/config --enable CONFIG_IP_NF_TARGET_REJECT
    scripts/config --enable CONFIG_IP6_NF_TARGET_REJECT
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_RATEEST   # UFW 速率检测
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_RATEEST

    # 2. Netfilter 高级 Target/Match (防 CC 与连接控制)
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_TPROXY
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_SOCKET
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_MAC
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_IPRANGE
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_MULTIPORT
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_COMMENT
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_RECENT    # fail2ban 刚需
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_LIMIT
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_HASHLIMIT
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_STRING    # 字符串特征拦截
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_LENGTH
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_STATE
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_CONNLIMIT # 限制并发
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_OWNER
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_REJECT
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_MARK
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_MARK
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_TCPMSS
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_TOS
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_HL
    scripts/config --enable CONFIG_NETFILTER_XT_TARGET_PROXY

    # 3. IPSet 集成 (海量 IP 黑名单秒级匹配)
    scripts/config --enable CONFIG_IP_SET
    # ★ CONFIG_IP_SET_MAX 是【整数】(ipset 集合上限，默认 256)，不是布尔开关。
    #   原先 --enable 会写成 =y，触发 kconfig "invalid value" 报错。用默认 256 即可；
    #   若要改数量：scripts/config --set-val CONFIG_IP_SET_MAX 512
    scripts/config --enable CONFIG_IP_SET_BITMAP_IP
    scripts/config --enable CONFIG_IP_SET_BITMAP_IPMAC
    scripts/config --enable CONFIG_IP_SET_BITMAP_PORT
    scripts/config --enable CONFIG_IP_SET_HASH_IP
    scripts/config --enable CONFIG_IP_SET_HASH_NET
    scripts/config --enable CONFIG_NETFILTER_XT_SET

    # 4. Nftables 核心框架 (firewalld 启动强依赖)
    scripts/config --enable CONFIG_NF_TABLES
    scripts/config --enable CONFIG_NF_TABLES_INET
    scripts/config --enable CONFIG_NF_TABLES_NETDEV
    scripts/config --enable CONFIG_NF_TABLES_BRIDGE
    scripts/config --enable CONFIG_NFT_CT
    scripts/config --enable CONFIG_NFT_COUNTER
    scripts/config --enable CONFIG_NFT_LOG
    scripts/config --enable CONFIG_NFT_LIMIT
    scripts/config --enable CONFIG_NFT_MASQ
    scripts/config --enable CONFIG_NFT_REDIR
    scripts/config --enable CONFIG_NFT_NAT
    scripts/config --enable CONFIG_NFT_REJECT
    scripts/config --enable CONFIG_NFT_COMPAT
    scripts/config --enable CONFIG_NF_TABLES_IPV4
    scripts/config --enable CONFIG_NFT_REJECT_IPV4
    scripts/config --enable CONFIG_NF_TABLES_IPV6
    scripts/config --enable CONFIG_NFT_REJECT_IPV6
    # 注：NFT_CHAIN_ROUTE/NAT_IPV4/IPV6 旧内核的独立链开关已合并进 NFT_NAT + NFT_FIB，此处不再单列
    # FIB 路由转发表核心 (解决 firewalld reload 报错)
    scripts/config --enable CONFIG_NFT_FIB
    scripts/config --enable CONFIG_NFT_FIB_INET
    scripts/config --enable CONFIG_NFT_FIB_IPV4
    scripts/config --enable CONFIG_NFT_FIB_IPV6
    scripts/config --enable CONFIG_NFT_QUOTA
    scripts/config --enable CONFIG_NFT_REJECT_INET
    scripts/config --enable CONFIG_NFT_HASH
    scripts/config --enable CONFIG_NFT_SOCKET
    scripts/config --enable CONFIG_NFT_OSF
    scripts/config --enable CONFIG_NFT_TPROXY
    scripts/config --enable CONFIG_NFT_SYNPROXY

    # 5. Mangle / Raw 表与特殊过滤
    scripts/config --enable CONFIG_IP_NF_RAW
    scripts/config --enable CONFIG_IP6_NF_RAW
    scripts/config --enable CONFIG_IP_NF_ARPTABLES
    scripts/config --enable CONFIG_IP_NF_ARPFILTER
    scripts/config --enable CONFIG_IP_NF_ARP_MANGLE

    # 6. 补充
    scripts/config --enable CONFIG_NETFILTER_ADVANCED
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_HL
    scripts/config --enable CONFIG_IP6_NF_TARGET_HL
    scripts/config --enable CONFIG_IP6_NF_MATCH_RT

    # ==========================================
    # 模块六：容器引擎与面板建站全环境 (Docker/Podman/宝塔/CyberPanel)
    # ==========================================
    # 1. 资源隔离与命名空间
    scripts/config --enable CONFIG_NAMESPACES
    scripts/config --enable CONFIG_USER_NS
    scripts/config --enable CONFIG_CGROUPS
    scripts/config --enable CONFIG_MEMCG
    scripts/config --enable CONFIG_MEMCG_V1             # 面板/老架构防 OOM
    scripts/config --enable CONFIG_BLK_CGROUP
    scripts/config --enable CONFIG_CGROUP_SCHED
    scripts/config --enable CONFIG_CGROUP_PIDS
    scripts/config --enable CONFIG_CGROUP_DEVICE
    scripts/config --enable CONFIG_CGROUP_CPUACCT
    scripts/config --enable CONFIG_CPUSETS

    # 2. 容器存储、网桥与 NAT 映射
    scripts/config --enable CONFIG_OVERLAY_FS
    scripts/config --enable CONFIG_BRIDGE
    scripts/config --enable CONFIG_BRIDGE_NETFILTER
    # PVE「VLAN 感知网桥」刚需(vmbr 上直接打 VLAN tag)，缺它该功能不可用
    scripts/config --enable CONFIG_BRIDGE_VLAN_FILTERING
    scripts/config --enable CONFIG_VETH
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_ADDRTYPE
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_CONNTRACK
    scripts/config --enable CONFIG_NETFILTER_XT_MARK
    # connmark 匹配/打标(透明代理 sing-box/Xray 按连接策略路由常用)
    scripts/config --enable CONFIG_NETFILTER_XT_CONNMARK
    scripts/config --enable CONFIG_NF_NAT_IPV6

    # 3. 磁盘配额 (面板多用户空间划分核心依赖)
    #    ★ XFS 配额原先只在 CentOS 那份里有，但两边都开了 XFS_FS，属于 Debian 漏加
    scripts/config --enable CONFIG_QUOTA
    scripts/config --enable CONFIG_QUOTA_NETLINK_INTERFACE
    scripts/config --enable CONFIG_QUOTACTL
    scripts/config --enable CONFIG_QFMT_V1
    scripts/config --enable CONFIG_QFMT_V2
    scripts/config --enable CONFIG_XFS_QUOTA
    scripts/config --enable CONFIG_XFS_POSIX_ACL
    scripts/config --enable CONFIG_EXT4_FS_POSIX_ACL
    scripts/config --enable CONFIG_EXT4_FS_SECURITY

    # 4. FTP 被动穿透与防御
    #    ★ 以下 3 项原先只在 Debian 那份里有，与发行版无关，属于 CentOS 漏加
    scripts/config --enable CONFIG_NF_CONNTRACK_FTP
    scripts/config --enable CONFIG_NF_NAT_FTP
    scripts/config --enable CONFIG_SYN_COOKIES

    # 5. Systemd 进程沙盒刚需
    scripts/config --enable CONFIG_SECCOMP
    scripts/config --enable CONFIG_SECCOMP_FILTER
    # 注：原先这里还开了 CONFIG_SECCOMP_CACHE_DEBUG，那是调试项，生产内核不需要，已移除

    # ==========================================
    # 模块七：高性能 Web IO 与 HTTPS 加速 (Nginx / OpenLiteSpeed)
    # ==========================================
    # 1. 核心 eBPF 与网络旁路收发
    scripts/config --enable CONFIG_BPF
    scripts/config --enable CONFIG_BPF_SYSCALL
    # ★ BPF JIT：不开则所有 eBPF 程序解释执行、性能差，且 Cilium/现代 nftables/XDP 等
    #   基本要求 JIT。成功 config 里 "# CONFIG_BPF_JIT is not set" 是明显欠优。
    scripts/config --enable CONFIG_BPF_JIT
    scripts/config --enable CONFIG_CGROUP_BPF
    scripts/config --enable CONFIG_XDP_SOCKETS          # AF_XDP 高性能收发包

    # 2. 异步 IO 与 Web 架构依赖
    scripts/config --enable CONFIG_INOTIFY_USER         # 配置热重载
    scripts/config --enable CONFIG_FANOTIFY
    scripts/config --enable CONFIG_FANOTIFY_ACCESS_PERMISSIONS
    scripts/config --enable CONFIG_SYSVIPC
    scripts/config --enable CONFIG_POSIX_MQUEUE         # 数据库与异步 IO 依赖
    scripts/config --enable CONFIG_AIO
    scripts/config --enable CONFIG_IO_URING
    scripts/config --enable CONFIG_EPOLL

    # 3. 内核级 TLS (大幅降低 HTTPS 加解密 CPU 占用)
    scripts/config --enable CONFIG_TLS
    scripts/config --enable CONFIG_TLS_DEVICE

    # ==========================================
    # 模块八：跨平台文件系统与高阶运维工具
    # ==========================================
    # 1. 监控、FUSE 与网络共享
    scripts/config --enable CONFIG_FUSE_FS
    scripts/config --enable CONFIG_CUSE
    scripts/config --enable CONFIG_TASKSTATS
    scripts/config --enable CONFIG_TASK_DELAY_ACCT
    scripts/config --enable CONFIG_TASK_XACCT
    scripts/config --enable CONFIG_TASK_IO_ACCOUNTING
    scripts/config --enable CONFIG_CIFS
    scripts/config --enable CONFIG_NFS_FS
    # 内核 NFS 服务端：把本机当 NAS 对外提供 NFS 共享(上面 NFS_FS 只是客户端/挂载别人的)
    scripts/config --enable CONFIG_NFSD
    scripts/config --enable CONFIG_NFSD_V4

    # 2. U盘与跨平台文件格式
    scripts/config --enable CONFIG_FAT_FS
    scripts/config --enable CONFIG_VFAT_FS
    scripts/config --enable CONFIG_EXFAT_FS
    scripts/config --enable CONFIG_NTFS3_FS             # 原生高性能 NTFS3
    scripts/config --enable CONFIG_NTFS3_LZX_XPRESS
    scripts/config --enable CONFIG_NTFS3_FS_POSIX_ACL
    scripts/config --enable CONFIG_NLS_CODEPAGE_437
    scripts/config --enable CONFIG_NLS_ISO8859_1
    scripts/config --enable CONFIG_NLS_UTF8

    # 3. K3s / 负载均衡基础
    scripts/config --enable CONFIG_IP_VS
    scripts/config --enable CONFIG_IP_VS_PROTO_TCP
    scripts/config --enable CONFIG_IP_VS_PROTO_UDP
    scripts/config --enable CONFIG_IP_VS_RR
    scripts/config --enable CONFIG_IP_VS_WRR
    scripts/config --enable CONFIG_IP_VS_SH
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_IPVS

    # ==========================================
    # 模块十：x86_64 硬件加速全家桶 (Intel + AMD 双平台通吃)
    # ==========================================
    # 1. 基础 AES 加密加速 (HTTPS 建站、VPN 刚需)
    scripts/config --enable CONFIG_CRYPTO_AES_NI_INTEL

    # 注：ChaCha20/Poly1305/SHA-NI/SHA512-SSSE3/BLAKE2s/CRC32C-INTEL/CRC32-PCLMUL/
    #     CRCT10DIF/GHASH-CLMUL 这些 x86 加速实现，新内核已重构进 CRYPTO_LIB_*_ARCH 与
    #     CRC32_ARCH，由内核按 CPU 能力自动启用，不再是可单独设置的开关，故不再列出。
    #     (AES-NI 仍是独立可设开关，保留上面一行即可。)

    # 信任并激活 CPU 硬件真随机数 (秒开机，杜绝 SSH 登录卡顿)
    # 注：RANDOM_TRUST_CPU / RANDOM_TRUST_BOOTLOADER 自内核 6.2 起已删除为编译期开关，
    #     改为默认开启、用启动参数 random.trust_cpu=off 才关闭，故无需在此设置。
    scripts/config --enable CONFIG_HW_RANDOM_AMD

    # AMD 专属密码学协处理器 (CCP)
    scripts/config --enable CONFIG_CPU_SUP_AMD
    scripts/config --enable CONFIG_CRYPTO_DEV_CCP
    scripts/config --enable CONFIG_CRYPTO_DEV_CCP_DD
    scripts/config --enable CONFIG_CRYPTO_DEV_SP_CCP

    # AMD P-State 频率调度器与温度传感器
    #    注：原先这里还开了 CONFIG_X86_AMD_PSTATE_UT，那是单元测试模块，生产内核不需要，已移除
    scripts/config --enable CONFIG_X86_AMD_PSTATE
    # ★ CONFIG_X86_AMD_PSTATE_DEFAULT_MODE 是【整数枚举】(1=disable 2=passive 3=active/EPP 4=guided)，
    #   不是字符串。原先 --set-str "amd-pstate-epp" 触发 kconfig "invalid value" 报错。
    #   X86_AMD_PSTATE=y 时 Kconfig 默认已是 3(active=EPP)，无需手工设置，故直接移除。
    scripts/config --enable CONFIG_SENSORS_K10TEMP

    # ==========================================
    # 模块十一：PVE 宿主机 / Hypervisor 核心组件
    # ==========================================
    # 1. KVM 虚拟化宿主端支持
    scripts/config --enable CONFIG_VIRTUALIZATION
    scripts/config --enable CONFIG_KVM
    scripts/config --enable CONFIG_KVM_INTEL
    scripts/config --enable CONFIG_KVM_AMD
    scripts/config --enable CONFIG_VHOST_NET
    scripts/config --enable CONFIG_VHOST_VSOCK
    scripts/config --enable CONFIG_VHOST_SCSI

    # 2. IOMMU 与 VFIO 硬件直通
    scripts/config --enable CONFIG_IOMMU_SUPPORT
    scripts/config --enable CONFIG_INTEL_IOMMU
    scripts/config --enable CONFIG_INTEL_IOMMU_DEFAULT_ON
    scripts/config --enable CONFIG_AMD_IOMMU
    scripts/config --enable CONFIG_VFIO
    scripts/config --enable CONFIG_VFIO_PCI
    scripts/config --enable CONFIG_VFIO_IOMMU_TYPE1
    scripts/config --enable CONFIG_IRQ_REMAP

    # 3. PVE 高级网络桥接、VLAN 与 OVS
    scripts/config --enable CONFIG_BONDING              # 网卡聚合/双线汇聚
    scripts/config --enable CONFIG_MACVLAN              # LXC 和 Docker 常用网络
    scripts/config --enable CONFIG_MACVTAP
    scripts/config --enable CONFIG_IPVLAN
    scripts/config --enable CONFIG_VXLAN
    scripts/config --enable CONFIG_VLAN_8021Q           # PVE 上的 VLAN Tag 支持
    scripts/config --enable CONFIG_OPENVSWITCH          # PVE OVS 虚拟交换机
    scripts/config --enable CONFIG_NET_CLS_CGROUP

    # 4. LXC 容器与高级 Cgroup 资源隔离
    scripts/config --enable CONFIG_CGROUP_FREEZER
    scripts/config --enable CONFIG_CGROUP_HUGETLB
    scripts/config --enable CONFIG_BLK_CGROUP_RWSTAT
    scripts/config --enable CONFIG_CHECKPOINT_RESTORE
    scripts/config --enable CONFIG_FHANDLE

    # 5. 硬件看门狗：PVE HA 围栏 / VPS 卡死自动重启。QEMU/KVM 常见的是 i6300esb。
    scripts/config --enable CONFIG_WATCHDOG_CORE
    scripts/config --enable CONFIG_I6300ESB_WDT

    # ==========================================
    # 模块十二：LVM2 与 Device Mapper (PVE / 物理机存储刚需)
    # ==========================================
    scripts/config --enable CONFIG_MD
    scripts/config --enable CONFIG_BLK_DEV_DM
    scripts/config --enable CONFIG_DM_THIN_PROVISIONING
    scripts/config --enable CONFIG_DM_CRYPT
    scripts/config --enable CONFIG_DM_SNAPSHOT
    scripts/config --enable CONFIG_DM_MIRROR

    # ==========================================
    # 模块十三：IPv6 核心协议栈与高级网络
    # ==========================================
    scripts/config --enable CONFIG_IPV6
    # 高级路由与 SLAAC 自动分配依赖 (PVE vmbr0 桥接刚需)
    scripts/config --enable CONFIG_IPV6_ROUTER_PREF      # 路由器首选项特性
    scripts/config --enable CONFIG_IPV6_ROUTE_INFO       # IPv6 路由信息
    scripts/config --enable CONFIG_IPV6_OPTIMISTIC_DAD   # 乐观 DAD，加速虚拟机获取 IPv6
    scripts/config --enable CONFIG_IPV6_NDISC_NODETYPE   # 高级邻居发现
    # 各种隧道支持 (异地组网、无 IPv6 环境下打洞)
    scripts/config --enable CONFIG_IPV6_SIT              # IPv6-in-IPv4 (HE.net 隧道刚需)
    scripts/config --enable CONFIG_IPV6_SIT_6RD          # 6rd 快速部署隧道
    scripts/config --enable CONFIG_IPV6_TUNNEL           # 纯 IPv6 隧道
    scripts/config --enable CONFIG_IPV6_GRE              # GRE over IPv6
    # IPsec 加密支持
    scripts/config --enable CONFIG_INET6_AH
    scripts/config --enable CONFIG_INET6_ESP
    scripts/config --enable CONFIG_INET6_IPCOMP
    scripts/config --enable CONFIG_IPV6_MIP6             # 移动 IPv6

    # ==========================================
    # 模块十四：内存压缩、Intel 对称调度、Web 极速握手
    # ==========================================
    # 1. ZRAM 与 ZSWAP 内存压缩 (适合 1G/2G 内存的云 VPS，防 OOM)
    scripts/config --enable CONFIG_ZSMALLOC
    scripts/config --enable CONFIG_ZRAM
    scripts/config --enable CONFIG_ZSWAP
    scripts/config --enable CONFIG_ZPOOL
    scripts/config --enable CONFIG_CRYPTO_LZ4           # ZRAM 推荐算法
    scripts/config --enable CONFIG_CRYPTO_ZSTD          # ZSWAP 推荐算法
    # 让 zram 也能用 zstd 后端(更高压缩比)，默认仍是 lzo-rle(更快)，运行时可切换
    scripts/config --enable CONFIG_ZRAM_BACKEND_ZSTD

    # 2. Intel CPU 对称支持
    scripts/config --enable CONFIG_CPU_SUP_INTEL
    scripts/config --enable CONFIG_X86_INTEL_PSTATE
    scripts/config --enable CONFIG_MICROCODE            # 加载 CPU 微码修复漏洞(新内核已合并 Intel/AMD)

    # 3. TCP Fast Open (降低 Nginx/LiteSpeed 握手延迟)
    scripts/config --enable CONFIG_TCP_FASTOPEN

    # 4. IPsec 防火墙策略匹配
    scripts/config --enable CONFIG_NETFILTER_XT_MATCH_POLICY

    # ==========================================
    # 补充模块一：MGLRU 内存管理与 THP 优化 (数据库与缓存刚需)
    # ==========================================
    scripts/config --enable CONFIG_LRU_GEN
    scripts/config --enable CONFIG_LRU_GEN_ENABLED
    # Redis / MariaDB 的透明大页行为设为 madvise (按需分配)
    scripts/config --enable CONFIG_TRANSPARENT_HUGEPAGE
    scripts/config --enable CONFIG_TRANSPARENT_HUGEPAGE_MADVISE
    scripts/config --disable CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS
    # KSM 同页合并：PVE 宿主跑多台相似 VM 时去重内存，显著省 RAM(运行时 sysctl 开启)
    scripts/config --enable CONFIG_KSM

    # ==========================================
    # 补充模块二：高级路由隔离与多路径传输 (代理与隧道分流刚需)
    # ==========================================
    scripts/config --enable CONFIG_NET_VRF              # 契合 sing-box/Xray 严格路由
    scripts/config --enable CONFIG_MPTCP                # 多路径 TCP
    scripts/config --enable CONFIG_MPTCP_IPV6
    # 连接跟踪事件，防止海量并发下网关或代理模块丢单
    scripts/config --enable CONFIG_NF_CONNTRACK_EVENTS
    scripts/config --enable CONFIG_NF_CONNTRACK_TIMEOUT

    # ==========================================
    # 补充模块三：PSI 压力指标与跨平台容器支持
    # ==========================================
    scripts/config --enable CONFIG_PSI
    scripts/config --disable CONFIG_PSI_DEFAULT_DISABLED    # 默认开启
    # 支持在 x86 上通过 QEMU 运行 ARM 架构 Docker 镜像
    scripts/config --enable CONFIG_BINFMT_MISC

    # ==========================================
    # 补充模块四：Web 服务器高吞吐抢占模型
    # ==========================================
    scripts/config --enable CONFIG_PREEMPT_VOLUNTARY
    scripts/config --disable CONFIG_PREEMPT
    # 非游戏/语音服务器，250Hz 是吞吐量与延迟的平衡点
    scripts/config --enable CONFIG_HZ_250
    scripts/config --disable CONFIG_HZ_1000

    # ==========================================
    # 补充模块五：TC 流量控制与精细化 QoS 限速
    # ==========================================
    # 1. 核心 QoS 调度框架与入口控制
    scripts/config --enable CONFIG_NET_SCHED
    scripts/config --enable CONFIG_NET_SCH_INGRESS

    # 2. 核心限速与整形算法
    scripts/config --enable CONFIG_NET_SCH_HTB          # 层次令牌桶
    scripts/config --enable CONFIG_NET_SCH_TBF          # 令牌桶过滤器
    scripts/config --enable CONFIG_NET_SCH_SFQ          # 随机公平队列
    scripts/config --enable CONFIG_NET_SCH_RED          # 早期随机丢弃
    scripts/config --enable CONFIG_NET_SCH_NETEM        # 延迟/丢包模拟器

    # 3. 流量分类器
    scripts/config --enable CONFIG_NET_CLS
    scripts/config --enable CONFIG_NET_CLS_U32          # tc 核心过滤器
    scripts/config --enable CONFIG_NET_CLS_MATCHALL
    scripts/config --enable CONFIG_NET_CLS_BPF          # 基于 eBPF 的现代分类器
    scripts/config --enable CONFIG_NET_CLS_ROUTE4

    # 4. 流量动作
    scripts/config --enable CONFIG_NET_CLS_ACT
    scripts/config --enable CONFIG_NET_ACT_POLICE       # 硬性限速策略
    scripts/config --enable CONFIG_NET_ACT_MIRRED       # 流量镜像与重定向
    scripts/config --enable CONFIG_NET_ACT_BPF

    # ==========================================
    # 补充模块 A：顶级异步与 TLS 卸载
    # ==========================================
    scripts/config --enable CONFIG_IO_URING_ZCRX        # io_uring 零拷贝接收
    scripts/config --enable CONFIG_IO_URING_BPF
    scripts/config --enable CONFIG_IO_URING_BPF_OPS
    scripts/config --enable CONFIG_NET_HANDSHAKE        # TLS 握手卸载到内核
    scripts/config --enable CONFIG_TCP_AO               # TCP 认证选项，抗注入

    # ==========================================
    # 补充模块 B：DAMON 内存智能回收
    # ==========================================
    scripts/config --enable CONFIG_DAMON
    scripts/config --enable CONFIG_DAMON_VADDR          # 监控虚拟地址空间
    scripts/config --enable CONFIG_DAMON_PADDR          # 监控物理地址空间
    scripts/config --enable CONFIG_DAMON_RECLAIM        # 主动内存回收
    scripts/config --enable CONFIG_DAMON_LRU_SORT       # 按访问频率优化 LRU

    # ==========================================
    # 补充模块 C：Livepatch 与内存安全加固
    # ==========================================
    scripts/config --enable CONFIG_LIVEPATCH            # 内核热补丁
    scripts/config --enable CONFIG_HARDENED_USERCOPY    # 强化内核/用户空间拷贝
    scripts/config --enable CONFIG_INIT_STACK_ALL_ZERO  # 栈内存清零，防数据泄露
    scripts/config --enable CONFIG_SECURITY_LANDLOCK    # 轻量级沙盒
    scripts/config --enable CONFIG_BPF_LSM              # 现代 BPF 安全模块
    # 注：CONFIG_HAVE_LIVEPATCH 是架构只读项，由内核自己声明，手工 enable 无效，已移除
    # 注：原先的「Rust 内核支持」整段已移除 —— 依赖里没有 rustc/bindgen/rust-src，
    #     olddefconfig 会直接丢弃这些项，属于自欺欺人。若真要开，需先装匹配版本的 Rust 工具链。

    # ==========================================
    # 安全审计 (阿里云盾 / 腾讯云镜等 Agent 依赖)
    # ==========================================
    scripts/config --enable CONFIG_AUDIT
    scripts/config --enable CONFIG_AUDITSYSCALL

    # ==========================================
    # 内核瘦身：禁用无用外设
    # ==========================================
    scripts/config --disable CONFIG_SOUND
    scripts/config --disable CONFIG_SND
    scripts/config --disable CONFIG_WLAN
    scripts/config --disable CONFIG_BT
    scripts/config --disable CONFIG_MEDIA_SUPPORT

    # ==========================================
    # 关闭调试信息
    # ==========================================
    # ★ 修正：现代内核的调试信息是「单选」(NONE / DWARF4 / DWARF5)。
    #   原写法把 NONE 也一起 disable 了，等于选不中「不生成调试信息」这一项，
    #   反而可能生成数 GB 的调试符号 —— 编译更慢、安装包暴涨。
    #   正确做法是 enable NONE。
    scripts/config --enable CONFIG_DEBUG_INFO_NONE
    scripts/config --disable CONFIG_DEBUG_INFO_DWARF4
    scripts/config --disable CONFIG_DEBUG_INFO_DWARF5
    scripts/config --disable CONFIG_DEBUG_INFO_BTF

    # ==========================================
    # 绕过模块签名验证
    # ==========================================
    scripts/config --disable CONFIG_MODULE_SIG
    scripts/config --disable CONFIG_SYSTEM_TRUSTED_KEYS
    scripts/config --disable CONFIG_SYSTEM_REVOCATION_KEYS
    sed -ri '/CONFIG_SYSTEM_TRUSTED_KEYS/s/=.+/=""/g' .config
    sed -ri '/CONFIG_SYSTEM_REVOCATION_KEYS/s/=.+/=""/g' .config

    # ==========================================
    # 压缩算法
    # ==========================================
    # vmlinuz 用 XZ：体积小，且兼容老 GRUB
    scripts/config --disable CONFIG_KERNEL_GZIP
    scripts/config --disable CONFIG_KERNEL_ZSTD
    scripts/config --disable CONFIG_KERNEL_BZIP2
    scripts/config --disable CONFIG_KERNEL_LZMA
    scripts/config --disable CONFIG_KERNEL_LZ4
    scripts/config --disable CONFIG_KERNEL_LZO
    scripts/config --enable CONFIG_KERNEL_XZ

    # ★ 模块压缩：真正的门是父开关 CONFIG_MODULE_COMPRESS。某次成功 config 里是
    #   "# CONFIG_MODULE_COMPRESS is not set"，所以 MODULE_COMPRESS_XZ 这个符号根本不存在、
    #   无从选起(这就是之前 verify 里 "XZ 符号完全不存在" 的原因)。必须先开父开关，
    #   再选算法 XZ。用 XZ 而非 ZSTD 的理由：
    #   .ko.zst 需要目标系统 kmod>=29，而 Debian10=kmod26 / Debian11=kmod28 / EL8=kmod25 全不认；
    #   XZ 的模块压缩 kmod 很早(约 2012)就支持，几乎所有系统都能加载。
    #   （老 GRUB 只关心上面的 KERNEL_XZ，与模块压缩无关，别混淆。）
    #   注：下载体积由 .deb/.rpm 自身的 xz 打包压缩决定；模块压缩影响的是安装后
    #   /lib/modules 的磁盘占用(未压缩可能几百 MB，XZ 后约几十 MB)。
    scripts/config --enable  CONFIG_MODULE_COMPRESS
    scripts/config --disable CONFIG_MODULE_COMPRESS_NONE
    scripts/config --disable CONFIG_MODULE_COMPRESS_GZIP
    scripts/config --disable CONFIG_MODULE_COMPRESS_ZSTD
    scripts/config --enable  CONFIG_MODULE_COMPRESS_XZ

    echo "==> 公共配置套用完毕"
}

# ------------------------------------------------------------------
# 配置校验：必须在 make olddefconfig 之后调用
#
# 为什么必须有这一步：
#   olddefconfig 会把依赖不满足的选项【静默丢弃】，不报任何错。
#   于是「以为开了 BBR / VFIO / nftables，实际没开」，编完也没人发现，
#   直到装到机器上才暴露。这里把不可见的东西变成可见的，关键项缺失直接让构建失败。
# ------------------------------------------------------------------

_vc_fail=0

_check_critical() {
    local key="$1" desc="${2:-}"
    if grep -qE "^${key}=(y|m)$" .config; then
        printf '  [OK]   %-45s %s\n' "$key" "$desc"
    else
        local actual
        actual=$(grep -E "^(# )?${key}[ =]" .config || echo '不存在')
        printf '  [FAIL] %-45s %s  <-- 实际: %s\n' "$key" "$desc" "$actual"
        _vc_fail=1
    fi
}

_check_warn() {
    local key="$1" desc="${2:-}"
    if grep -qE "^${key}=(y|m)$" .config; then
        printf '  [OK]   %-45s %s\n' "$key" "$desc"
    else
        printf '  [WARN] %-45s %s  <-- 未启用(该内核版本可能不支持)\n' "$key" "$desc"
    fi
}

_check_str() {
    local key="$1" want="$2"
    if grep -qE "^${key}=\"${want}\"$" .config; then
        printf '  [OK]   %-45s = "%s"\n' "$key" "$want"
    else
        local actual
        actual=$(grep -E "^${key}=" .config || echo '不存在')
        printf '  [FAIL] %-45s 期望 "%s"  <-- 实际: %s\n' "$key" "$want" "$actual"
        _vc_fail=1
    fi
}

# 只告警版：适用于「设不上也能靠运行时兜底」的派生字符串(如默认 qdisc)。
_check_str_warn() {
    local key="$1" want="$2" note="${3:-}"
    if grep -qE "^${key}=\"${want}\"$" .config; then
        printf '  [OK]   %-45s = "%s"\n' "$key" "$want"
    else
        local actual
        actual=$(grep -E "^${key}=" .config || echo '未设置')
        printf '  [WARN] %-45s 期望 "%s"  <-- 实际: %s  %s\n' "$key" "$want" "$actual" "$note"
    fi
}

verify_config() {
    local distro="${1:?需要指定发行版: centos|debian}"

    [ -f .config ] || { echo "错误: 当前目录没有 .config，verify 必须在内核源码目录执行"; exit 1; }

    echo "=================================================="
    echo " 内核配置校验 (${distro})"
    echo "=================================================="

    echo
    echo "--- 关键项：缺失即判定构建失败 ---"
    # 能不能开机
    _check_critical CONFIG_EXT4_FS               "根文件系统"
    _check_critical CONFIG_VIRTIO_BLK            "KVM 云主机磁盘"
    _check_critical CONFIG_VIRTIO_NET            "KVM 云主机网卡"
    _check_critical CONFIG_VIRTIO_PCI            "virtio 总线"
    _check_critical CONFIG_SCSI_VIRTIO           "virtio-scsi 磁盘"
    _check_critical CONFIG_BLK_DEV_NVME          "AWS Nitro / NVMe 启动盘"
    _check_critical CONFIG_SERIAL_8250_CONSOLE   "串口控制台(救援刚需)"
    # 网络核心（release 名字里带 _bbr，缺了就是虚假宣传）
    _check_critical CONFIG_TCP_CONG_BBR          "BBR 拥塞控制"
    _check_critical CONFIG_NET_SCH_FQ            "FQ 队列"
    _check_str      CONFIG_DEFAULT_TCP_CONG      "bbr"
    # 默认 qdisc 设不上也能靠 sysctl net.core.default_qdisc=fq 兜底，且 BBR 不挑 qdisc，
    # 故降为告警不阻断构建。
    _check_str_warn CONFIG_DEFAULT_NET_SCH       "fq"  "(可用 sysctl net.core.default_qdisc=fq 兜底)"
    _check_critical CONFIG_TUN                   "TUN/TAP 隧道"
    _check_critical CONFIG_IPV6                  "IPv6 协议栈"
    # 防火墙
    _check_critical CONFIG_NF_TABLES             "nftables(firewalld/UFW 依赖)"
    _check_critical CONFIG_IP_NF_IPTABLES        "iptables 框架"
    _check_critical CONFIG_NETFILTER_XT_TARGET_MASQUERADE "Docker 端口映射"
    # 容器与 systemd
    _check_critical CONFIG_OVERLAY_FS            "Docker 存储驱动"
    _check_critical CONFIG_NAMESPACES            "容器命名空间"
    _check_critical CONFIG_CGROUPS               "cgroup 资源隔离"
    _check_critical CONFIG_BRIDGE                "Docker/PVE 网桥"
    _check_critical CONFIG_VETH                  "容器虚拟网卡对"
    _check_critical CONFIG_SECCOMP               "systemd 沙盒"
    # 瘦身是否真的生效
    _check_critical CONFIG_DEBUG_INFO_NONE       "确认未生成调试符号"
    # 模块压缩：唯一的【硬性】要求是「绝不能是 ZSTD」——.ko.zst 需要目标系统 kmod>=29，
    # 而 Debian10/11、EL8 等 kmod<29 会「能开机但所有外挂模块静默加载失败」。
    # XZ 最佳(压缩且兼容)；若因该内核 Kconfig 依赖导致回退成 NONE(未压缩)，同样兼容，
    # 只是模块体积偏大，可接受，故仅告警。
    if grep -q '^CONFIG_MODULE_COMPRESS_ZSTD=y' .config; then
        printf '  [FAIL] %-45s %s\n' "CONFIG_MODULE_COMPRESS_ZSTD" "选中了 ZSTD —— kmod<29 系统模块加载会全部失败！"
        _vc_fail=1
    elif grep -q '^CONFIG_MODULE_COMPRESS_XZ=y' .config; then
        printf '  [OK]   %-45s %s\n' "CONFIG_MODULE_COMPRESS_XZ" "模块 XZ 压缩(兼容 kmod<29)"
    else
        # 诊断：区分「XZ 可选但没选中(scripts/config 问题)」还是「XZ 符号不存在(依赖/host 工具缺失被 gate)」
        # 注意：grep 无匹配会返回非零，脚本顶部 set -e 会因此中断，务必用 || true 兜住。
        local mc xzstate
        mc=$(grep -E '^CONFIG_MODULE_COMPRESS_[A-Z]+=y' .config 2>/dev/null | tr '\n' ' ' || true)
        xzstate=$(grep -E 'CONFIG_MODULE_COMPRESS_XZ' .config 2>/dev/null || echo 'XZ 符号完全不存在(被 Kconfig 依赖 gate 掉)')
        printf '  [WARN] %-45s 实际: %s| XZ: %s\n' "模块压缩(非 XZ，兼容但偏大)" "${mc:-NONE }" "$xzstate"
    fi

    # 发行版安全链
    case "$distro" in
        centos)
            _check_critical CONFIG_SECURITY_SELINUX  "SELinux(RHEL 系刚需)"
            ;;
        debian)
            _check_critical CONFIG_SECURITY_APPARMOR "AppArmor(Debian 系刚需)"
            ;;
        *)
            echo "错误: 未知发行版 '$distro'"; exit 1 ;;
    esac

    echo
    echo "--- 增强项：缺失只告警，不阻断 ---"
    _check_warn CONFIG_WIREGUARD          "WireGuard"
    _check_warn CONFIG_HYPERV             "Hyper-V/Azure 支持"
    _check_warn CONFIG_HYPERV_STORAGE     "Azure 磁盘(storvsc)"
    _check_warn CONFIG_HYPERV_NET         "Azure 网卡(netvsc)"
    _check_warn CONFIG_MLX5_CORE          "Mellanox CX-4/5/6 网卡"
    _check_warn CONFIG_IXGBEVF            "SR-IOV VF 网卡(ixgbevf)"
    _check_warn CONFIG_IAVF               "SR-IOV VF 网卡(i40e/ice)"
    _check_warn CONFIG_BPF_JIT            "eBPF JIT 加速"
    _check_warn CONFIG_BRIDGE_VLAN_FILTERING "PVE VLAN 感知网桥"
    _check_warn CONFIG_NFSD               "NFS 服务端(NAS 对外共享)"
    _check_warn CONFIG_KSM                "KSM 同页合并(PVE 省内存)"
    _check_warn CONFIG_I6300ESB_WDT       "QEMU 看门狗(HA/卡死重启)"
    _check_warn CONFIG_VIRTIO_BALLOON     "KVM 内存气球"
    _check_warn CONFIG_KVM                "KVM 宿主(PVE)"
    _check_warn CONFIG_VFIO_PCI           "PCI 直通(PVE)"
    _check_warn CONFIG_INTEL_IOMMU        "Intel IOMMU"
    _check_warn CONFIG_AMD_IOMMU          "AMD IOMMU"
    _check_warn CONFIG_OPENVSWITCH        "OVS 虚拟交换机(PVE)"
    _check_warn CONFIG_ZRAM               "ZRAM 内存压缩"
    _check_warn CONFIG_ZSWAP              "ZSWAP"
    _check_warn CONFIG_IO_URING           "io_uring 异步 IO"
    _check_warn CONFIG_TLS                "内核级 TLS"
    _check_warn CONFIG_MPTCP              "多路径 TCP"
    _check_warn CONFIG_NET_VRF            "VRF 路由隔离"
    _check_warn CONFIG_LRU_GEN            "MGLRU"
    _check_warn CONFIG_DAMON              "DAMON 内存回收"
    _check_warn CONFIG_LIVEPATCH          "内核热补丁"
    _check_warn CONFIG_SECURITY_LANDLOCK  "Landlock 沙盒"
    _check_warn CONFIG_BPF_LSM            "BPF LSM"
    _check_warn CONFIG_NTFS3_FS           "NTFS3"
    _check_warn CONFIG_EXFAT_FS           "exFAT"
    _check_warn CONFIG_NET_SCH_CAKE       "CAKE 队列"
    _check_warn CONFIG_XFS_QUOTA          "XFS 配额"
    _check_warn CONFIG_NF_CONNTRACK_FTP   "FTP 被动模式穿透"
    _check_warn CONFIG_IO_URING_ZCRX      "io_uring 零拷贝"
    _check_warn CONFIG_TCP_AO             "TCP 认证选项"

    echo
    echo "--- LSM 安全链实际值 ---"
    grep -E '^CONFIG_LSM=' .config || echo "  (未设置 CONFIG_LSM)"

    echo
    if [ "$_vc_fail" -ne 0 ]; then
        echo "=================================================="
        echo " 校验失败：上面标记 [FAIL] 的关键配置未生效。"
        echo " 这通常是 olddefconfig 因依赖不满足而静默丢弃了该选项。"
        echo "=================================================="
        exit 1
    fi
    echo "=================================================="
    echo " 校验通过：全部关键配置均已生效。"
    echo "=================================================="
}

# ------------------------------------------------------------------
# 入口
# ------------------------------------------------------------------
case "${1:-}" in
    apply)  apply_common_config ;;
    verify) shift; verify_config "${1:-}" ;;
    *)
        echo "用法: bash $0 apply"
        echo "      bash $0 verify <centos|debian>"
        exit 1
        ;;
esac
