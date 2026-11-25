#!/bin/sh
# S4, part 1: checks that do not drive any pin or touch the PL. Run ON the EBAZ with sudo:
#   sudo sh ~/sadiy/tools/ebaz_s4_readonly.sh > /tmp/s4_readonly.txt 2>&1
# What it does:
#   - gpiodetect / gpioinfo of the EMIO lines (54..69): names, direction, consumers
#   - PS GPIO registers read with devmem (DIRM_2, OEN_2, DATA_2_RO = EMIO lines 54..85): direction and pad level
#   - gpioget of the EMIO lines 54..61: reads the pad levels. This requests the lines as INPUT, which they
#     already are after boot (output enable is 0), so nothing changes. 54..59 are spare lines (the PE4302 lines
#     until 2026-11-25; with nothing wired their level means nothing), LD (61) = 0 with no synthesiser attached.
#   - i2cdetect on bus 0: probes 0x03..0x77. The PCF8574 (attenuator) should show at 0x27 if it is wired.
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
echo "bit n of these = EMIO line 54+n: n=0..5 spare (PE4302 V1..V6 until 2026-11-25), 6 ADF4351 CE, 7 ADF4351 LD"
hdr "pad levels, EMIO 54..61 (input reads)"
if gpioget --help 2>&1 | grep -q -- '--chip'; then
  gpioget --chip "$chip" 54 55 56 57 58 59 60 61 2>&1
else
  gpioget -c "$chip" 54 55 56 57 58 59 60 61 2>&1
fi
echo "order: spare0(54) spare1(55) spare2(56) spare3(57) spare4(58) spare5(59) CE(60) LD(61)"
hdr "i2cdetect bus 0"
i2cdetect -l
i2cdetect -y -r 0      # -r: the Cadence controller has no SMBus Quick Write
hdr "device nodes"
ls -l /dev/spidev* /dev/i2c-* /dev/gpiochip* 2>&1
hdr "done"
