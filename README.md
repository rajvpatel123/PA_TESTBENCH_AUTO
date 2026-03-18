# PA_TESTBENCH_AUTO

PA Testbench with **automatic VISA instrument discovery**.

Unlike the hardcoded version, this testbench scans all connected VISA resources on startup, sends `*IDN?` to each, and automatically maps them to the correct driver — no GPIB address or USB ID configuration required.

## How Auto-Discovery Works

1. `discover_instruments()` in `utils/visa_helper.py` calls `rm.list_resources()` to enumerate all VISA addresses.
2. Each resource is queried with `*IDN?`.
3. The IDN response is matched against `_IDN_MAP` (model keyword → driver class).
4. A human-readable name is auto-generated (e.g. `Agilent_E3648A_GPIB10`).
5. The driver is instantiated, connected, and added to the registry.

## Supported Instruments

| Instrument | Driver |
|---|---|
| Keysight E36233A / E36234A | `KeysightE36xxSupply` |
| Agilent E3648A | `AgilentE3648ASupply` |
| HP 6633B | `HP6633BSupply` |
| Keysight 34461A / 34465A | `Keysight3446xDMM` |
| Keysight PXA N9030A | `PXAN9030A` |
| R&S SMBV100B | `RSSMBV100B` |

## Project Structure

```
PA_TESTBENCH_AUTO/
├── drivers/          # Instrument driver classes
├── tabs/             # Tkinter UI tabs
├── utils/
│   ├── visa_helper.py    # Auto-discovery + registry logic
│   └── logger.py         # Shared logger
└── main.py           # App entry point
```

## Adding a New Instrument

1. Create a driver class in `drivers/`.
2. Add it to `_IDN_MAP` in `utils/visa_helper.py` with the model keyword(s) from its `*IDN?` response.
3. That's it — it will be auto-discovered on next launch.
