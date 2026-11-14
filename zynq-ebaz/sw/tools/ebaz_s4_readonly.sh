#!/bin/sh
# S4, part 1: checks that do not drive any pin or touch the PL. Run ON the EBAZ with sudo:
#   sudo sh ~/sadiy/tools/ebaz_s4_readonly.sh > /tmp/s4_readonly.txt 2>&1
# What it does:
#   - gpiodetect / gpioinfo of the EMIO lines (54..69): names, direction, consumers
#   - PS GPIO registers read with devmem (DIRM_2, OEN_2, DATA_2_RO = EMIO lines 54..85): direction and pad level
#   - gpioget of the EMIO lines 54..61: reads the pad levels. This requests the lines as INPUT, which they
#     already are after boot (output enable is 0), so nothing changes. Expect PE4302 V1..V6 (54..59) = 1
#     when the adapter pull-ups are fitted, LD (61) = 0 with no synthesiser attached.
#   - i2cdetect on bus 0: probes 0x03..0x77. The ADS1115 should show at 0x48 if it is wired.
# What it must NOT do: read or write 0x43C00000. The Phase 1 bitstream has no AXI slave there and the access
# would stall the CPU.
chip=gpiochip0
have() { command -v "$1" >/dev/null 2>&1; }
hdr() { printf '\n== %s\n' "$1"; }

hdr "date, kernel"; date; uname -r
hdr "gpiodetect"; gpiodetect
hdr "gpioinfo EMIO lines 54..69 (Linux offset = 54 + n)"
gpioinfo "$chip" 2>&1 | awk '/line +(5[4-9]|6[0-9]):/'
hdr "PS GPIO registers (bank 2 = EMIO 54..85)"
for r in "DIRM_2 0xE000A284" "OEN_2 0xE000A288" "DATA_2_RO 0xE000A068"; do
  set -- $r; printf '%-10s %s = ' "$1" "$2"; devmem "$2" 32
done
echo "bit n of these = EMIO line 54+n: n=0..5 PE4302 V1..V6, 6 ADF4351 CE, 7 ADF4351 LD"
hdr "pad levels, EMIO 54..61 (input reads)"
if gpioget --help 2>&1 | grep -q -- '--chip'; then
  gpioget --chip "$chip" 54 55 56 57 58 59 60 61 2>&1
else
  gpioget -c "$chip" 54 55 56 57 58 59 60 61 2>&1
fi
echo "order: V1(54) V2(55) V3(56) V4(57) V5(58) V6(59) CE(60) LD(61)"
hdr "i2cdetect bus 0"
i2cdetect -l
i2cdetect -y 0
hdr "device nodes"
ls -l /dev/spidev* /dev/i2c-* /dev/gpiochip* 2>&1
hdr "done"
