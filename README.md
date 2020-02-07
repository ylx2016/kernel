# kernel
```
linux kernel for bbr/bbrplus

见
https://github.com/ylx2016/kernel/releases

一键安装内核见
https://github.com/ylx2016/Linux-NetSpeed/releases

c6-c8 = centos6-centos8
d9-d10=debian9-debian10
u16-u19=ubuntu16-19

激活bbrplus
echo "net.ipv4.tcp_congestion_control=bbrplus" >> /etc/sysctl.conf
sysctl -p

bbsplus算法原作者
https://blog.csdn.net/dog250/article/details/80629551
bbrplus首用名 ？
https://github.com/cx9208/bbrplus


查看当前运行的算法
cat /proc/sys/net/ipv4/tcp_congestion_control

lsmod | grep bbr 这个在内置默认bbr算法的情况下是不会有输出的

