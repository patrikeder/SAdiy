# Adapter LCD (Sitronix ST7789), keys and LEDs for Linux

Written by session R, 2026-11-14. For session L. State of the hardware: built into `rtl/fpga` (bitstream
`build/fpga/ebaz_sadiy.bit`), **not tested on the board**.

## What the hardware provides

No PL logic: the PS SPI1 controller and two EMIO GPIO lines go straight to the pads.

| LCD pin (silk) | FPGA ball | Source | Linux |
|---|---|---|---|
| SCL | R19 | PS SPI1 SCLK (EMIO) | SPI1 clock |
| SDA | P20 | PS SPI1 MOSI (EMIO) | SPI1 data out |
| CS | T20 | PS SPI1 SS0 (EMIO), pad pull-up | chip select 0 |
| DC | R18 | EMIO GPIO 8 | gpio0 line 62 (54 + 8), `dc-gpios` |
| RES | N17 | EMIO GPIO 9, pad pull-up | gpio0 line 63 (54 + 9), `reset-gpios`, active low |

There is no backlight pin on the adapter's LCD header (backlight is not controllable). MISO is not connected.

## Keys and LEDs (EMIO GPIO, added later the same day)

| Adapter | Ball | EMIO n | Linux line (54 + n) | Notes |
|---|---|---|---|---|
| LED1..LED3 | H18, K17, E19 | 10, 11, 12 | 64, 65, 66 | output only, tri-stated until driven; polarity not verified (try both) |
| KEY1..KEY5 | T19, P19, U20, U19, V20 | 13..17 | 67..71 | input, pad pull-up, pressed reads 0 (`GPIO_ACTIVE_LOW`) |

The EMIO GPIO width is now 18 (was 16): third PS7 difference. Device tree (to verify):

```dts
/ {
    leds {
        compatible = "gpio-leds";
        led1 { label = "adapter:led1"; gpios = <&gpio0 64 GPIO_ACTIVE_HIGH>; };
        led2 { label = "adapter:led2"; gpios = <&gpio0 65 GPIO_ACTIVE_HIGH>; };
        led3 { label = "adapter:led3"; gpios = <&gpio0 66 GPIO_ACTIVE_HIGH>; };
    };
    keys {
        compatible = "gpio-keys";
        key1 { label = "KEY1"; linux,code = <KEY_1>; gpios = <&gpio0 67 GPIO_ACTIVE_LOW>; };
        key2 { label = "KEY2"; linux,code = <KEY_2>; gpios = <&gpio0 68 GPIO_ACTIVE_LOW>; };
        key3 { label = "KEY3"; linux,code = <KEY_3>; gpios = <&gpio0 69 GPIO_ACTIVE_LOW>; };
        key4 { label = "KEY4"; linux,code = <KEY_4>; gpios = <&gpio0 70 GPIO_ACTIVE_LOW>; };
        key5 { label = "KEY5"; linux,code = <KEY_5>; gpios = <&gpio0 71 GPIO_ACTIVE_LOW>; };
    };
};
```

(`gpio-keys` needs `#include <dt-bindings/input/input.h>`; `CONFIG_KEYBOARD_GPIO` and `CONFIG_LEDS_GPIO` must be
in the kernel: check your `.config`.) Without them, `gpioget` / `gpioset` on lines 64..71 work as well.
Key J20-vs-U20 silk question on the adapter is still open (see `pinmap.md`).

## What session L must do (boot image: one rebuild)

PS SPI1 is a PS7 setting, so FSBL / ps7_init and the device tree change. Your Phase 1 XSA does not have it yet.

1. In `rtl/vivado/phase1.tcl` add to the PS7 overrides:
   `CONFIG.PCW_SPI1_PERIPHERAL_ENABLE {1}`, `CONFIG.PCW_SPI1_SPI1_IO {EMIO}`, and
   `CONFIG.PCW_GPIO_EMIO_GPIO_WIDTH {18}` / `CONFIG.PCW_GPIO_EMIO_GPIO_IO {18}` (was 16; the GPIO_0 port becomes
   18 bits wide, lines 0..15 keep their numbers).
   Then tie the inputs like SPI0: `SPI1_MISO_I` to 0 and `SPI1_SS_I` to 1. Connecting the SPI1 outputs to pads is
   not needed in your design (my bitstream does that); unconnected outputs are fine.
   `rtl/scripts/check_ps7.sh` must then say IDENTICAL again (today it reports exactly these four keys).
2. Rebuild XSA, then the PetaLinux image. Because the PS7 setting is in the XSA, `spi1` appears in the generated
   device tree.
3. Kernel (already in your current build, checked in `kernel-build-artifacts/.config`): `CONFIG_SPI_CADENCE=y`,
   `CONFIG_FB_TFT=y`, `CONFIG_FB_TFT_ST7789V=y`. `CONFIG_FRAMEBUFFER_CONSOLE` is not set, so the panel shows nothing
   until something draws to `/dev/fb1`. `CONFIG_SPI_GPIO` is not set; it is not needed.
4. Device tree node for `system-user.dtsi` (to verify on 6.12, fbtft bindings are in
   `drivers/staging/fbtft`):

```dts
&spi1 {
    status = "okay";
    num-cs = <1>;

    display@0 {
        compatible = "sitronix,st7789v";
        reg = <0>;
        spi-max-frequency = <10000000>;     /* controller divides 150 MHz by 16 = 9.4 MHz */
        buswidth = <8>;
        dc-gpios    = <&gpio0 62 GPIO_ACTIVE_HIGH>;   /* EMIO 8 */
        reset-gpios = <&gpio0 63 GPIO_ACTIVE_LOW>;    /* EMIO 9, RES is active low */
        width  = <240>;                       /* PANEL SIZE NOT KNOWN: set to the real resolution */
        height = <240>;
        rotate = <0>;
        fps = <20>;
        debug = <0>;
    };
};
```

## Notes and risks

- Panel size and offset: 240x240 and 135x240 ST7789 modules need a RAM address offset (for 240x240 usually 80 rows
  in some rotations); the staging driver has no offset parameter, so a shifted picture is likely and may need a
  small driver patch. Tell me the module size and I will check the datasheet values.
- SPI1 clock: the EMIO path limits SCLK (to about 25 MHz); 9.4 MHz is conservative. The ST7789 write cycle of 66 ns
  allows about 15 MHz; try dividing by 8 (18.75 MHz) only after it works.
- Idle state: until the PS drives them, CS and RES are pulled up (panel deselected, not in reset), SCL pulled low.
- Check on the board: `gpioinfo` shows line 62 / 63 as `gpio0` EMIO lines. A logic analyzer on SCL / SDA / CS shows
  the first frame of the init sequence.
- The pads `lcd_*` are ports of `ebaz_sadiy_top` only. Do not constrain them in your Phase 1 design unless you also
  connect them there.
