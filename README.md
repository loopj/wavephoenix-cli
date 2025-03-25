# WavePhoenix CLI

CLI for [WavePhoenix](https://github.com/loopj/wavephoenix), an open-source WaveBird receiver implementation.

Supports scanning for devices in DFU mode, flashing firmware, and dumping version information.

## Installation

### pip

WavePhoenix CLI is available on PyPI and can be installed with pip.

```bash
pip install wavephoenix
```

### pipx

[pipx](https://github.com/pypa/pipx) allows for the global installation of Python applications in isolated environments.

```bash
pipx install wavephoenix
```

## Entering DFU Mode

Hold the "pair" button on the device while plugging it in to enter DFU mode.

## Usage

Scan for devices in DFU mode:

```bash
wavephoenix scan
```

Flash firmware to a device in DFU mode:

```bash
wavephoenix flash firmware.gbl
```

Dump version information from a device in DFU mode:

```bash
wavephoenix info
```

> [!NOTE]
> Devices will leave DFU mode after `flash` or `info` commands are executed.
