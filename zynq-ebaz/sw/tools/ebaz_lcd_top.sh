#!/bin/sh
# Show `top` on the adapter LCD (console tty1) instead of a login prompt. Runs ON THE EBAZ4205 (sysvinit image).
#
#   sudo sh ebaz_lcd_top.sh install   put this script in /usr/local/bin and let init run it on tty1 instead of getty
#   sudo sh ebaz_lcd_top.sh remove    give tty1 its login prompt back
#   sh ebaz_lcd_top.sh status         what is installed, the console size, whether it is running
#   sh ebaz_lcd_top.sh frame          one frame on stdout (a dry test, needs no LCD; LCD_TOP_SIZE=30,15 to choose the size)
#   ebaz_lcd_top run                  what init starts (do not call by hand unless tty1 is free)
#
# Why a wrapper: the LCD is a 240x240 panel, so the text console has only about 30 columns (15 rows with the
# 8x16 font, 30 with 8x8) and no keyboard is attached. `top` itself would cut off %CPU and the command name at
# 30 columns, so the wrapper runs `top -b`, takes its last frame (the first one only has averages since the start
# of each process) and prints a compact version that fits: time and load, tasks, CPU, memory, then PID %CPU
# %MEM COMMAND for as many processes as there are rows.
#
# The root file system is mounted read-only: `install` and `remove` remount it read-write for a moment and
# back (the inittab is a file on the SD card, so the change survives reboots). The original inittab is kept as
# /etc/inittab.sadiy-orig. The serial console login on ttyPS0 is not touched.
#
# Environment (all optional): LCD_TOP_TTY (/dev/tty1), LCD_TOP_DELAY seconds between frames (2),
# LCD_TOP_SIZE cols,rows, TOP (the top command), INITTAB, DEST, SKIP_SYSTEM=1 (tests: no mount, telinit, kill).
TTY=${LCD_TOP_TTY:-/dev/tty1}
DELAY=${LCD_TOP_DELAY:-2}
TOP=${TOP:-top}
INITTAB=${INITTAB:-/etc/inittab}
DEST=${DEST:-/usr/local/bin/ebaz_lcd_top}
SELF=$0
MINE="1:12345:respawn:$DEST run"
GETTY="1:12345:respawn:/sbin/getty 38400 tty1"

die() { echo "ebaz_lcd_top: $*" >&2; exit 1; }

size() {        # "cols rows" of the console
    if [ -n "$LCD_TOP_SIZE" ]; then echo "${LCD_TOP_SIZE%,*} ${LCD_TOP_SIZE#*,}"; return; fi
    if s=$(stty size <"$TTY" 2>/dev/null) && [ -n "$s" ]; then set -- $s; echo "$2 $1"; return; fi
    echo "30 15"
}

# top -b output on stdin, last frame only, compact. $1 cols, $2 rows, $3 end-of-line sequence.
compact() {
    awk -v cols="$1" -v rows="$2" -v eol="$3" '
    /^top - / { n = 0 }
    { line[++n] = $0 }
    function num(s) { return s + 0 }
    function field_before(word,    j) {
        for (j = 2; j <= NF; j++) if ($j == word) return $(j - 1)
        return "?"
    }
    function out(s) {
        s = substr(s, 1, cols) eol
        text = (text == "" && nout == 0) ? s : text "\n" s
        nout++
    }
    END {
        nout = 0; text = ""
        pid = cpu = mem = cmd = 0
        for (i = 1; i <= n; i++) {
            l = line[i]
            gsub(/,/, " ", l)
            $0 = l
            if (l ~ /^top - /) {
                k = index(l, "load average:")
                ld = (k ? substr(l, k + 13) : "")
                gsub(/^ +| +$/, "", ld); gsub(/  +/, " ", ld)
                out(sprintf("%s ld %s", $3, ld))
            } else if (l ~ /^Tasks:/) {
                out("Tasks " field_before("total") " run " field_before("running"))
            } else if (l ~ /Cpu\(s\)/) {
                out("CPU us " field_before("us") " sy " field_before("sy") " id " field_before("id"))
            } else if (l ~ /Mem/ && l !~ /Swap/) {
                unit = ($1 == "KiB") ? 1024 : 1
                tot = field_before("total"); used = field_before("used")
                if (unit == 1024) { tot = int(tot / 1024); used = int(used / 1024) }
                else { tot = int(tot); used = int(used) }
                out("Mem " used "/" tot "M")
            } else if (l ~ /^ *PID /) {
                for (j = 1; j <= NF; j++) {
                    if ($j == "PID") pid = j
                    if ($j == "%CPU") cpu = j
                    if ($j == "%MEM") mem = j
                    if ($j == "COMMAND") cmd = j
                }
                out(sprintf("%5s %5s %4s %s", "PID", "%CPU", "%MEM", "COMMAND"))
                first = i + 1
                break
            }
        }
        if (first == 0 || !pid || !cpu || !mem || !cmd) exit 1
        for (i = first; i <= n && nout < rows; i++) {
            $0 = line[i]
            if (NF < cmd) continue
            out(sprintf("%5s %5s %4s %s", $pid, $cpu, $mem, $cmd))
        }
        printf "%s", text
    }'
}

