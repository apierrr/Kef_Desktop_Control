# KEF Desktop Control

A simple Python GUI application to control a KEF LSX speaker over the network.

## Features

- Switch input sources (Aux, Bluetooth, Optical, Wifi)
- Get and set speaker volume
- Turn the speaker off
- Modern GUI using [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- Async operations with [aiokef](https://github.com/GuilhemSaurel/aiokef) and [asyncio]
- Compatible with PyInstaller for easy packaging

## Requirements

- Python 3.7+
- [aiokef](https://github.com/GuilhemSaurel/aiokef)
- [customtkinter](https://github.com/TomSchimansky/CustomTkinter)
- [nest_asyncio](https://github.com/erdewit/nest_asyncio)

Install dependencies with:

```sh
python -m venv venvKef_Desktop_Control
```
```sh
.\venvKef_Desktop_Control\Scripts\activate
```
```sh
pip install aiokef customtkinter nest_asyncio
```

## Usage

1. Set your LSX speaker's IP address in `main.py`:

    ```python
    ip_lsx = "192.168.1.10"
    ```

2. Run the application:

    ```sh
    python main.py
    ```
## Packaging

To bundle the app with PyInstaller, use:

```sh
pyinstaller --onefile --noconsole --icon=kef.ico --add-data "kef.ico;." --add-data "[PATH TO FOLDER THAT CONTAINS YOUR VENV]\venvKef_Desktop_Control\Lib\site-packages\aiokef\_static_version.py;aiokef" main.py