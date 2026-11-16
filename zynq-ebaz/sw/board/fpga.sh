#!/bin/sh
# Load the SAdiy engine bitstream into the PL (if needed) and say what is in there. Run from ~/sadiy on the EBAZ4205.
#   ./fpga.sh            show the PL; load the bitstream only if the PL has none or the wrong one
#   ./fpga.sh --force    load it again (a sweep or bench run that was killed hard, or a new bitstream)
#   ./fpga.sh status     only show, never load
# The bitstream is fpga/ebaz_sadiy.bit.bin (put there by deploy_to_board.sh; BITSTREAM=<file> for another one).
# Loading restarts the network interface for a few seconds (the Ethernet PHY clock goes through the PL): an ssh
# session may stall; run `sudo udhcpc -i <interface>` if the address does not come back. A bitstream loaded here is
# gone after a reboot unless the SD card's BOOT.BIN holds the same one.
. "$(dirname "$0")/common.sh"
cd "$SADIY_HOME" || exit 1
banner
case "${1:-}" in
    status) probe; exit $? ;;
    --force) ;;
    "") probe && exit 0 ;;
    *) echo "usage: ./fpga.sh [status|--force]" >&2; exit 2 ;;
esac
[ -f "$BITSTREAM" ] || die "no bitstream at $BITSTREAM (deploy with the bitstream: BITSTREAM=<ebaz_sadiy.bit.bin> sh zynq-ebaz/sw/deploy/deploy_to_board.sh <ip>)"
echo "loading $BITSTREAM ($(ls -l "$BITSTREAM" | awk '{print $5}') bytes)"
as_root sh "$SADIY_HOME/fpga/sadiy_pl_load.sh" "$BITSTREAM" || die "loading failed"
probe
