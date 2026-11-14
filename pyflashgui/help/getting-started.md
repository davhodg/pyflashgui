[&larr; Contents](manual.md)

# Getting started

pyflashgui is a graphical flash programming tool: for Arm Cortex-M targets with any debug probe pyOCD supports, and for the many other devices a J-Link reaches through SEGGER's J-Link Commander.

**It is a tool for the bench**: for development, debugging and hobby use. It is not meant for production programming.

1. Choose the **Probe** and the **Target** in the bar across the top.
2. **Add...** the firmware files in the Files pane.
3. Look at the memory map under the list: it says whether they fit the target.
4. **Connect**, then **Program and verify**, then **Reset** to start what was written.

With no hardware, choose *Simulated* under **Using** and the same steps work on a target that exists only in memory.