one_frame() {   # $1 cols, $2 rows, $3 eol
    LC_ALL=C "$TOP" -b -n2 -d "$DELAY" 2>/dev/null | compact "$1" "$2" "$3"
}

cmd_frame() {
    set -- $(size)
    DELAY=${LCD_TOP_DELAY:-1}
    one_frame "$1" "$2" ""
    echo
}

cmd_run() {
    exec <"$TTY" >"$TTY" 2>&1 || exit 1
    export TERM=linux LC_ALL=C
    eol=$(printf '\033[K')
    # no screen blanking or power-down on the LCD, cursor off, clear
    printf '\033[9;0]\033[14;0]\033[?25l\033[H\033[2J'
    while :; do
        set -- $(size)
        f=$(one_frame "$1" "$2" "$eol")
        if [ -z "$f" ]; then sleep 5; continue; fi
        printf '\033[H%s\033[J' "$f"
    done
}

root_is_ro() { [ -z "$SKIP_SYSTEM" ] && grep -Eq '^[^ ]+ / [^ ]+ ro[, ]' /proc/mounts; }

kill_matching() {   # kill processes whose command line contains $1
    [ -n "$SKIP_SYSTEM" ] && return 0
    for d in /proc/[0-9]*; do
        p=${d#/proc/}
        [ "$p" = "$$" ] && continue
        if tr '\0' ' ' <"$d/cmdline" 2>/dev/null | grep -q "$1"; then kill "$p" 2>/dev/null; fi
    done
}

reload_init() {
    [ -n "$SKIP_SYSTEM" ] && return 0
    telinit q 2>/dev/null || init q 2>/dev/null
}

edit_inittab() {   # $1 old pattern (regex), $2 new line
    grep -q "^$1" "$INITTAB" || die "no matching line for tty1 in $INITTAB (looking for: $1)"
    [ -f "$INITTAB.sadiy-orig" ] || cp "$INITTAB" "$INITTAB.sadiy-orig"
    sed -e "s|^$1.*\$|$2|" "$INITTAB" >"$INITTAB.new" || die "sed failed"
    cat "$INITTAB.new" >"$INITTAB" || die "could not write $INITTAB"
    rm -f "$INITTAB.new"
}

with_rw_root() {      # $1 name of the action (for the message), then the function to run
    what=$1; shift
    [ -z "$SKIP_SYSTEM" ] && [ "$(id -u)" != 0 ] && die "run as root: sudo sh $SELF $what"
    was_ro=0
    if root_is_ro; then was_ro=1; mount -o remount,rw / || die "could not remount / read-write"; fi
    "$@"
    rc=$?
    [ "$was_ro" = 1 ] && mount -o remount,ro / 2>/dev/null
    return $rc
}

do_install() {
    if grep -q "^$MINE\$" "$INITTAB"; then echo "already installed in $INITTAB"; else
        edit_inittab "1:[0-9]*:respawn:/sbin/getty[^#]*tty1" "$MINE"
    fi
    mkdir -p "$(dirname "$DEST")" || die "no $(dirname "$DEST")"
    if [ "$(cd "$(dirname "$SELF")" && pwd)/$(basename "$SELF")" != "$DEST" ]; then cp "$SELF" "$DEST" && chmod 755 "$DEST" || die "could not copy to $DEST"; fi
    reload_init
    kill_matching "getty 38400 tty1"      # init starts the new entry; ttyPS0 keeps its login
    echo "installed: tty1 now shows top ($DEST run). Undo with: sudo sh $DEST remove"
}

do_remove() {
    if grep -q "^$MINE\$" "$INITTAB"; then edit_inittab "1:[0-9]*:respawn:$DEST run" "$GETTY"; else echo "not installed in $INITTAB"; fi
    rm -f "$DEST"
    reload_init
    kill_matching "ebaz_lcd_top run"
    echo "removed: tty1 has its login prompt again"
}

cmd_status() {
    if grep -q "^$MINE\$" "$INITTAB" 2>/dev/null; then echo "inittab: top on tty1 (installed)"; else echo "inittab: not installed ($(grep -E '^1:' "$INITTAB" 2>/dev/null))"; fi
    [ -x "$DEST" ] && echo "script:  $DEST" || echo "script:  $DEST missing"
    set -- $(size); echo "console: $1 columns x $2 rows ($TTY)"
    if [ -z "$SKIP_SYSTEM" ]; then
        for d in /proc/[0-9]*; do tr '\0' ' ' <"$d/cmdline" 2>/dev/null | grep -q "ebaz_lcd_top run" && echo "running: pid ${d#/proc/}"; done
    fi
    return 0
}

case "$1" in
    install) with_rw_root install do_install ;;
    remove)  with_rw_root remove do_remove ;;
    status)  cmd_status ;;
    frame)   cmd_frame ;;
    run)     cmd_run ;;
    *)       sed -n '2,11p' "$SELF" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
