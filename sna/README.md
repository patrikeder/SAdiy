# SNA: scalar network analyzer (second project in SAdiy)

Second project next to the DIY spectrum analyzer (`../src`, `../hw`, ...). It reuses the same RF chain and the same SBC code, but needs neither the AD831 mixer, nor an IF filter, nor the 500 MHz low-pass.

## What it measures
S21 magnitude of a DUT from 35 MHz to 4.4 GHz (ADF4351 range; the detector is spec'd to 8 GHz).

## Signal path
ADF4351 -> 6 dB pad -> PE4302 -> [DUT] -> detector -> ADS1115 -> SBC

## Reuse from the spectrum analyzer
- Drivers: `../src/sadiy/drivers` (PE4302 done, ADF4351 register packing open, ADS1115 written but not yet on hardware)
- Sweep engine, `sweepd`, ZeroMQ protocol, terminal client, simulator
- Calibration table format (`../cal`)
- New in this project: SNA mode in `freqplan` (LO = RF directly, no IF) and thru normalisation in `cal`

## Files
- `bringup-plan.md`: signal path, calibration, software tasks, timeline, done criteria

## Status
Planned 2026-11-01. Nothing implemented yet.
