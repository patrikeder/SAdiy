# EBAZ4205 Linux baseline

Captured: Sat Nov 14 16:28:57 PST 2026 (board clock, may be wrong without NTP)

## System

```
hostname:  ebaz4205_sadiy
kernel:    Linux ebaz4205_sadiy 6.12.40-xilinx-g31626ef92ff1 #1 SMP PREEMPT Fri Nov  7 15:28:23 UTC 2025 armv7l GNU/Linux
os:        
cmdline:   console=ttyPS0,115200 earlycon root=/dev/mmcblk0p2 ro rootwait
uptime:     16:28:57 up 8 min,  2 users,  load average: 0.00, 0.04, 0.05
Hardware	: Xilinx Zynq Platform
Revision	: 0003
model name	: ARMv7 Processor rev 0 (v7l)
cpus:      2
MemTotal:         248528 kB
MemFree:          201224 kB
MemAvailable:     220860 kB
```

## Network

```
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    inet 127.0.0.1/8 scope host lo
2: enx000a35001e53: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP group default qlen 1000
    inet 192.168.88.244/24 brd 192.168.88.255 scope global enx000a35001e53
```

## Boot media and storage

```
root: /dev/root ext4
NAME        MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
mmcblk0     179:0    0 14.8G  0 disk 
|-mmcblk0p1 179:1    0    2G  0 part /boot
|                                    /boot
`-mmcblk0p2 179:2    0    4G  0 part /
mtd: dev:    size   erasesize  name
Filesystem      Size  Used Avail Use% Mounted on
/dev/root       3.8G  427M  3.2G  12% /
/dev/mmcblk0p1  2.0G  7.9M  2.0G   1% /boot
[    0.000000] Kernel command line: console=ttyPS0,115200 earlycon root=/dev/mmcblk0p2 ro rootwait
[    0.950463] mmc0: new high speed SDHC card at address aaaa
[    0.955628] mmcblk0: mmc0:aaaa SU16G 14.8 GiB
[    0.962038]  mmcblk0: p1 p2
[    1.159482] EXT4-fs (mmcblk0p2): orphan cleanup on readonly fs
```

## FPGA

```
/sys/class/fpga_manager/fpga0: name=Xilinx Zynq FPGA Manager state=operating
/sys/kernel/config/device-tree/overlays
no UIO devices
```

## Device nodes (SPI, I2C, GPIO)

```
crw------- 1 root root 153, 0 Dec 31  1969 /dev/spidev0.0
crw------- 1 root root 89, 0 Dec 31  1969 /dev/i2c-0
crw------- 1 root root 254, 0 Dec 31  1969 /dev/gpiochip0
/sys/class/gpio/gpiochip512: label=zynq_gpio base=512 ngpio=118
spi master: /sys/class/spi_master/spi0 -> /sys/devices/soc0/axi/e0006000.spi/spi_master/spi0
```

## Tools

```
python3: /usr/bin/python3
i2cdetect: /usr/sbin/i2cdetect
i2cget: /usr/sbin/i2cget
i2cset: /usr/sbin/i2cset
gpiodetect: /usr/bin/gpiodetect
gpioset: /usr/bin/gpioset
gpioget: /usr/bin/gpioget
gpioinfo: /usr/bin/gpioinfo
devmem: /sbin/devmem
devmem2: MISSING
peekpoke: MISSING
spidev_test: MISSING
strace: MISSING
tcpdump: MISSING
systemctl: MISSING
sshd: /usr/sbin/sshd
Python 3.12.11
```

## Python modules

```
zmq: ok 25.1.2
numpy: ok 1.26.4
spidev: ok 3.6
gpiod: MISSING
smbus: MISSING
smbus2: MISSING
fcntl: ok 
mmap: ok 
tomllib: ok 
json: ok 2.0.9
logging: ok 0.5.1.2
asyncio: ok 
ctypes: ok 1.1.0
unittest: ok 
```

## Kernel messages (SPI, I2C, GPIO, FPGA, eth)

```
[    0.000000] Booting Linux on physical CPU 0x0
[    0.347022] FPGA manager framework
[    0.792708] macb e000b000.ethernet eth0: Cadence GEM rev 0x00020118 at 0xe000b000 irq 38 (00:0a:35:00:1e:53)
[    0.802593] i2c_dev: i2c /dev entries driver
[    0.805702] cdns-i2c e0004000.i2c: can't get pinctrl, bus recovery not supported
[    0.812499] cdns-i2c e0004000.i2c: 100 kHz mmio e0004000 irq 39
[    0.855181] SPI driver fb_st7789v has no spi_device_id for sitronix,st7789v
[    0.880292] fpga_manager fpga0: Xilinx Zynq FPGA Manager registered
[    0.962373] of-fpga-region fpga-region: FPGA Region probed
[    4.876597] macb e000b000.ethernet enx000a35001e53: renamed from eth0
[    9.418168] macb e000b000.ethernet enx000a35001e53: PHY [e000b000.ethernet-ffffffff:00] driver [ICPlus IP101G] (irq=POLL)
[    9.418208] macb e000b000.ethernet enx000a35001e53: configuring for phy/mii link mode
[   12.510354] macb e000b000.ethernet enx000a35001e53: Link is Up - 100Mbps/Full - flow control off
```

## Loaded modules

```
Module                  Size  Used by
uio_pdrv_genirq        12288  0
```
