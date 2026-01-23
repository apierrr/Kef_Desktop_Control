import asyncio
import socket
import sys
import os

import nest_asyncio  # pyright: ignore[reportMissingImports]
import customtkinter as ctk  # pyright: ignore[reportMissingImports]

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

nest_asyncio.apply()

ip_lsx = "192.168.1.12"

# Mapping des sources - copié de aiokef pour compatibilité
INPUT_SOURCES_20_MINUTES_LR = {
    "Bluetooth": 9,
    "Aux": 10,
    "Opt": 11,
    "Usb": 12,
    "Wifi": 2,
}

STANDBY_OPTIONS = [20, 60, None]  # in minutes, None = never

# Construire INPUT_SOURCES: {source_name: {standby_time: (LR_code, RL_code)}}
INPUT_SOURCES = {}
for _source, _code in INPUT_SOURCES_20_MINUTES_LR.items():
    _LR_mapping = {t: _code + i * 16 for i, t in enumerate(STANDBY_OPTIONS)}
    INPUT_SOURCES[_source] = {t: (LR, LR + 64) for t, LR in _LR_mapping.items()}

# Construire INPUT_SOURCES_RESPONSE: {code: (source, standby_time, orientation)}
INPUT_SOURCES_RESPONSE = {}
for _source, _mapping in INPUT_SOURCES.items():
    for _t, (_LR, _RL) in _mapping.items():
        INPUT_SOURCES_RESPONSE[_LR] = (_source, _t, "L/R")
        INPUT_SOURCES_RESPONSE[_RL] = (_source, _t, "R/L")

# Fix de aiokef pour certains codes spéciaux
INPUT_SOURCES_RESPONSE[48] = INPUT_SOURCES_RESPONSE.get(82, ("Wifi", 60, "R/L"))
INPUT_SOURCES_RESPONSE[15] = ("Bluetooth", 20, "L/R")  # Bluetooth_paired

class KefConnection:
    """Gère une connexion keep-alive aux enceintes KEF (comme aiokef)."""
    def __init__(self, host, port=50001):
        self.host = host
        self.port = port
        self._reader = None
        self._writer = None
        self._lock = asyncio.Lock()
        self._disconnect_task = None
        self._keep_alive = 1.0  # Secondes avant déconnexion auto
    
    def _schedule_disconnect(self):
        """Planifie une déconnexion après _keep_alive secondes."""
        if self._disconnect_task is not None:
            self._disconnect_task.cancel()
        self._disconnect_task = asyncio.get_event_loop().create_task(
            self._delayed_disconnect()
        )
    
    async def _delayed_disconnect(self):
        await asyncio.sleep(self._keep_alive)
        await self._disconnect()
    
    async def _disconnect(self):
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except:
                pass
            self._writer = None
            self._reader = None
    
    async def _ensure_connected(self):
        # Annuler la déconnexion planifiée
        if self._disconnect_task is not None:
            self._disconnect_task.cancel()
            self._disconnect_task = None
        
        if self._writer is None or self._writer.is_closing():
            # Fermer proprement si en cours de fermeture
            if self._writer is not None:
                await self._disconnect()
            
            # Nouvelle connexion
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, family=socket.AF_INET),
                timeout=2.0
            )
    
    async def send_command(self, cmd: bytes, retries=10) -> bytes:
        async with self._lock:
            last_error = None
            for attempt in range(retries):
                try:
                    await self._ensure_connected()
                    self._writer.write(cmd)
                    await self._writer.drain()
                    data = await asyncio.wait_for(self._reader.read(100), timeout=2.0)
                    # Planifier la déconnexion après le délai keep-alive
                    self._schedule_disconnect()
                    return data
                except Exception as e:
                    last_error = e
                    await self._disconnect()
                    if attempt < retries - 1:
                        await asyncio.sleep(0.5)
            
            raise last_error

# Connexion globale réutilisable
kef_conn = KefConnection(ip_lsx)

