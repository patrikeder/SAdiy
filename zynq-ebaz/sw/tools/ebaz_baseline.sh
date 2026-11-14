#!/bin/sh
# S1: capture a baseline of the EBAZ4205 Linux image. Runs ON the board (busybox sh
# is enough) and prints markdown to stdout. Reads only; installs nothing.
#
#   ssh root@<ebaz-ip> sh -s < zynq-ebaz/sw/tools/ebaz_baseline.sh > zynq-ebaz/docs/ebaz-baseline.md
#
# Every check prints its result, a missing tool is reported, never an error.

have() { command -v "$1" >/dev/null 2>&1; }
sec() { printf '\n## %s\n\n' "$1"; }
blk() { printf '```\n'; cat; printf '```\n'; }

printf '# EBAZ4205 Linux baseline\n\n'
printf 'Captured: %s (board clock, may be wrong without NTP)\n' "$(date 2>/dev/null)"

sec "System"
{
  echo "hostname:  $(hostname 2>/dev/null)"
  echo "kernel:    $(uname -a 2>/dev/null)"
  echo "os:        $( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME $VERSION_ID") )"
  echo "cmdline:   $(cat /proc/cmdline 2>/dev/null)"
  echo "uptime:    $(uptime 2>/dev/null)"
  grep -E 'model name|Hardware|Revision' /proc/cpuinfo 2>/dev/null | sort -u
  echo "cpus:      $(grep -c '^processor' /proc/cpuinfo 2>/dev/null)"
  grep -E 'MemTotal|MemFree|MemAvailable' /proc/meminfo 2>/dev/null
} | blk

sec "Network"
{
  if have ip; then ip -4 addr show 2>/dev/null | grep -E 'inet |^[0-9]'; else ifconfig 2>/dev/null; fi
  have ethtool && ethtool eth0 2>/dev/null | grep -E 'Speed|Duplex|Link detected'
} | blk

sec "Boot media and storage"
{
  echo "root: $(awk '$2=="/"{print $1, $3}' /proc/mounts | tail -1)"
  have lsblk && lsblk 2>/dev/null
  cat /proc/mtd 2>/dev/null | sed 's/^/mtd: /'
  df -h 2>/dev/null | grep -vE 'tmpfs|devtmpfs'
  dmesg 2>/dev/null | grep -iE 'mmcblk|mmc0.*(new|card)' | head -5
} | blk

sec "FPGA"
{
  for d in /sys/class/fpga_manager/*; do
    [ -e "$d" ] || continue
    echo "$d: name=$(cat $d/name 2>/dev/null) state=$(cat $d/state 2>/dev/null)"
  done
  [ -d /sys/class/fpga_manager ] || echo "no /sys/class/fpga_manager"
  ls -d /sys/kernel/config/device-tree/overlays 2>/dev/null || echo "no configfs device-tree overlays dir (try: mount -t configfs none /sys/kernel/config)"
  ls /lib/firmware 2>/dev/null | head -20 | sed 's/^/firmware: /'
  ls -d /sys/class/uio/uio* 2>/dev/null || echo "no UIO devices"
} | blk

sec "Device nodes (SPI, I2C, GPIO)"
{
  ls -l /dev/spidev* 2>/dev/null || echo "no /dev/spidev*"
  ls -l /dev/i2c-* 2>/dev/null || echo "no /dev/i2c-*"
  ls -l /dev/gpiochip* 2>/dev/null || echo "no /dev/gpiochip*"
  for c in /sys/class/gpio/gpiochip*; do
    [ -e "$c" ] || continue
    echo "$c: label=$(cat $c/label 2>/dev/null) base=$(cat $c/base 2>/dev/null) ngpio=$(cat $c/ngpio 2>/dev/null)"
  done
  for b in /sys/class/spi_master/*; do [ -e "$b" ] && echo "spi master: $b -> $(readlink -f $b)"; done
  for i in /sys/class/i2c-adapter/*; do [ -e "$i" ] && echo "i2c adapter: $i name=$(cat $i/name 2>/dev/null)"; done
} | blk

sec "Tools"
{
  for t in python3 i2cdetect i2cget i2cset gpiodetect gpioset gpioget gpioinfo devmem devmem2 peekpoke spidev_test strace tcpdump systemctl sshd; do
    if have $t; then echo "$t: $(command -v $t)"; else echo "$t: MISSING"; fi
  done
  have python3 && python3 --version 2>&1
} | blk

sec "Python modules"
{
  if have python3; then
    for m in zmq numpy spidev gpiod smbus smbus2 fcntl mmap tomllib json logging asyncio ctypes unittest; do
      if python3 -c "import $m" 2>/dev/null; then
        v=$(python3 -c "import $m; print(getattr($m,'__version__',''))" 2>/dev/null)
        echo "$m: ok $v"
      else
        echo "$m: MISSING"
      fi
    done
  else
    echo "python3 not installed"
  fi
} | blk

sec "Kernel messages (SPI, I2C, GPIO, FPGA, eth)"
dmesg 2>/dev/null | grep -iE 'spi|i2c|gpio|fpga|macb|gem|phy|uio' | head -40 | blk

sec "Loaded modules"
(lsmod 2>/dev/null || echo "no lsmod") | head -30 | blk
