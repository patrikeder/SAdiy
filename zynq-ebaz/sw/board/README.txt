SAdiy on the EBAZ4205: where things are and what to run.   (this folder is ~/sadiy; it is replaced by deploy_to_board.sh)

RUN (from ~/sadiy or by full path, the scripts find their own files; no PYTHONPATH needed):
  ./status.sh   what is on the board: software build, PL state, devices, running sweepd, other copies of the software
  ./fpga.sh     load the bitstream if the PL has none or the wrong one (--force: again)
  ./bench.sh    bench mode (Pins / Synth tabs of the GUI): ADF4351, PE4302, ADS1115. No sweeping
  ./sweep.sh    sweeping with the PL engine
  ./selftest.sh pass/fail test of the PL sweep path with the engine's test ramp (no RF). ./sweep.sh --test-ramp shows the ramp in the GUI
  ./sim.sh      simulated chain, no hardware
  ./stop.sh     stop sweepd
GUI on the PC:  sh zynq-ebaz/sw/pc/gui.sh <this board's ip>

FILES (all under ~/sadiy):
  src/sadiy/                the Python code (sweepd, drivers, ...)           zynq-ebaz/sw/sadiy_ebaz/   EBAZ backends
  zynq-ebaz/rtl/regmap/     regmap.toml (register map of the PL engine)      fpga/                      bitstream and loader
  tools/bringup.py          gpio-map, synth-ce, pe4302-walk ...              zynq-ebaz/sw/tools/        pl_bringup.py, LCD tools
  config/default.toml       settings                                         BUILD_INFO                 commit of this copy

If you type python3 -m sadiy.server.sweepd yourself: first `. ~/sadiy/env.sh` (sets PYTHONPATH). Without it, from ~ the folder
~/sadiy is found as an empty package and the error is "No module named 'sadiy.server'".

Other copies of the software (for example ~/sadiy/bringup-pkg or ~/engine-pkg from earlier tests) are NOT updated by the
deploy and may be old: ./status.sh lists them with their build. Delete what you do not use (rm -r).