async def get_current_state():
    """Lit l'état actuel de l'enceinte et retourne (source, standby_time, orientation, is_on)"""
    GET_SOURCE = bytes([0x47, 0x30, 0x80])
    response = await kef_conn.send_command(GET_SOURCE)
    
    raw_code = response[3]
    is_on = raw_code <= 128
    code = raw_code % 128
    
    if code in INPUT_SOURCES_RESPONSE:
        source, standby_time, orientation = INPUT_SOURCES_RESPONSE[code]
        return source, standby_time, orientation, is_on
    else:
        # Valeurs par défaut si code inconnu
        return "Unknown", 20, "L/R", is_on

async def set_source_preserving_settings(source_name: str):
    """
    Change la source en préservant standby_time et orientation.
    Utilise la logique correcte de aiokef.
    """
    if source_name not in INPUT_SOURCES:
        raise ValueError(f"Source inconnue: {source_name}. Sources valides: {list(INPUT_SOURCES.keys())}")
    
    # Lire l'état actuel pour préserver les settings
    current_source, standby_time, orientation, is_on = await get_current_state()
    
    # Si standby_time est None (never) mais pas dans nos options, utiliser 20
    if standby_time not in STANDBY_OPTIONS:
        standby_time = 20
    
    # Obtenir le code pour la nouvelle source avec les mêmes settings
    orientation_index = 0 if orientation == "L/R" else 1
    new_code = INPUT_SOURCES[source_name][standby_time][orientation_index]
    
    # S'assurer qu'on allume l'enceinte (code < 128)
    new_code = new_code % 128
    
    # Envoyer la commande
    SET_SOURCE = bytes([0x53, 0x30, 0x81, new_code])
    await kef_conn.send_command(SET_SOURCE)

async def turn_off_preserving_settings():
    """Éteint l'enceinte en préservant tous les paramètres."""
    # Lire l'état actuel
    current_source, standby_time, orientation, is_on = await get_current_state()
    
    # Si source inconnue, utiliser Wifi par défaut
    if current_source not in INPUT_SOURCES:
        current_source = "Wifi"
    
    if standby_time not in STANDBY_OPTIONS:
        standby_time = 20
    
    # Bug KEF: crash si standby=20min, donc on passe à 60min avant d'éteindre
    if standby_time == 20:
        standby_time = 60
    
    orientation_index = 0 if orientation == "L/R" else 1
    # Obtenir le code et ajouter 128 pour éteindre
    code = INPUT_SOURCES[current_source][standby_time][orientation_index]
    off_code = (code % 128) + 128
    
    SET_SOURCE = bytes([0x53, 0x30, 0x81, off_code])
    await kef_conn.send_command(SET_SOURCE)

async def kef_aux():
    await set_source_preserving_settings("Aux")

async def kef_bluetooth():
    await set_source_preserving_settings("Bluetooth")

async def kef_opt():
    await set_source_preserving_settings("Opt")

async def kef_wifi():
    await set_source_preserving_settings("Wifi")

async def turn_off():
    await turn_off_preserving_settings()

def run_async_task(coro):
    loop = asyncio.get_event_loop()
    loop.create_task(coro)

async def get_volume():
    GET_VOLUME = bytes([0x47, 0x25, 0x80])
    response = await kef_conn.send_command(GET_VOLUME)
    volume = response[3]
    # Si >= 128, c'est muté, on retourne le volume sans le bit mute
    if volume >= 128:
        volume -= 128
    return volume

async def set_volume(volume: int):
    volume = max(0, min(100, volume))
    SET_VOLUME = bytes([0x53, 0x25, 0x81, volume])
    await kef_conn.send_command(SET_VOLUME)

class KefGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("KEF Controller")
        self.geometry("420x420")
        self.resizable(False, False)
        self.iconbitmap(resource_path("kef.ico"))

        # États pour gestion du drag et volume en attente
        self.is_dragging = False
        self.pending_volume = None
        self.drag_timeout_id = None

        # Boutons sources
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=30)
        btn_opts = {"master": btn_frame, "width": 160, "height": 48, "corner_radius": 16, "font": ("SF Pro Display", 18, "bold")}
        ctk.CTkButton(**btn_opts, text="Aux", command=lambda: run_async_task(kef_aux())).grid(row=0, column=0, padx=16, pady=10)
        ctk.CTkButton(**btn_opts, text="Bluetooth", command=lambda: run_async_task(kef_bluetooth())).grid(row=0, column=1, padx=16, pady=10)
        ctk.CTkButton(**btn_opts, text="Optical", command=lambda: run_async_task(kef_opt())).grid(row=1, column=0, padx=16, pady=10)
        ctk.CTkButton(**btn_opts, text="Wifi", command=lambda: run_async_task(kef_wifi())).grid(row=1, column=1, padx=16, pady=10)
        ctk.CTkButton(self, text="Turn Off", command=lambda: run_async_task(turn_off()), width=340, height=40, corner_radius=16, fg_color="#e74c3c", hover_color="#c0392b", font=("SF Pro Display", 16, "bold")).pack(pady=(0, 30))

        # Volume
        self.volume_label = ctk.CTkLabel(self, text="Volume: ...", font=("SF Pro Display", 32, "bold"))
        self.volume_label.pack(pady=(0, 10))

        self.volume_scale = ctk.CTkSlider(self, from_=0, to=100, width=340, height=24, command=self.on_volume_drag, number_of_steps=100)
        self.volume_scale.pack(pady=(0, 10))
        self.volume_scale.bind('<ButtonRelease-1>', self.on_volume_release)
        self.volume_scale.bind('<ButtonPress-1>', self.on_volume_press)

        self.update_volume_display()


    def on_volume_press(self, event=None):
        self.is_dragging = True
        # Si un timeout précédent existe, l'annuler
        if self.drag_timeout_id:
            self.after_cancel(self.drag_timeout_id)
            self.drag_timeout_id = None

    def on_volume_drag(self, value):
        # Affiche le volume choisi en temps réel et bloque update auto
        value = int(float(self.volume_scale.get()))
        self.pending_volume = value
        self.volume_label.configure(text=f"Volume: {value}")

    def on_volume_release(self, event=None):
        value = int(float(self.volume_scale.get()))
        self.pending_volume = value
        self.is_dragging = False
        run_async_task(self._set_and_confirm_volume(value))

    async def _set_and_confirm_volume(self, value):
        try:
            await set_volume(value)
        except Exception as e:
            self.volume_label.configure(text=f"Erreur: {e}")
        # Après confirmation, on laisse la valeur affichée jusqu'à la prochaine update réelle
        self.pending_volume = None
        # On attend un court délai avant de réactiver update auto (pour éviter snap-back)
        def clear_pending():
            self.pending_volume = None
            self.update_volume_display()
        self.drag_timeout_id = self.after(600, clear_pending)

    def update_volume_display(self):
        # Si on est en drag ou en attente de confirmation, ne pas écraser l'affichage
        if self.is_dragging or self.pending_volume is not None:
            self.after(500, self.update_volume_display)
            return
        async def update():
            try:
                vol = await get_volume()
                self.volume_label.configure(text=f"Volume: {vol}")
                self.volume_scale.set(vol)
            except Exception as e:
                # Ne pas afficher l'erreur, juste réessayer plus tard
                pass
            self.after(5000, self.update_volume_display)  # Polling toutes les 5 secondes
        run_async_task(update())


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    gui = KefGUI()
    def poll_loop():
        try:
            loop.call_soon(loop.stop)
            loop.run_forever()
        except Exception:
            pass
        gui.after(50, poll_loop)
    gui.after(50, poll_loop)
    gui.mainloop()

if __name__ == "__main__":
    
    main()
