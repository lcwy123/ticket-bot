#!/bin/bash
# 闲鱼APP客户端 - 内网穿透设置脚本
# 用于在阿里云服务器上设置frp内网穿透，使服务器可以访问手机上的闲鱼APP

set -e

echo "=== 闲鱼APP内网穿透设置 ==="

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 配置
FRP_VERSION="0.51.0"
FRP_DIR="/opt/frp"
SERVER_PORT=7000
ADB_PORT=5555

# 检查是否为root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}请使用sudo运行此脚本${NC}"
    exit 1
fi

# 检查系统
if [ ! -f /etc/os-release ]; then
    echo -e "${RED}无法确定操作系统${NC}"
    exit 1
fi

install_frp_server() {
    echo -e "${YELLOW}安装FRP服务端...${NC}"

    # 下载FRP
    cd /tmp
    if [ ! -f "frp_${FRP_VERSION}_linux_amd64.tar.gz" ]; then
        wget -q "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz" || {
            echo -e "${RED}下载FRP失败${NC}"
            exit 1
        }
    fi

    # 解压安装
    mkdir -p ${FRP_DIR}
    tar -xzf "frp_${FRP_VERSION}_linux_amd64.tar.gz" -C ${FRP_DIR} --strip-components=1

    # 创建frps配置文件
    cat > ${FRP_DIR}/frps.ini << 'EOF'
[common]
bind_port = 7000
# 为了安全，可以设置token
token = your_secure_token_here

# ADB端口映射
[adb]
type = tcp
local_ip = 127.0.0.1
local_port = 5555
remote_port = 5555
EOF

    echo -e "${GREEN}FRP服务端已安装到 ${FRP_DIR}${NC}"
}

install_frpc_android() {
    echo -e "${YELLOW}手机端FRP客户端设置说明:${NC}"
    echo ""
    echo "在手机上安装FRP客户端(推荐使用 https://github.com/HBTaleb/frp) "
    echo "并配置以下内容:"
    echo ""
    cat << 'EOF'
[common]
server_addr = your_server_ip
server_port = 7000
token = your_secure_token_here

[adb]
type = tcp
local_ip = 127.0.0.1
local_port = 5555
remote_port = 5555
EOF
    echo ""
    echo -e "${YELLOW}或者使用 Termux 安装frpc:${NC}"
    echo "pkg install frpc"
}

start_frp_server() {
    echo -e "${YELLOW}启动FRP服务端...${NC}"

    # 创建systemd服务
    cat > /etc/systemd/system/frps.service << 'EOF'
[Unit]
Description=FRP Server
After=network.target

[Service]
Type=simple
ExecStart=${FRP_DIR}/frps -c ${FRP_DIR}/frps.ini
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable frps
    systemctl start frps

    echo -e "${GREEN}FRP服务端已启动${NC}"
    echo "查看状态: systemctl status frps"
    echo "查看日志: journalctl -u frps -f"
}

check_adb() {
    echo -e "${YELLOW}检查ADB环境...${NC}"

    if command -v adb &> /dev/null; then
        ADB_VERSION=$(adb version | head -1)
        echo -e "${GREEN}ADB已安装: ${ADB_VERSION}${NC}"
    else
        echo -e "${YELLOW}ADB未安装，正在安装...${NC}"
        if command -v apt-get &> /dev/null; then
            apt-get update && apt-get install -y android-tools-adb
        elif command -v yum &> /dev/null; then
            yum install -y android-tools
        fi
    fi
}

connect_to_phone() {
    echo -e "${YELLOW}尝试连接到手机...${NC}"
    echo ""

    # 列出已连接设备
    echo "已连接的设备:"
    adb devices

    echo ""
    echo -e "${YELLOW}如果手机未连接，请确保:${NC}"
    echo "1. 手机已开启USB调试"
    echo "2. 手机已运行frpc并成功连接"
    echo "3. 服务器防火墙已开放 5555 端口"
    echo ""
    echo "连接命令: adb connect 127.0.0.1:5555"
}

# 主流程
echo ""
echo "请选择操作:"
echo "1. 安装FRP服务端 (在服务器上运行一次)"
echo "2. 启动FRP服务端"
echo "3. 检查ADB"
echo "4. 连接手机"
echo "5. 全部执行"
echo ""

read -p "请输入选项 [1-5]: " choice

case $choice in
    1)
        install_frp_server
        install_frpc_android
        ;;
    2)
        start_frp_server
        ;;
    3)
        check_adb
        ;;
    4)
        connect_to_phone
        ;;
    5)
        install_frp_server
        install_frpc_android
        start_frp_server
        check_adb
        connect_to_phone
        ;;
    *)
        echo -e "${RED}无效选项${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}设置完成!${NC}"
