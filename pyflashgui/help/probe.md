[&larr; Contents](manual.md)

# Probe and target

The bar across the top of the window says what pyflashgui is connected through and what to. Everything else in the window depends on it.

| | |
|---|---|
| **Through** | What reaches the probe. *pyOCD* works with many probes and Cortex-M devices. *J-Link Commander* works with a J-Link and every device SEGGER's software knows. *Simulated* is a probe and a target that exist only in memory, for trying pyflashgui with no hardware. |
| **Probe** | The debug probe, by its description and serial number. **Refresh** looks again for what is plugged in. |
| **Target** | The device on the end of the probe. Type any part of its name to find it. |
| **Speed** | How fast the probe clocks the debug port. *Probe's own* leaves it to the probe. |
| **Interface** | With J-Link Commander only: how the probe is wired to the device. |
| **Connect** | Attaches the probe to the target, and becomes **Disconnect**. |

The bar at the foot of the window says what is known of the target that is chosen: who makes it, its core where that is known, and how much flash and RAM it has.

What is chosen is kept in the [workspace](manual.md): the target and the speed belong to the product being worked on, and the probe is remembered by its serial number, so a bench with two probes on it connects through the same one each time.

## Connecting

**The target is stopped while it is connected**, and runs again when it is disconnected or reset. Connecting to a device that is doing something is therefore not free: it stops doing it.

If connecting fails, the [Event Log](manual.md) says what the probe reported. The usual causes are the target not being powered, the wrong target chosen, or a cable too long for the speed: try a lower **Speed**.

## Targets

The list is every target pyOCD has built in, and every device in the CMSIS-Packs installed on this computer. A target that is built in has its memory known before anything is connected, so the [Memory Map](memory-map.md) can check the files against it straight away. One from a pack is checked once it is connected to.

## J-Link Commander

Choosing *J-Link Commander* under **Through** uses a J-Link by way of SEGGER's own command line program, which comes with SEGGER's J-Link software. It reaches every device that software knows, which is far more than Cortex-M: Cortex-A and Cortex-R, RISC-V and others. The price is that it works with a J-Link and nothing else, and needs SEGGER's software installed.

- **SEGGER's software is yours to install**, and its licence is between you and SEGGER. pyflashgui never carries it. It is for genuine SEGGER probes, and SEGGER describes J-Link Commander as a tool for development, not for production programming.
- **Target** is the device's name as SEGGER's software has it, such as `STM32F103ZE`. The list is read from that software, with each device's maker, core and memory; a name not on it can be typed.
- **Interface** appears for this choice only: SWD, JTAG, cJTAG or FINE, as the device is wired.
- **The Memory Map goes by SEGGER's list of the device's memory**, which says where its flash and RAM are and may not give every address they can be reached at. So a file outside what is listed is a warning and not a refusal, and SEGGER's software has the last word. The list does not say how the flash is divided into sectors, so the map does not say how much is erased.
- **The bar shows that something is happening, not how far along it is**, since J-Link Commander does not say.
- **Connect** checks that the probe and the device answer. Nothing is held open between one operation and the next; each attaches again by itself.

If pyflashgui does not find J-Link Commander, *Tools > Settings > J-Link Commander location...* says where it is.

**Tried on one board so far.** Listing the probe, connecting and reading were tried on an XMC4500 through its on-board J-Link, and what was read matched SEGGER's own tool. Programming, erasing and resetting this way have not yet been tried on a probe.

## Probes with pyOCD

With *pyOCD* chosen, every probe is reached through pyOCD, which has a driver for each of the ways a probe talks over USB. Which probes work is therefore pyOCD's list:

| Probe | How pyOCD talks to it | What to install | Worth knowing |
|---|---|---|---|
| **CMSIS-DAP probes** | Arm's open CMSIS-DAP protocol | Windows: nothing. Linux: a udev rule. | The widest choice, and the one to pick when there is a choice. |
| **ST-Link** v2, v2-1 and v3 | ST's own protocol | Windows: ST's USB driver, where Windows has none for it. Linux: a udev rule. | Recent ST-Link firmware reaches only STM32 targets: for any other maker's device, use another probe. Firmware V2J24 or newer. |
| **J-Link** | SEGGER's own library, or CMSIS-DAP for a J-Link switched to that mode | SEGGER's J-Link software, on Windows and on Linux. | In its own mode it is not offered until that software is installed. Current J-Link BASE, PLUS, EDU, ULTRA+ and PRO models can be set to start as a CMSIS-DAP probe instead, with SEGGER's Configurator, and are then used like any other. |
| **Picoprobe** | The original Raspberry Pi Pico probe firmware | Linux: a udev rule. | The Pico's current debug probe firmware is CMSIS-DAP instead, and is the one to have. |

CMSIS-DAP is a protocol and not a product, so a great many probes speak it. Among those pyOCD's documentation names:

- Raspberry Pi Debug Probe, and a Pico running the debug probe firmware
- DAPLink, on its own and built into Arm Mbed and micro:bit boards
- NXP MCU-Link, MCU-Link Pro, LPC-Link2 and OpenSDA
- Microchip Atmel-ICE, and the EDBG on Microchip's boards
- Infineon (Cypress) KitProg3 and MiniProg4
- Keil ULINKplus
- TI XDS110, standalone and on TI LaunchPads. It is asked for one reply at a time, which some versions of its firmware need; pyflashgui sets that itself. pyOCD's udev rules do not include it, so on Linux it wants a rule of its own or the one TI's software installs.

**The target has to be an Arm Cortex-M, whichever probe it is.** The probe carries the debug port; what is on the far side of it is pyOCD's to understand, and Cortex-M is what it understands. A probe that can reach other kinds of processor with its maker's own software still reaches only Cortex-M here.

On Linux a probe is usable without root once a udev rule allows it; pyOCD publishes [a set of them](https://github.com/pyocd/pyOCD/tree/main/udev).

Vendor software is never bundled with pyflashgui: install the vendor's own, and pyflashgui finds the probe.
