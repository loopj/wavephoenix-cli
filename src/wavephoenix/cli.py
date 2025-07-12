import argparse
import asyncio
import os
import re
import sys
from typing import List
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from tqdm import tqdm

# UUIDs for services and characteristics
OTA_SERVICE_UUID = "1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0"
OTA_CONTROL_UUID = "f7bf3564-fb6d-4e53-88a4-5e37e0326063"
OTA_DATA_UUID = "984227f3-34fc-4045-a5d0-2c581f81a153"
APPLOADER_VERSION_UUID = "4f4a2368-8cca-451e-bfff-cf0e2ee23e9f"
OTA_VERSION_UUID = "4cc07bcf-0868-4b32-9dad-ba4cc41e5316"
GECKO_BOOTLOADER_UUID = "25f05c0a-e917-46e9-b2a5-aa2be1245afe"
APPLICATION_VERSION_UUID = "0d77cc11-4ac1-49f2-bfa9-cd96ac7a92f8"

# BLE device name (replace with the actual name)
DEVICE_NAME = "WavePhoenix"

# OTA control command values
START_OTA = bytearray([0x00])  # Start OTA update
FINISH_OTA = bytearray([0x03])  # OTA upload finished
CLOSE_CONNECTION = bytearray([0x04])  # Close OTA connection

# Chunk size for sending firmware
CHUNK_SIZE = 64  # Use 64-byte chunks

# Error codes for OTA update
ERROR_CODES = {
    0x80: "CRC check failed.",
    0x81: "Client tried to send data or finish the upload before starting it.",
    0x82: "AppLoader has run out of buffer space.",
    0x83: "New firmware image is too large to fit into flash, or overlaps with AppLoader.",
    0x84: "GBL file parsing failed. Make sure you are sending a valid .gbl firmware file (not a .hex file).",
    0x85: "The Gecko bootloader cannot erase or write flash as requested by AppLoader, the download area may be too small to fit the entire GBL image.",
    0x86: "Wrong type of bootloader. For example, target device has UART DFU bootloader instead of OTA bootloader installed.",
    0x87: "New application image is rejected because it would overlap with the AppLoader.",
}


async def find_device_by_name(device_name: str) -> str | None:
    """Scan for devices and return the address of the first device with the given name."""

    devices = await BleakScanner.discover()
    for device in devices:
        if device.name and device_name in device.name:
            return device.address

    return None


async def scan_for_devices(device_name: str) -> List[BLEDevice]:
    """Scan for devices with the given name."""

    print("Scanning for WavePhoenix devices...")
    devices = await BleakScanner.discover()
    found_devices = [
        device for device in devices if device.name and device_name in device.name
    ]

    return found_devices


async def connect_to_device(address: str | None = None) -> BleakClient | None:
    """Connect to the BLE device, by address if provided, or by scanning for a named device."""

    # If address is not provided, find the first WavePhoenix device
    if not address:
        address = await find_device_by_name(DEVICE_NAME)
        if not address:
            return None

    # Connect to the device, and return the connected client
    try:
        client = BleakClient(address)
        await client.connect()
        if not client.is_connected:
            print(f"Failed to connect to the BLE device at address {address}")
            return None
        return client
    except BleakError as e:
        print(f"Error connecting to BLE device: {e}")
        return None


async def check_ota_service_and_characteristics(client: BleakClient) -> bool:
    """Check if the device has the expected OTA service and characteristics."""

    services = client.services
    if not services or len(services.services) == 0:
        return False

    for service in services:
        if service.uuid == OTA_SERVICE_UUID:
            has_control_char = False
            has_data_char = False
            for char in service.characteristics:
                if char.uuid == OTA_CONTROL_UUID and "write" in char.properties:
                    has_control_char = True
                if (
                    char.uuid == OTA_DATA_UUID
                    and "write-without-response" in char.properties
                ):
                    has_data_char = True

            return has_control_char and has_data_char

    return False


async def get_device_info(client: BleakClient) -> None:
    """Retrieve and display version information from the device."""

    try:
        # Read version information from the device
        apploader_version = await client.read_gatt_char(APPLOADER_VERSION_UUID)
        ota_version = await client.read_gatt_char(OTA_VERSION_UUID)
        bootloader_version = await client.read_gatt_char(GECKO_BOOTLOADER_UUID)
        app_version = await client.read_gatt_char(APPLICATION_VERSION_UUID)

        # Display the version information
        print("Device information:")
        print(f"- Device Name:              {DEVICE_NAME}")
        print(f"- BLE Address:              {client.address}")
        print(f"- Apploader Version:        {apploader_version.hex()}")
        print(f"- OTA Version:              {ota_version.hex()}")
        print(f"- Gecko Bootloader Version: {bootloader_version.hex()}")
        print(f"- Application Version:      {app_version.hex()}")

    except Exception as e:
        print(f"Error retrieving device info: {e}")


