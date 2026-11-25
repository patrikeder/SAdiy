#!/bin/sh
# S4, part 2: EMIO readback test. Drives each of the 7 EMIO output lines (n = 0..6, Linux offset 54 + n)
# high and low through sysfs GPIO (the same path hal/linux.py uses) and reads the level back from the PS GPIO
# data register (DATA_2_RO, 0xE000A068). The readback passes through the IOBUF in the PL, so a PASS shows:
#   - line number mapping 54 + n <-> bit n,   - the PL pin buffers follow the PS output enable and data.
# It does NOT show that the pad sits on the right DATA2 pin: that needs a DMM or the DSLogic at the connector.
#
#   sudo sh ~/sadiy/tools/ebaz_s4_readback.sh > /tmp/s4_readback.txt 2>&1
#
# Pins are driven for a few milliseconds each and are returned to input (high impedance) at the end, also on Ctrl-C.
# n = 0..5 are spare EMIO GPIO since 2026-11-25 (they were the PE4302 lines V1..V6).
# Run it with the adapter DISCONNECTED. With old attenuator wires connected this would drive those lines, with the
# ADF4351 connected CE would drop low briefly. LD (n = 7) is an input in the design: read only.
# Never touches 0x43C00000.
BASE=512                 # sysfs base of zynq_gpio (see ebaz-baseline.md)
EMIO0=54
DATA_RO=0xE000A068
DIRM=0xE000A284
OEN=0xE000A288
names="spare0 spare1 spare2 spare3 spare4 spare5 CE"
fail=0

release() {
  for n in 0 1 2 3 4 5 6; do
    g=$((BASE + EMIO0 + n))
    [ -d /sys/class/gpio/gpio$g ] && { echo in > /sys/class/gpio/gpio$g/direction 2>/dev/null; echo $g > /sys/class/gpio/unexport 2>/dev/null; }
  done
}
trap release EXIT INT TERM

bit() { v=$(devmem $DATA_RO 32); echo $(( (v >> $1) & 1 )); }

echo "start: DIRM_2=$(devmem $DIRM 32) OEN_2=$(devmem $OEN 32) DATA_2_RO=$(devmem $DATA_RO 32)"
echo "(floating pads: the start level of the spare lines and CE is arbitrary with nothing connected)"
n=0
for name in $names; do
  g=$((BASE + EMIO0 + n))
  echo $g > /sys/class/gpio/export 2>/dev/null
  if [ ! -d /sys/class/gpio/gpio$g ]; then echo "n=$n $name: cannot export gpio$g"; fail=$((fail+1)); n=$((n+1)); continue; fi
  res=""
  for val in high low; do
    want=$([ $val = high ] && echo 1 || echo 0)
    echo $val > /sys/class/gpio/gpio$g/direction
    got=$(bit $n)
    sysv=$(cat /sys/class/gpio/gpio$g/value)
    oen=$(( ($(devmem $OEN 32) >> n) & 1 ))
    dirm=$(( ($(devmem $DIRM 32) >> n) & 1 ))
    ok=PASS; [ "$got" = "$want" ] && [ "$sysv" = "$want" ] && [ $oen = 1 ] && [ $dirm = 1 ] || { ok=FAIL; fail=$((fail+1)); }
    res="$res $val:pad=$got,sysfs=$sysv,dirm=$dirm,oen=$oen $ok;"
  done
  echo in > /sys/class/gpio/gpio$g/direction
  echo $g > /sys/class/gpio/unexport
  echo "n=$n gpio$g $name:$res"
  n=$((n+1))
done
echo "LD (n=7, input only): pad=$(bit 7) (expect 0: pull-down in the XDC, nothing connected)"
echo "end:   DIRM_2=$(devmem $DIRM 32) OEN_2=$(devmem $OEN 32) (expect bits 0..6 back to 0)"
echo "RESULT: $([ $fail = 0 ] && echo ALL PASS || echo "$fail FAILED")"
