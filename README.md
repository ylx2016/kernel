# kernel
linux kernel for bbr/bbrplus

见
https://github.com/ylx2016/kernel/releases

c6-c8 = centos6-centos8
d9-d10=debian9-debian10
激活bbrplus
echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
sysctl -p