async def ota_firmware_update(
    client: BleakClient, firmware_file_path: str, sync: bool, sleep_ms: float
) -> None:
    """Perform an OTA firmware update."""

    try:
        print("Starting OTA firmware update...\n")

        await asyncio.sleep(0.2)
        await client.write_gatt_char(OTA_CONTROL_UUID, START_OTA)
        await asyncio.sleep(0.5)

        file_size = os.path.getsize(firmware_file_path)
        with (
            open(firmware_file_path, "rb") as firmware_file,
            tqdm(
                total=file_size,
                unit="B",
                unit_scale=True,
                desc="Updating",
                unit_divisor=1024,
            ) as progress_bar,
        ):
            while True:
                chunk = firmware_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                if sync:
                    await client.write_gatt_char(OTA_DATA_UUID, chunk)
                else:
                    await client.write_gatt_char(OTA_DATA_UUID, chunk, response=False)
                    await asyncio.sleep(sleep_ms / 1000)
                progress_bar.update(len(chunk))

        await asyncio.sleep(0.2)
        try:
            await client.write_gatt_char(OTA_CONTROL_UUID, FINISH_OTA)
        except BleakError as e:
            # Use regex to extract the error code
            # NOTE: This is corebluetooth-specific and may not work with other BLE stacks
            match = re.search(r"Code=(\d+)", str(e))
            if match:
                code = int(match.group(1), 10)  # Ensure code is interpreted as decimal
                error_reason = ERROR_CODES.get(code, "Unknown error code")
                print(f"Error applying OTA update: {error_reason}")
            else:
                print("Unknown error applying OTA update.")

            return

        print("OTA firmware update complete!")
    except Exception as e:
        print(f"Error during OTA firmware update: {e}")


async def main() -> None:
    """Main entry point for the CLI script."""

    parser = argparse.ArgumentParser(description="WavePhoenix CLI")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # Define the "flash" command
    flash_parser = subparsers.add_parser(
        "flash", help="Flash firmware to a WavePhoenix device"
    )
    flash_parser.add_argument(
        "firmware", type=str, help="Path to the firmware file (.gbl)"
    )
    flash_parser.add_argument(
        "--address", type=str, help="Optional BLE device address to flash"
    )
    flash_parser.add_argument(
        "--mode",
        choices=["reliability", "speed"],
        default="speed",
        help="Transfer mode: 'reliability' uses write with response, 'speed' uses write without response (default: speed)",
    )
    flash_parser.add_argument(
        "--sleep",
        type=float,
        default=5.0,
        help="Sleep duration in ms between chunks in speed mode (default: 5 ms)",
    )

    # Define the "scan" command
    subparsers.add_parser("scan", help="Scan for WavePhoenix devices in DFU mode")

    # Define the "info" command
    info_parser = subparsers.add_parser(
        "info", help="Display version information for a WavePhoenix device"
    )
    info_parser.add_argument("--address", type=str, help="Optional BLE device address")

    # Parse command-line arguments
    args = parser.parse_args()

    # Handle command-line arguments and execute the appropriate command
    if args.command == "scan":
        found_devices = await scan_for_devices(DEVICE_NAME)
        if not found_devices:
            print("No WavePhoenix devices found. Make sure the device is in DFU mode.")
            return

        for device in found_devices:
            print(f"- Found WavePhoenix device at address: {device.address}")

    elif args.command == "flash":
        if not os.path.exists(args.firmware):
            print(f"Error: Firmware file '{args.firmware}' not found.")
            sys.exit(1)

        client = await connect_to_device(args.address)
        if not client:
            print(
                "No WavePhoenix devices found. Make sure the device is in DFU mode and nearby."
            )
            return

        try:
            if await check_ota_service_and_characteristics(client):
                await ota_firmware_update(
                    client, args.firmware, args.mode == "reliability", args.sleep
                )
            else:
                print(
                    "Device does not have the expected OTA service or characteristics."
                )
        finally:
            await client.disconnect()

    elif args.command == "info":
        client = await connect_to_device(args.address)
        if not client:
            print(
                "No WavePhoenix devices found. Make sure the device is in DFU mode and nearby."
            )
            return

        try:
            await get_device_info(client)
        finally:
            await client.disconnect()

    else:
        parser.print_help()


# Provide a non-async entry point for the script
def run() -> None:
    asyncio.run(main())


# Allow running the CLI script directly
if __name__ == "__main__":
    asyncio.run(main())
