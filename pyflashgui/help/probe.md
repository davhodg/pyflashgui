[&larr; Contents](manual.md)

# Probe and target

The bar across the top of the window says what pyflashgui is connected through and what to. Everything else in the window depends on it.

| | |
|---|---|
| **Through** | What reaches the probe. *pyOCD* is the real one. *Simulated* is a probe and a target that exist only in memory, for trying pyflashgui with no hardware. |
| **Probe** | The debug probe, by its description and serial number. **Refresh** looks again for what is plugged in. |
| **Target** | The device on the end of the probe. Type any part of its name to find it. |
| **Speed** | How fast the probe clocks the debug port. *Probe's own* leaves it to the probe. |
| **Connect** | Attaches the probe to the target, and becomes **Disconnect**. |

What is chosen is kept in the [workspace](manual.md): the target and the speed belong to the product being worked on, and the probe is remembered by its serial number, so a bench with two probes on it connects through the same one each time.

## Connecting

**The target is stopped while it is connected**, and runs again when it is disconnected or reset. Connecting to a device that is doing something is therefore not free: it stops doing it.

If connecting fails, the [Event Log](manual.md) says what the probe reported. The usual causes are the target not being powered, the wrong target chosen, or a cable too long for the speed: try a lower **Speed**.

## Targets

The list is every target pyOCD has built in, and every device in the CMSIS-Packs installed on this computer. A target that is built in has its memory known before anything is connected, so the [Memory Map](memory-map.md) can check the files against it straight away. One from a pack is checked once it is connected to.

## Probes and drivers

| Probe | Windows | Linux |
|---|---|---|
| CMSIS-DAP, v1 or v2 | no driver needed | a udev rule |
| ST-Link | ST's driver | a udev rule |
| TI XDS110 | TI's driver | a udev rule |

CMSIS-DAP is a protocol and not a product, so a great many probes speak it: the Raspberry Pi Debug Probe, DAPLink, NXP MCU-Link and LPC-Link2, Microchip Atmel-ICE and EDBG, Infineon KitProg3, Keil ULINKplus, and the probe built into many development boards, which appears here as one. On Linux a probe is usable without root once a udev rule allows it; pyOCD publishes [a set of them](https://github.com/pyocd/pyOCD/tree/main/udev).

A TI XDS110 is asked for one reply at a time, which some versions of its firmware need. It makes that probe a little slower and costs nothing else.

Vendor software is never bundled with pyflashgui: install the vendor's own, and pyflashgui finds the probe.
